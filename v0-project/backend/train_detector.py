#!/usr/bin/env python
"""Option A for Engine A — fine-tune YOLOv8 on IDRiD lesion segmentation masks.

APTOS provides no lesion bounding boxes, so to train a detector in-house we
convert IDRiD per-lesion segmentation masks into YOLO-format bounding boxes
and train YOLOv8 on those. The result replaces backend/models/yolov8_lesion.pt
and the app labels it as "fine-tuned on IDRiD".

Expected IDRiD layout (IEEE DataPort "A. Segmentation" package):
    idrid/
      1. Original Images/a. Training Set/IDRiD_*.jpg
      2. All Segmentation Groundtruths/a. Training Set/
         1. Microaneurysms/   2. Haemorrhages/
         3. Hard Exudates/    4. Soft Exudates/   (IDRiD_*_*.tif)

Usage:
    python train_detector.py --data-dir "path/to/A. Segmentation" --epochs 50
    # then copy/rename best.pt -> backend/models/yolov8_lesion.pt
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def prepare_idrid_labels(data_dir: Path) -> pd.DataFrame:
    """Build a DataFrame of {image, cls, x, y, w, h} YOLO labels from masks.

    Each lesion class mask is converted to connected components; each
    component above a size threshold becomes one bounding box.
    """
    import cv2
    from PIL import Image

    class_ids = {"microaneurysm": 0, "hemorrhage": 1, "hard_exudate": 2, "soft_exudate": 3}
    mask_folders = {
        "1. Microaneurysms": "microaneurysm",
        "2. Haemorrhages": "hemorrhage",
        "3. Hard Exudates": "hard_exudate",
        "4. Soft Exudates": "soft_exudate",
    }

    image_dir = data_dir / "1. Original Images" / "a. Training Set"
    mask_root = data_dir / "2. All Segmentation Groundtruths" / "a. Training Set"
    if not image_dir.exists():
        raise SystemExit(f"IDRiD images not found at {image_dir}")

    rows = []
    for img_file in image_dir.rglob("*"):
        if img_file.suffix.lower() not in (".jpg", ".png"):
            continue
        image_id = img_file.stem
        w, h = Image.open(img_file).size
        for folder, cls_name in mask_folders.items():
            mask_candidates = list((mask_root / folder).rglob(f"{image_id}_*.tif"))
            if not mask_candidates:
                continue
            mask = cv2.imread(str(mask_candidates[0]), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                continue
            mask = (mask > 0).astype(np.uint8)
            num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
            for i in range(1, num):
                x, y, bw, bh, area = stats[i]
                if area < 20:
                    continue
                cx, cy = (x + bw / 2) / w, (y + bh / 2) / h
                nw, nh = bw / w, bh / h
                rows.append(
                    {
                        "image": f"{image_id}{img_file.suffix}",
                        "cls": class_ids[cls_name],
                        "x": round(cx, 5),
                        "y": round(cy, 5),
                        "w": round(nw, 5),
                        "h": round(nh, 5),
                    }
                )
    df = pd.DataFrame(rows)
    print(f"Built {len(df)} lesion boxes across {df['image'].nunique()} images")
    df.to_csv(data_dir / "idrid_yolo_labels.csv", index=False)
    return df


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="Path to the IDRiD dataset folder")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--out", default="models/yolov8_lesion.pt")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Data dir not found: {data_dir}", file=sys.stderr)
        return 1

    df = prepare_idrid_labels(data_dir)
    if df.empty:
        print("No boxes produced — check IDRiD folder layout.", file=sys.stderr)
        return 1

    train_images = int(len(set(df["image"])) * 5 / 6)
    val_images = int(len(set(df["image"])) * 1 / 6)

    # Write YOLO-format .txt labels next to a YOLO dataset YAML, then train.
    import yaml
    from ultralytics import YOLO

    dataset = data_dir / "dr_dataset"
    dataset.mkdir(exist_ok=True)
    images_dir = dataset / "images"
    labels_dir = dataset / "labels"
    images_dir.mkdir(exist_ok=True)
    labels_dir.mkdir(exist_ok=True)

    df["image_path"] = df["image"]
    # Copy unique images referenced
    seen = set()
    for img_name in df["image"].unique():
        if img_name in seen:
            continue
        seen.add(img_name)
        for cand in data_dir.glob("**/" + img_name):
            if "Original Images" in str(cand) or "Source Images" in str(cand):
                (images_dir / img_name).write_bytes(cand.read_bytes())
                break
    for img_name, grp in df.groupby("image"):
        lbl_dest = labels_dir / (Path(img_name).stem + ".txt")
        with lbl_dest.open("w") as f:
            for _, r in grp.iterrows():
                f.write(f"{int(r['cls'])} {r['x']} {r['y']} {r['w']} {r['h']}\n")

    yaml_path = dataset / "data.yaml"
    train_dir = images_dir / "train"
    val_dir = images_dir / "val"
    lbl_train = labels_dir / "train"
    lbl_val = labels_dir / "val"
    for d in (train_dir, val_dir, lbl_train, lbl_val):
        d.mkdir(exist_ok=True)

    # Deterministic holdout split for the val: key (Ultralytics requires it).
    sorted_imgs = sorted(images_dir.glob("*.jpg"))
    for i, img_path in enumerate(sorted_imgs):
        is_val = i % 6 == 0
        dest_img = (val_dir if is_val else train_dir) / img_path.name
        dest_lbl = (lbl_val if is_val else lbl_train) / (img_path.stem + ".txt")
        lbl_src = labels_dir / (img_path.stem + ".txt")
        if not dest_img.exists():
            img_path.rename(dest_img)
        if lbl_src.exists() and not dest_lbl.exists():
            lbl_src.rename(dest_lbl)

    yaml_path.write_text(
        yaml.safe_dump(
            {
                "path": str(dataset),
                "train": "images/train",
                "val": "images/val",
                "names": {0: "microaneurysm", 1: "hemorrhage", 2: "hard_exudate", 3: "soft_exudate"},
            },
            sort_keys=False,
        )
    )

    model = YOLO("yolov8n.pt")
    model.train(
        data=str(yaml_path),
        epochs=args.epochs,
        imgsz=640,
        batch=args.batch_size,
        device="cpu",
    )
    best = Path(model.trainer.best) if model.trainer and model.trainer.best else None
    if best is not None and best.exists():
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        best.rename(out) if not out.exists() else None
        import datetime as _dt
        latest = out.with_suffix(".pt.meta.json") if out.suffix == ".pt" else out.with_suffix(out.suffix + ".meta.json")
        mu = model.trainer.metrics or {}
        map50 = mu.get("metrics/mAP50(B)", 0.0) or 0.0
        latest.write_text(
            json.dumps(
                {
                    "model": "YOLOv8n",
                    "dataset": "IDRiD A. Segmentation (lesion masks -> YOLO boxes)",
                    "train_images": train_images,
                    "val_images": val_images,
                    "lesion_boxes": len(df),
                    "epochs": args.epochs,
                    "val_map50": round(float(map50), 4),
                    "training_date": _dt.date.today().isoformat(),
                },
                indent=2,
            )
        )
        print(f"Saved detector -> {out}")
        print(f"Saved detector meta -> {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())