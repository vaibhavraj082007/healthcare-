"""
RetinaShield — IDRiD Lesion Segmentation Dataset Importer
==========================================================
Converts IDRiD pixel-level segmentation masks into YOLO bounding-box label files
and a lesion manifest JSON.

Expected IDRiD directory layout
--------------------------------
<root>/
  A. Segmentation/
    1. Original Images/
      a. Training Set/   → IDRiD_NN.jpg
    2. All Segmentation Groundtruths/
      a. Training Set/
        1. Microaneurysms/    → IDRiD_NN_MA.tif
        2. Haemorrhages/      → IDRiD_NN_HE.tif
        3. Hard Exudates/     → IDRiD_NN_EX.tif
        4. Soft Exudates/     → IDRiD_NN_SE.tif

Output layout (YOLO format)
---------------------------
<output>/
  images/{train,val,test}/
  labels/{train,val,test}/
  dataset.yaml
  lesion_manifest.json

Class index mapping
-------------------
  0 → microaneurysm
  1 → hemorrhage
  2 → hard_exudate
  3 → soft_exudate  (cotton_wool_spot equivalent in IDRiD)

License
-------
IDRiD is distributed under CC BY 4.0.
Full citation: Porwal et al., "IDRiD: Diabetic Retinopathy – Segmentation and Grading Challenge", 2020.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Require OpenCV — tests skip this module if unavailable
try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False
    logger.warning("OpenCV not available — IDRiDLesionImporter will raise on process().")

# ---------------------------------------------------------------------------
# Lesion class registry
# ---------------------------------------------------------------------------

LESION_CLASSES: List[str] = [
    "microaneurysm",   # 0 — IDRiD: 1. Microaneurysms
    "hemorrhage",      # 1 — IDRiD: 2. Haemorrhages
    "hard_exudate",    # 2 — IDRiD: 3. Hard Exudates
    "soft_exudate",    # 3 — IDRiD: 4. Soft Exudates
]

_LESION_SUBDIR_MAP: Dict[str, str] = {
    "microaneurysm": "1. Microaneurysms",
    "hemorrhage":    "2. Haemorrhages",
    "hard_exudate":  "3. Hard Exudates",
    "soft_exudate":  "4. Soft Exudates",
}
_LESION_SUFFIX_MAP: Dict[str, str] = {
    "microaneurysm": "_MA",
    "hemorrhage":    "_HE",
    "hard_exudate":  "_EX",
    "soft_exudate":  "_SE",
}
_MIN_LESION_AREA_PX: int = 9   # ~3×3 pixel noise filter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_extent(bbox: Dict[str, float]) -> Dict[str, float]:
    w = max(0.0, bbox["x_max"] - bbox["x_min"])
    h = max(0.0, bbox["y_max"] - bbox["y_min"])
    area = w * h
    diam = 2.0 * math.sqrt(area / math.pi) if area > 0 else 0.0
    return {"area_pixels": area, "equivalent_diameter": diam, "width": w, "height": h}


def _mask_to_boxes(
    mask: np.ndarray,
    *,
    min_area: int = _MIN_LESION_AREA_PX,
) -> List[Dict[str, float]]:
    """Extract bounding boxes from a binary mask using connected-components analysis."""
    if not _CV2_AVAILABLE:
        raise RuntimeError("OpenCV required for mask_to_boxes")

    _, binary = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
    num_labels, labels_cc, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    boxes = []
    for label_idx in range(1, num_labels):  # skip background (0)
        area = int(stats[label_idx, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        x = int(stats[label_idx, cv2.CC_STAT_LEFT])
        y = int(stats[label_idx, cv2.CC_STAT_TOP])
        w = int(stats[label_idx, cv2.CC_STAT_WIDTH])
        h = int(stats[label_idx, cv2.CC_STAT_HEIGHT])
        boxes.append({
            "x_min": float(x), "y_min": float(y),
            "x_max": float(x + w), "y_max": float(y + h),
        })
    return boxes


def _yolo_line(class_idx: int, bbox: Dict[str, float], img_w: int, img_h: int) -> str:
    """Convert absolute bbox to YOLO normalised format."""
    cx = (bbox["x_min"] + bbox["x_max"]) / 2.0 / img_w
    cy = (bbox["y_min"] + bbox["y_max"]) / 2.0 / img_h
    w = (bbox["x_max"] - bbox["x_min"]) / img_w
    h = (bbox["y_max"] - bbox["y_min"]) / img_h
    return f"{class_idx} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def _train_val_test_split(
    items: List[Any], *, train_frac: float = 0.70, val_frac: float = 0.15, seed: int = 42
) -> Tuple[List[Any], List[Any], List[Any]]:
    rng = random.Random(seed)
    items = list(items)
    rng.shuffle(items)
    n = len(items)
    n_train = int(n * train_frac)
    n_val = int(n * val_frac)
    return items[:n_train], items[n_train:n_train + n_val], items[n_train + n_val:]


# ---------------------------------------------------------------------------
# Main importer
# ---------------------------------------------------------------------------

class IDRiDLesionImporter:
    """
    Convert IDRiD segmentation masks to YOLO bounding-box dataset.

    Parameters
    ----------
    root_dir   : path to the IDRiD dataset root
    output_dir : path to write the YOLO dataset
    seed       : RNG seed for reproducible train/val/test split
    """

    def __init__(
        self,
        *,
        root_dir: str | os.PathLike,
        output_dir: str | os.PathLike,
        seed: int = 42,
    ):
        self.root_dir = Path(root_dir)
        self.output_dir = Path(output_dir)
        self.seed = seed

    # ------------------------------------------------------------------
    def process(
        self,
        *,
        tile_size: int = 640,
        overlap: float = 0.20,
    ) -> Dict[str, Any]:
        """
        Run the full import pipeline.

        Returns
        -------
        dict with total_images, lesion_counts, splits, output_dir
        """
        if not _CV2_AVAILABLE:
            raise RuntimeError("OpenCV (cv2) is required for IDRiD import.")

        seg_root = self.root_dir / "A. Segmentation"
        img_dir = seg_root / "1. Original Images" / "a. Training Set"
        gt_root = seg_root / "2. All Segmentation Groundtruths" / "a. Training Set"

        # Discover all training images
        image_paths = sorted(img_dir.glob("*.jpg")) + sorted(img_dir.glob("*.png"))
        image_ids = [p.stem for p in image_paths]

        if not image_ids:
            logger.warning("No images found under %s", img_dir)

        # Process each image
        records: List[Dict[str, Any]] = []
        lesion_counts: Dict[str, int] = {lc: 0 for lc in LESION_CLASSES}

        for img_path in image_paths:
            image_id = img_path.stem
            img = cv2.imread(str(img_path))
            if img is None:
                logger.warning("Could not read image %s — skipping", img_path)
                img_h, img_w = 800, 1000  # fallback dims
            else:
                img_h, img_w = img.shape[:2]

            detections: List[Dict[str, Any]] = []
            yolo_lines: List[str] = []

            for class_idx, lesion_type in enumerate(LESION_CLASSES):
                subdir = _LESION_SUBDIR_MAP[lesion_type]
                suffix = _LESION_SUFFIX_MAP[lesion_type]
                # Try both .tif and .png mask files
                mask_path: Optional[Path] = None
                for ext in [".tif", ".png", ".bmp"]:
                    candidate = gt_root / subdir / f"{image_id}{suffix}{ext}"
                    if candidate.exists():
                        mask_path = candidate
                        break

                if mask_path is None:
                    continue

                mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
                if mask is None:
                    continue

                boxes = _mask_to_boxes(mask)
                for bbox in boxes:
                    extent = _compute_extent(bbox)
                    detections.append({
                        "lesion_type": lesion_type,
                        "bbox": bbox,
                        "approximate_extent": extent,
                        "source": "IDRiD_gt_mask",
                        "confidence": 1.0,  # ground-truth
                    })
                    yolo_lines.append(_yolo_line(class_idx, bbox, img_w, img_h))
                    lesion_counts[lesion_type] += 1

            records.append({
                "image_id": image_id,
                "image_path": str(img_path),
                "image_size": [img_w, img_h],
                "detections": detections,
                "yolo_label_lines": yolo_lines,
            })

        # Train / val / test split
        train_ids, val_ids, test_ids = _train_val_test_split(
            [r["image_id"] for r in records], seed=self.seed
        )
        split_map: Dict[str, str] = {}
        for sid in train_ids:
            split_map[sid] = "train"
        for sid in val_ids:
            split_map[sid] = "val"
        for sid in test_ids:
            split_map[sid] = "test"

        # Write output files
        for split in ["train", "val", "test"]:
            (self.output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
            (self.output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

        for rec in records:
            image_id = rec["image_id"]
            split = split_map.get(image_id, "train")

            # Copy image
            src_img = Path(rec["image_path"])
            if src_img.exists():
                dst_img = self.output_dir / "images" / split / src_img.name
                shutil.copy2(str(src_img), str(dst_img))

            # Write YOLO label file
            label_path = self.output_dir / "labels" / split / f"{image_id}.txt"
            label_path.write_text("\n".join(rec["yolo_label_lines"]))

        # Write dataset.yaml
        yaml_content = (
            f"path: {self.output_dir}\n"
            f"train: images/train\n"
            f"val: images/val\n"
            f"test: images/test\n"
            f"nc: {len(LESION_CLASSES)}\n"
            f"names: {LESION_CLASSES}\n"
        )
        (self.output_dir / "dataset.yaml").write_text(yaml_content)

        # Write lesion manifest JSON
        manifest = {
            "dataset_name": "IDRiD_Lesion_Segmentation",
            "license": "CC BY 4.0",
            "citation": "Porwal et al., IDRiD: Diabetic Retinopathy Segmentation and Grading Challenge, 2020",
            "lesion_classes": LESION_CLASSES,
            "total_images": len(records),
            "lesion_counts": lesion_counts,
            "splits": {"train": train_ids, "val": val_ids, "test": test_ids},
            "records": [
                {
                    "image_id": r["image_id"],
                    "split": split_map.get(r["image_id"], "train"),
                    "detections": r["detections"],
                }
                for r in records
            ],
        }
        (self.output_dir / "lesion_manifest.json").write_text(
            json.dumps(manifest, indent=2)
        )

        return {
            "total_images": len(records),
            "lesion_counts": lesion_counts,
            "splits": {"train": len(train_ids), "val": len(val_ids), "test": len(test_ids)},
            "output_dir": str(self.output_dir),
        }
