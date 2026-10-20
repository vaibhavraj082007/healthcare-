#!/usr/bin/env python
"""Held-out test scoring on APTOS test split.

Loads the trained efficientnet_b0_dr.pt checkpoint, runs inference over
test.zip, and writes a submission.csv in the exact sample_submission.csv
format (columns: id_code, diagnosis).

Usage:
    python predict_test.py --data-dir path/to/aptos --out submission.csv
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import settings
from app.ml.preprocessing import preprocess_image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--weights", default=str(settings.classifier_weights))
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--input-size", type=int, default=380)
    parser.add_argument("--out", default="submission.csv")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    weights_path = Path(args.weights)
    if not (data_dir / "test.csv").exists():
        print("Missing test.csv", file=sys.stderr)
        return 1
    has_zip = (data_dir / "test.zip").exists() or (
        data_dir / "aptos2019-blindness-detection.zip"
    ).exists()
    has_dir = (data_dir / "test_images").is_dir()
    if not (has_zip or has_dir):
        print(f"Missing test.zip, aptos2019...zip or test_images/ in {data_dir}", file=sys.stderr)
        return 1
    if not weights_path.exists():
        print(f"Checkpoint not found: {weights_path}", file=sys.stderr)
        return 1

    settings.input_size = args.input_size
    device = settings.device
    state = torch.load(weights_path, map_location=device)

    from torchvision.models import efficientnet_b0

    model = efficientnet_b0(weights=None)
    model.classifier[1] = nn.Linear(model.classifier[1].in_features, 5)
    model.load_state_dict(state["model_state"])
    model.eval().to(device)

    test_df = pd.read_csv(data_dir / "test.csv")
    print(f"Predicting {len(test_df)} test images...")

    predictions: list[int] = []
    test_zip = data_dir / "test.zip"
    if not test_zip.exists():
        test_zip = data_dir / "aptos2019-blindness-detection.zip"
    aptos_layout = test_zip.name.startswith("aptos2019")
    with zipfile.ZipFile(test_zip) if test_zip.exists() else nullcontext(None) as zf:

        def open_image(id_code: str):
            if zf is not None:
                return zf.open(
                    f"test_images/{id_code}.png" if aptos_layout else f"{id_code}.png"
                )
            for c in (data_dir / f"{id_code}.png", data_dir / "test_images" / f"{id_code}.png"):
                if c.exists():
                    return open(c, "rb")
            raise FileNotFoundError(f"no test image for {id_code}")

        rows = test_df["id_code"].tolist()
        for i in tqdm(range(0, len(rows), args.batch_size)):
            batch = rows[i : i + args.batch_size]
            tensors = []
            for id_code in batch:
                with open_image(id_code) as f:
                    from PIL import Image

                    img = Image.open(f).convert("RGB")
                tensors.append(preprocess_image(img, size=args.input_size))
            xb = torch.from_numpy(np.stack(tensors)).to(device)
            with torch.no_grad():
                probs = torch.softmax(model(xb), dim=1)
            predictions.extend(torch.argmax(probs, dim=1).cpu().numpy().tolist())

    sample = pd.read_csv(data_dir / "sample_submission.csv")
    sample["diagnosis"] = predictions
    sample.to_csv(args.out, index=False)
    print(f"Wrote {args.out} ({len(sample)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())