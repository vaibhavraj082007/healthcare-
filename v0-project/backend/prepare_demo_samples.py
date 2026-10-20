#!/usr/bin/env python
"""Curate 2 fundus images per ICDR grade (0-4) into backend/demo_samples/.

Reads train.csv labels + the APTOS archive, extracts the PNGs, runs the same
quality gate used by /api/uploads so every demo sample is pre-verified to run
cleanly through the pipeline, and writes manifest.json.

Usage:
    python prepare_demo_samples.py --data-dir path/to/aptos
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd
from PIL import Image, ImageFilter, ImageEnhance

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.ml.quality_gate import assess_quality

PER_GRADE = 2


def _add_poor_samples(
    archive: Path, df: pd.DataFrame, out_dir: Path, manifest: list
) -> None:
    """Create two deliberately blurry/dark samples to exercise the retake flow."""
    pool_by_grade = {g: df[df["diagnosis"] == g]["id_code"].tolist() for g in (0, 2)}
    with zipfile.ZipFile(archive) as zf:
        for tag, grade, radius, brightness in (("poor_01", 0, 7, 0.5), ("poor_02", 2, 7, 0.5)):
            id_code = pool_by_grade[grade][0]
            try:
                entry = f"train_images/{id_code}.png"
                raw = zf.read(entry)
            except KeyError:
                entry = f"{id_code}.png"
                raw = zf.read(entry)
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            img = img.filter(ImageFilter.GaussianBlur(radius=radius))
            img = ImageEnhance.Brightness(img).enhance(brightness)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            raw = buf.getvalue()
            quality = assess_quality(raw)
            dest = f"{tag}.png"
            (out_dir / dest).write_bytes(raw)
            manifest.append(
                {
                    "file": dest,
                    "id_code": id_code,
                    "diagnosis": None,
                    "quality_status": quality["status"],
                    "quality_score": round(quality["blur_score"], 4),
                    "note": "deliberately blurred/dark capture for testing the retake flow",
                }
            )
            print(f"{dest}  quality={quality['status']} score={quality['blur_score']:.2f}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument(
        "--out", default=str(Path(__file__).resolve().parent / "demo_samples")
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    archive = data_dir / "aptos2019-blindness-detection.zip"
    if not archive.exists():
        archive = data_dir / "train.zip"
    if not archive.exists():
        print(f"no APTOS archive found in {data_dir}", file=sys.stderr)
        return 1

    train = pd.read_csv(data_dir / "train.csv")
    manifest = []
    with zipfile.ZipFile(archive) as zf:
        for grade in range(5):
            pool = train[train["diagnosis"] == grade]["id_code"].tolist()
            picked = 0
            for id_code in pool:
                if picked >= PER_GRADE:
                    break
                try:
                    raw = zf.read(f"train_images/{id_code}.png")
                except KeyError:
                    raw = zf.read(f"{id_code}.png")
                quality = assess_quality(raw)
                if quality["status"] != "acceptable":
                    continue  # keep the demo set pre-verified to pass the gate
                dest_name = f"grade{grade}_{id_code}.png"
                (out_dir / dest_name).write_bytes(raw)
                manifest.append(
                    {
                        "file": dest_name,
                        "id_code": id_code,
                        "diagnosis": grade,
                        "quality_status": quality["status"],
                        "quality_score": round(quality["blur_score"], 4),
                    }
                )
                picked += 1
                print(
                    f"{dest_name}  grade={grade}  quality={quality['status']} "
                    f"score={quality['blur_score']:.2f}"
                )

        _add_poor_samples(archive, train, out_dir, manifest)

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote {len(manifest)} demo samples -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())