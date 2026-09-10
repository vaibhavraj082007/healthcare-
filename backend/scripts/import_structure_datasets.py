"""
RetinaShield — Structure Benchmark Dataset Adapters
====================================================
Provides `StructureDatasetAdapter` with static methods for importing structure
annotation datasets (DRIVE, REFUGE, IDRiD structural) into a common record format.

All adapters return a list of record dicts:
  {
    dataset_name      : str,
    image_id          : str,
    image_path        : str,
    vessel_mask_path  : str | None,       # DRIVE / STARE
    fov_mask_path     : str | None,       # DRIVE FOV mask
    optic_disc_mask_path : str | None,    # REFUGE / IDRiD
    fovea_center      : [x, y] | None,   # REFUGE / IDRiD
    license           : str,
    split             : str,              # "train" | "val" | "test" | "unknown"
  }

No deep-learning or OpenCV dependency at module level — importers use only
the standard library (os, csv, pathlib, json) plus optional cv2 for image ops.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class StructureDatasetAdapter:
    """
    Static-method adapters for ophthalmological structure benchmark datasets.
    """

    # ------------------------------------------------------------------
    @staticmethod
    def import_drive(
        root: str | os.PathLike,
        *,
        split: str = "train",
    ) -> List[Dict[str, Any]]:
        """
        Import the DRIVE (Digital Retinal Images for Vessel Extraction) dataset.

        Expected layout
        ---------------
        <root>/
          training/
            images/         → *_training.tif
            1st_manual/     → *_manual1.gif   (expert vessel mask)
            mask/           → *_training_mask.gif  (FOV mask)
          test/
            images/         → *_test.tif
            1st_manual/     → *_1st_manual.gif
            mask/           → *_test_mask.gif

        License: Research use only — Niemeijer et al., 2004.
        Reference: https://drive.grand-challenge.org/
        """
        root = Path(root)
        split_dir = root / split if (root / split).exists() else root / "training"
        img_dir = split_dir / "images"
        manual_dir = split_dir / "1st_manual"
        mask_dir = split_dir / "mask"

        records: List[Dict[str, Any]] = []
        if not img_dir.exists():
            logger.warning("DRIVE image dir not found: %s", img_dir)
            return records

        for img_path in sorted(img_dir.iterdir()):
            if img_path.suffix.lower() not in {".tif", ".tiff", ".png", ".jpg"}:
                continue
            stem = img_path.stem  # e.g. "21_training"

            # Vessel mask: stem → e.g. "21_manual1.gif"
            image_num = stem.split("_")[0]
            vessel_mask: Optional[str] = None
            for candidate in manual_dir.iterdir() if manual_dir.exists() else []:
                if candidate.name.startswith(image_num):
                    vessel_mask = str(candidate)
                    break

            # FOV mask
            fov_mask: Optional[str] = None
            for candidate in mask_dir.iterdir() if mask_dir.exists() else []:
                if candidate.name.startswith(image_num):
                    fov_mask = str(candidate)
                    break

            records.append({
                "dataset_name": "DRIVE",
                "image_id": stem,
                "image_path": str(img_path),
                "vessel_mask_path": vessel_mask,
                "fov_mask_path": fov_mask,
                "optic_disc_mask_path": None,
                "fovea_center": None,
                "license": "Research use only — Niemeijer et al., 2004 (DRIVE dataset)",
                "split": "train" if "training" in str(split_dir) else "test",
            })

        return records

    # ------------------------------------------------------------------
    @staticmethod
    def import_refuge(
        root: str | os.PathLike,
    ) -> List[Dict[str, Any]]:
        """
        Import the REFUGE (Retinal Fundus Glaucoma Challenge) dataset.

        Expected layout
        ---------------
        <root>/
          images/              → *.jpg / *.png
          Disc_Cup_Masks/      → *.png  (optic disc + cup mask)
          Fovea_Locations.csv  → ImgName, Fovea_X, Fovea_Y

        License: CC BY-NC-SA 4.0 — Orlando et al., MICCAI 2018.
        """
        root = Path(root)
        img_dir = root / "images"
        mask_dir = root / "Disc_Cup_Masks"
        fovea_csv = root / "Fovea_Locations.csv"

        fovea_map: Dict[str, List[float]] = {}
        if fovea_csv.exists():
            with open(fovea_csv, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    img_name = list(row.values())[0].strip()
                    try:
                        vals = list(row.values())
                        fx, fy = float(vals[1]), float(vals[2])
                        stem = Path(img_name).stem
                        fovea_map[stem] = [fx, fy]
                    except (IndexError, ValueError):
                        pass

        records: List[Dict[str, Any]] = []
        if not img_dir.exists():
            logger.warning("REFUGE image dir not found: %s", img_dir)
            return records

        for img_path in sorted(img_dir.iterdir()):
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".tif"}:
                continue
            stem = img_path.stem

            od_mask: Optional[str] = None
            od_candidate = mask_dir / f"{stem}.png"
            if od_candidate.exists():
                od_mask = str(od_candidate)

            records.append({
                "dataset_name": "REFUGE",
                "image_id": stem,
                "image_path": str(img_path),
                "vessel_mask_path": None,
                "fov_mask_path": None,
                "optic_disc_mask_path": od_mask,
                "fovea_center": fovea_map.get(stem),
                "license": "CC BY-NC-SA 4.0 — Orlando et al., MICCAI 2018 (REFUGE dataset)",
                "split": "unknown",
            })

        return records

    # ------------------------------------------------------------------
    @staticmethod
    def import_idrid(
        root: str | os.PathLike,
    ) -> List[Dict[str, Any]]:
        """
        Import IDRiD structural annotations (optic disc + fovea centre).

        Expected layout
        ---------------
        <root>/
          1. Segmentation/
            a. Original Images/   → IDRiD_NN.jpg
            b. Optic Disc/        → IDRiD_NN_OD.tif
          2. Fovea Center/
            IDRiD_Fovea_Center.csv   → IDRiD_NN.jpg, x, y  (no header)

        License: CC BY 4.0 — Porwal et al., 2020.
        """
        root = Path(root)
        seg_root = root / "1. Segmentation"
        img_dir = seg_root / "a. Original Images"
        od_dir = seg_root / "b. Optic Disc"
        fovea_csv = root / "2. Fovea Center" / "IDRiD_Fovea_Center.csv"

        fovea_map: Dict[str, List[float]] = {}
        if fovea_csv.exists():
            with open(fovea_csv, newline="", encoding="utf-8") as f:
                for row in csv.reader(f):
                    if len(row) < 3:
                        continue
                    stem = Path(row[0].strip()).stem
                    try:
                        fx, fy = float(row[1]), float(row[2])
                        fovea_map[stem] = [fx, fy]
                    except ValueError:
                        pass

        records: List[Dict[str, Any]] = []
        if not img_dir.exists():
            logger.warning("IDRiD image dir not found: %s", img_dir)
            return records

        for img_path in sorted(img_dir.iterdir()):
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".tif"}:
                continue
            stem = img_path.stem  # e.g. "IDRiD_01"

            od_mask: Optional[str] = None
            od_candidate = od_dir / f"{stem}_OD.tif"
            if od_candidate.exists():
                od_mask = str(od_candidate)

            records.append({
                "dataset_name": "IDRiD",
                "image_id": stem,
                "image_path": str(img_path),
                "vessel_mask_path": None,
                "fov_mask_path": None,
                "optic_disc_mask_path": od_mask,
                "fovea_center": fovea_map.get(stem),
                "license": "CC BY 4.0 — Porwal et al., IDRiD, 2020",
                "split": "unknown",
            })

        return records
