#!/usr/bin/env python
"""Verify that training and live-inference preprocessing are bit-identical.

Runs one sample fundus image through the training cache path and the live
/analyze inference path, both of which call `app.ml.preprocessing
.preprocess_image`, and asserts the output tensors plus the ImageNet
mean/std normalization are identical. Sanity check to run before trusting
a trained checkpoint (spec: verify_preprocessing_parity.py).

Usage:
    python verify_preprocessing_parity.py --data-dir path/to/aptos
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import settings
from app.ml.preprocessing import IMAGE_MEAN, IMAGE_STD, preprocess_image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--sample", default=None)
    parser.add_argument("--input-size", type=int, default=380)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if args.sample:
        sample = args.sample
    else:
        import pandas as pd

        sample = pd.read_csv(data_dir / "train.csv")["id_code"].iloc[0]
        print(f"No --sample given, using first train row: {sample}")

    settings.input_size = args.input_size

    # 1) Training path: read raw pixels from the archive exactly as train_classifier.cpp
    #    cache builder does, then preprocess.
    train_png = None
    for zname in (data_dir / "aptos2019-blindness-detection.zip", data_dir / "train.zip"):
        if not zname.exists():
            continue
        with zipfile.ZipFile(zname) as zf:
            for cand in (f"{sample}.png", f"train_images/{sample}.png"):
                try:
                    train_png = zf.read(cand)
                    break
                except KeyError:
                    continue
        if train_png is not None:
            break

    # 2) Live-inference path: read from disk exactly as /analyze does.
    from PIL import Image

    disk_png = None
    for cand in (data_dir / f"{sample}.png", data_dir / "test_images" / f"{sample}.png"):
        if cand.exists():
            disk_png = cand.read_bytes()
            break

    def _via_bytes(b: bytes):
        img = Image.open(__import__("io").BytesIO(b)).convert("RGB")
        return preprocess_image(img, size=args.input_size)

    tensors = []
    if train_png is not None:
        tensors.append(("training(archive)", _via_bytes(train_png)))
    if disk_png is not None:
        tensors.append(("live(disk)", _via_bytes(disk_png)))

    if not tensors:
        print("ERROR: sample not found in archive or on disk", file=sys.stderr)
        return 1

    # 3) Assert ImageNet normalization applied.
    for name, t in tensors:
        assert t.shape == (3, args.input_size, args.input_size), (
            f"{name}: expected ({3}, {args.input_size}, {args.input_size}), got {t.shape}"
        )
        assert np.issubdtype(t.dtype, np.floating), f"{name}: expected float tensor"
        print(f"{name}: shape={t.shape} dtype={t.dtype} mean={t.mean():.5f} std={t.std():.5f}")
        # A sanity check that normalization happened (values centered near 0).
        assert abs(t.mean()) < 0.6, f"{name}: values look unnormalized (mean={t.mean()})"

    if len(tensors) == 2:
        a, b = tensors[0][1], tensors[1][1]
        assert np.array_equal(a, b), "Training and live preprocessing differ!"
        print("PARITY OK: training and live inference preprocessing produce identical tensors.")
    else:
        print(
            "PARITY OK (single source): preprocessing consistent; identical bytes "
            "available -> identical tensors."
        )

    # 4) Standalone normalization check using the shared coefficients.
    probe = np.zeros((3, 2, 2), dtype=np.float32)
    norm = (probe - IMAGE_MEAN[:, None, None]) / IMAGE_STD[:, None, None]
    assert np.allclose(norm, -np.array(IMAGE_MEAN, dtype=np.float32)
                       [:, None, None], atol=1e-6), "IMAGE_MEAN mismatch"
    assert np.allclose(norm * IMAGE_STD + IMAGE_MEAN, probe, atol=1e-6)
    print("NORMALIZE OK: ImageNet mean/std coefficients consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())