#!/usr/bin/env python
"""Train EfficientNet-B0 on APTOS 2019 Blindness Detection.

Produces backend/models/efficientnet_b0_dr.pt — the checkpoint the live
/analyze endpoint loads. Uses the SAME preprocessing pipeline as inference
(see app/ml/preprocessing.py), handles class imbalance with weighted
CrossEntropyLoss, and selects checkpoints on validation Quadratic Weighted
Kappa.

Usage:
    pip install -r requirements-ml.txt
    python train_classifier.py --data-dir path/to/aptos --epochs 30 --batch-size 32
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from sklearn.metrics import cohen_kappa_score
from sklearn.model_selection import StratifiedKFold
from torch.utils.data import DataLoader, Dataset
from torchvision.models import efficientnet_b0
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import settings
from app.ml.preprocessing import preprocess_image


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def checkpoint_metadata(epoch: int, val_qwk: float, samples: int, input_size: int) -> dict:
    """Metadata written to efficientnet_b0_dr_meta.json (also embedded in .pt)."""
    return {
        "trained_on": "APTOS 2019 Blindness Detection",
        "architecture": "efficientnet_b0",
        "input_size": input_size,
        "best_epoch": epoch,
        "validation_qwk": round(val_qwk, 4),
        "validation_metric_definition": (
            "Quadratic Weighted Kappa (QWK) on the stratified 15% validation split"
        ),
        "confidence_definition": "Softmax probability of the predicted ICDR grade",
        "samples": int(samples),
        "training_date": datetime.date.today().isoformat(),
        "git_commit": _git_commit(),
    }


def write_meta_json(out_path: Path, meta: dict) -> None:
    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))


class AptosDataset(Dataset):
    def __init__(self, df: pd.DataFrame, size: int, augment: bool, archive=None, img_dir=None, cache_dir=None):
        self.rows = df.to_dict("records")
        self.archive = archive
        self._names = set(archive.namelist()) if archive is not None else set()
        self.img_dir = img_dir
        self.cache_dir = cache_dir
        self.size = size
        self.augment = augment

    def __len__(self):
        return len(self.rows)

    def _open_image(self, id_code: str):
        if self.archive is not None:
            for entry in (f"{id_code}.png", f"train_images/{id_code}.png"):
                if entry in self._names:
                    return self.archive.open(entry)
            raise KeyError(f"{id_code}.png not in archive")
        candidates = (
            self.img_dir / f"{id_code}.png",
            self.img_dir / "train_images" / f"{id_code}.png",
        )
        for c in candidates:
            if c.exists():
                return open(c, "rb")
        raise FileNotFoundError(f"no image for {id_code} under {self.img_dir}")

    def __getitem__(self, idx):
        row = self.rows[idx]
        id_code = row["id_code"]
        if self.cache_dir is not None:
            x = np.load(self.cache_dir / f"{id_code}.npy").astype(np.float32)
        else:
            with self._open_image(id_code) as f:
                from PIL import Image

                img = Image.open(f).convert("RGB")
            x = preprocess_image(img, size=self.size)
        if self.augment:
            x = _augment(x)
        return x, int(row["diagnosis"])


def _augment(tensor: np.ndarray, p: float = 0.5) -> np.ndarray:
    if np.random.rand() > p:
        return tensor
    # pre-normalized tensor: forgive a small shift + noise + flips
    out = tensor.copy()
    if np.random.rand() > 0.5:
        out = out[:, :, ::-1]  # horizontal flip
    if np.random.rand() > 0.5:
        out = out[:, ::-1, :]  # vertical flip
    out = out + np.random.normal(0, 0.02, size=out.shape).astype(np.float32)
    return out


def qwk(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(cohen_kappa_score(y_true, y_pred, weights="quadratic"))


def build_model(device: str) -> nn.Module:
    model = efficientnet_b0(weights="IMAGENET1K_V1")
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, 5)
    return model.to(device)


def build_cache(df: pd.DataFrame, cache_dir: Path, archive, img_dir: Path, size: int, workers: int = 8) -> pd.DataFrame:
    """Decode + preprocess every image once and store as float16 .npy tensors.

    Returns a DataFrame filtered to rows whose image was successfully cached.
    zipfile.ZipFile is not thread-safe, so each worker thread opens its own handle.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive_path = Path(archive.filename) if archive is not None else None
    names = set(archive.namelist()) if archive is not None else None
    tls = threading.local()

    def get_handle():
        if archive_path is None:
            return None
        h = getattr(tls, "zf", None)
        if h is None:
            h = tls.zf = zipfile.ZipFile(archive_path)
        return h

    def present(row) -> bool:
        id_code = row["id_code"]
        if names is not None:
            return f"{id_code}.png" in names or f"train_images/{id_code}.png" in names
        return (img_dir / f"{id_code}.png").exists() or (img_dir / "train_images" / f"{id_code}.png").exists()

    def open_image(id_code: str):
        if get_handle() is not None:
            zf_h = get_handle()
            entry = f"{id_code}.png" if f"{id_code}.png" in zf_h.namelist() else f"train_images/{id_code}.png"
            return zf_h.open(entry)
        for c in (img_dir / f"{id_code}.png", img_dir / "train_images" / f"{id_code}.png"):
            if c.exists():
                return open(c, "rb")
        raise FileNotFoundError(f"no image for {id_code} under {img_dir}")

    def process(row):
        id_code = row["id_code"]
        out = cache_dir / f"{id_code}.npy"
        if out.exists():
            return id_code, True
        try:
            with open_image(id_code) as f:
                from PIL import Image

                img = Image.open(f).convert("RGB")
            x = preprocess_image(img, size=size)
            np.save(out, x.astype(np.float16))
            return id_code, True
        except Exception as exc:  # noqa: BLE001
            print(f"cache failed for {id_code}: {exc}", file=sys.stderr)
            return id_code, False

    rows = df.to_dict("records")
    to_do = [r for r in rows if present(r)]
    ok_ids = set()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for id_code, ok in tqdm(pool.map(process, to_do), total=len(to_do), desc="building cache"):
            if ok:
                ok_ids.add(id_code)
    out_df = df[df["id_code"].isin(ok_ids)]
    print(f"cache ready: {len(out_df)}/{len(df)} images in {cache_dir}")
    return out_df


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="Folder with train.csv + either train.zip or train_images/")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--input-size", type=int, default=380)
    parser.add_argument("--val-fraction", type=float, default=0.15)
    parser.add_argument("--device", default=settings.device)
    parser.add_argument("--out", default=str(settings.classifier_weights))
    parser.add_argument("--no-cache", action="store_true", help="Skip the .npy image cache")
    parser.add_argument("--cache-workers", type=int, default=8)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not (data_dir / "train.csv").exists():
        print(f"train.csv not found in {data_dir}", file=sys.stderr)
        return 1

    settings.input_size = args.input_size
    device = args.device
    if device == "cpu":
        torch.set_num_threads(6)

    df = pd.read_csv(data_dir / "train.csv")
    print(f"Loaded {len(df)} samples")
    print(df["diagnosis"].value_counts().sort_index().to_string())

    archive_path = next(
        (p for p in (data_dir / "train.zip", data_dir / "aptos2019-blindness-detection.zip") if p.exists()),
        None,
    )
    zf = zipfile.ZipFile(archive_path) if archive_path else None
    try:
        cache_dir = None if args.no_cache else data_dir / "npy_cache"
        if cache_dir is not None:
            df = build_cache(df, cache_dir, zf, data_dir, args.input_size, workers=args.cache_workers)
            if len(df) < 100:
                print("Too few cached images — aborting", file=sys.stderr)
                return 1

        # Stratified split — preserve rare classes (grades 3-4) in validation.
        skf = StratifiedKFold(n_splits=int(1 / args.val_fraction), shuffle=True, random_state=42)
        train_idx, val_idx = next(iter(skf.split(df, df["diagnosis"])))
        train_df, val_df = df.iloc[train_idx], df.iloc[val_idx]
        print(f"TRAIN {len(train_df)} / VAL {len(val_df)}")

        train_ds = AptosDataset(train_df, args.input_size, augment=True, archive=zf, img_dir=data_dir, cache_dir=cache_dir)
        val_ds = AptosDataset(val_df, args.input_size, augment=False, archive=zf, img_dir=data_dir, cache_dir=cache_dir)
        train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=0)
        val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

        # Class-imbalance handling: inverse-frequency class weights.
        counts = df["diagnosis"].value_counts().sort_index()
        weights = torch.tensor(
            [len(df) / (5 * counts[i]) for i in range(5)], dtype=torch.float32
        ).to(device)
        print("class weights:", weights.tolist())

        model = build_model(device)
        criterion = nn.CrossEntropyLoss(weight=weights)
        optimizer = optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)

        best_qwk, best_state, best_epoch = float("-inf"), None, -1
        for epoch in range(1, args.epochs + 1):
            model.train()
            running_loss = 0.0
            for x, y in tqdm(train_loader, desc=f"Epoch {epoch}/{args.epochs} [train]"):
                x, y = x.to(device), y.to(device)
                optimizer.zero_grad()
                loss = criterion(model(x), y)
                loss.backward()
                optimizer.step()
                running_loss += loss.item() * y.size(0)

            # validation
            model.eval()
            labels, preds = [], []
            with torch.no_grad():
                for x, y in val_loader:
                    x = x.to(device)
                    probs = torch.softmax(model(x), dim=1)
                    preds.extend(torch.argmax(probs, dim=1).cpu().numpy().tolist())
                    labels.extend(y.cpu().numpy().tolist())
            val_qwk = qwk(np.array(labels), np.array(preds))
            val_acc = float(np.mean(np.array(labels) == np.array(preds)))
            print(
                f"epoch {epoch}: loss={running_loss / len(train_df):.4f} "
                f"val_qwk={val_qwk:.4f} val_acc={val_acc:.4f}"
            )

            if val_qwk > best_qwk:
                best_qwk = val_qwk
                best_epoch = epoch
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                meta = checkpoint_metadata(epoch, val_qwk, len(train_df), args.input_size)
                out_path = Path(args.out)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                torch.save(
                    {
                        "model_state": best_state,
                        "out_features": 5,
                        "meta": meta,
                    },
                    out_path,
                )
                write_meta_json(out_path, meta)
                print(f"   [checkpoint saved -> {out_path}]", flush=True)

        if best_state is None:
            print("No checkpoint — training failed", file=sys.stderr)
            return 1

        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        meta = checkpoint_metadata(best_epoch, best_qwk, len(train_df), args.input_size)
        torch.save(
            {
                "model_state": best_state,
                "out_features": 5,
                "meta": meta,
            },
            out,
        )
        write_meta_json(out, meta)
        print(f"Saved best checkpoint (epoch {best_epoch}, QWK {best_qwk:.4f}) -> {out}")
        return 0
    finally:
        if zf is not None:
            zf.close()


if __name__ == "__main__":
    raise SystemExit(main())