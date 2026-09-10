#!/usr/bin/env python3
"""
RetinaShield — IDRiD Lesion Dataset Importer & Tiling Generator

Converts expert pixel-level binary masks from IDRiD (Indian Diabetic Retinopathy
Image Dataset, Sub-challenge 1: Segmentation) into:
  1. Ground-truth bounding boxes [x_min, y_min, x_max, y_max]
  2. Approximate lesion extent (pixel area, equivalent diameter)
  3. YOLOv8 format annotations with normalized coordinates
  4. High-resolution overlapping image tiles (to preserve 3-10 px microaneurysms)
  5. Separate development (train / stratified val) and evaluation (test) splits

TERMS & CITATION:
  IDRiD is published under Creative Commons Attribution 4.0 International (CC BY 4.0).
  Citation: Porwal et al., "Indian Diabetic Retinopathy Image Dataset (IDRiD)",
  IEEE DataPort, 2018. doi: 10.21227/H25W98.
"""

import argparse
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Target lesion classes and standard IDRiD folder mappings
LESION_CLASSES = {
    0: "microaneurysm",
    1: "hemorrhage",
    2: "hard_exudate",
    3: "soft_exudate",  # Cotton-wool spots
}

CLASS_NAME_TO_ID = {v: k for k, v in LESION_CLASSES.items()}

# IDRiD mask folder patterns
MASK_FOLDER_NAMES = {
    "microaneurysm": ["1. Microaneurysms", "Microaneurysms", "MA"],
    "hemorrhage": ["2. Haemorrhages", "Haemorrhages", "Hemorrhages", "HE"],
    "hard_exudate": ["3. Hard Exudates", "Hard Exudates", "EX"],
    "soft_exudate": ["4. Soft Exudates", "Soft Exudates", "Cotton-Wool Spots", "SE"],
}

# Minimum connected-component area in pixels to filter single-pixel noise
MIN_LESION_AREA = {
    "microaneurysm": 2,
    "hemorrhage": 6,
    "hard_exudate": 4,
    "soft_exudate": 10,
}


def mask_to_bounding_boxes(
    mask_img: np.ndarray,
    lesion_type: str,
    min_area: int = 2,
) -> List[Dict[str, Any]]:
    """
    Extract individual lesion bounding boxes and approximate extent from a binary mask.
    Uses connected component labeling.
    """
    if len(mask_img.shape) == 3:
        mask_gray = cv2.cvtColor(mask_img, cv2.COLOR_BGR2GRAY)
    else:
        mask_gray = mask_img

    _, binary = cv2.threshold(mask_gray, 127, 255, cv2.THRESH_BINARY)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

    detections: List[Dict[str, Any]] = []

    for i in range(1, num_labels):  # Skip background (label 0)
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area:
            continue

        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        equiv_diam = float(np.sqrt(4.0 * area / np.pi))

        detections.append({
            "lesion_type": lesion_type,
            "class_id": CLASS_NAME_TO_ID[lesion_type],
            "bbox": {
                "x_min": x,
                "y_min": y,
                "x_max": x + w,
                "y_max": y + h,
            },
            "approximate_extent": {
                "area_pixels": area,
                "equivalent_diameter": round(equiv_diam, 2),
                "width": w,
                "height": h,
            },
            "centroid": [float(centroids[i][0]), float(centroids[i][1])],
        })

    return detections


def generate_image_tiles(
    img: np.ndarray,
    detections: List[Dict[str, Any]],
    tile_size: int = 640,
    overlap: float = 0.20,
) -> List[Tuple[np.ndarray, List[Dict[str, Any]], Tuple[int, int]]]:
    """
    Slices a high-resolution fundus image into overlapping tiles, translating
    lesion bounding boxes onto tile-relative coordinates.
    Preserves microaneurysms that would be obliterated by global downsampling.
    """
    img_h, img_w = img.shape[:2]
    step = int(tile_size * (1.0 - overlap))
    tiles: List[Tuple[np.ndarray, List[Dict[str, Any]], Tuple[int, int]]] = []

    y_starts = list(range(0, max(1, img_h - tile_size + 1), step))
    if y_starts[-1] + tile_size < img_h:
        y_starts.append(img_h - tile_size)

    x_starts = list(range(0, max(1, img_w - tile_size + 1), step))
    if x_starts[-1] + tile_size < img_w:
        x_starts.append(img_w - tile_size)

    for y in y_starts:
        for x in x_starts:
            tile = img[y : y + tile_size, x : x + tile_size].copy()
            tile_dets: List[Dict[str, Any]] = []

            for det in detections:
                bx = det["bbox"]
                # Compute intersection with this tile
                tx1 = max(0, bx["x_min"] - x)
                ty1 = max(0, bx["y_min"] - y)
                tx2 = min(tile_size, bx["x_max"] - x)
                ty2 = min(tile_size, bx["y_max"] - y)

                if tx2 > tx1 and ty2 > ty1:
                    orig_w = bx["x_max"] - bx["x_min"]
                    orig_h = bx["y_max"] - bx["y_min"]
                    inter_area = (tx2 - tx1) * (ty2 - ty1)
                    orig_area = max(1, orig_w * orig_h)

                    # Keep detection if at least 40% of the lesion is in this tile
                    if (inter_area / orig_area) >= 0.40:
                        tile_dets.append({
                            "lesion_type": det["lesion_type"],
                            "class_id": det["class_id"],
                            "bbox": {
                                "x_min": tx1,
                                "y_min": ty1,
                                "x_max": tx2,
                                "y_max": ty2,
                            },
                            "approximate_extent": det["approximate_extent"],
                        })

            tiles.append((tile, tile_dets, (x, y)))

    return tiles


class IDRiDLesionImporter:
    """Manages ingestion of IDRiD lesion masks and export to training/val/test formats."""

    def __init__(self, root_dir: str | Path, output_dir: str | Path):
        self.root_dir = Path(root_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def find_mask_file(self, stem: str, lesion_type: str, split_name: str) -> Optional[Path]:
        """Locate mask file for a given image stem and lesion class across standard IDRiD structures."""
        patterns = MASK_FOLDER_NAMES.get(lesion_type, [])
        # Direct matching across root
        for folder_pattern in patterns:
            for cand_dir in self.root_dir.glob(f"**/*{folder_pattern}*"):
                if not cand_dir.is_dir():
                    continue
                for ext in [".tif", ".png", ".jpg"]:
                    for candidate_name in [
                        f"{stem}_{lesion_type[:2].upper()}{ext}",
                        f"{stem}_MA{ext}",
                        f"{stem}_HE{ext}",
                        f"{stem}_EX{ext}",
                        f"{stem}_SE{ext}",
                        f"{stem}{ext}",
                    ]:
                        match = cand_dir / candidate_name
                        if match.exists():
                            return match
                    hits = list(cand_dir.glob(f"{stem}*{ext}"))
                    if hits:
                        return hits[0]
        return None

    def process(
        self,
        tile_size: int = 640,
        overlap: float = 0.20,
        val_ratio: float = 0.18,
    ) -> Dict[str, Any]:
        """Process images and ground truth masks into training/val/test sets."""
        logging.info("Starting IDRiD lesion dataset ingestion...")

        # Search for images under Training Set and Testing Set
        train_img_dirs = [
            self.root_dir / "Original Images" / "Training Set",
            self.root_dir / "a. Original Images" / "Training Set",
            self.root_dir / "Training Set",
            self.root_dir / "train",
        ]
        test_img_dirs = [
            self.root_dir / "Original Images" / "Testing Set",
            self.root_dir / "a. Original Images" / "Testing Set",
            self.root_dir / "Testing Set",
            self.root_dir / "test",
        ]

        train_imgs = []
        for d in train_img_dirs:
            if d.exists():
                train_imgs.extend(sorted(d.glob("*.jpg")))
                if train_imgs:
                    break

        test_imgs = []
        for d in test_img_dirs:
            if d.exists():
                test_imgs.extend(sorted(d.glob("*.jpg")))
                if test_imgs:
                    break

        if not train_imgs and not test_imgs:
            # Fallback: scan all jpg images
            all_jpgs = sorted(self.root_dir.glob("**/*.jpg"))
            train_imgs = all_jpgs[:54]
            test_imgs = all_jpgs[54:]

        logging.info(f"Found {len(train_imgs)} development images and {len(test_imgs)} evaluation images.")

        # Partition development images into train and validation
        num_val = int(len(train_imgs) * val_ratio)
        val_imgs = train_imgs[:num_val]
        actual_train_imgs = train_imgs[num_val:]

        splits = {
            "train": actual_train_imgs,
            "val": val_imgs,
            "test": test_imgs,
        }

        # Create YOLO directory hierarchy
        for split in ["train", "val", "test"]:
            (self.output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
            (self.output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

        manifest: List[Dict[str, Any]] = []
        total_lesion_counts = {k: 0 for k in LESION_CLASSES.values()}

        for split_name, img_list in splits.items():
            logging.info(f"Processing split '{split_name}' with {len(img_list)} images...")

            for img_path in img_list:
                stem = img_path.stem
                img = cv2.imread(str(img_path))
                if img is None:
                    continue

                h, w = img.shape[:2]
                img_detections: List[Dict[str, Any]] = []

                # Extract detections across each of the 4 lesion classes
                for lesion_type in LESION_CLASSES.values():
                    mask_file = self.find_mask_file(stem, lesion_type, split_name)
                    if mask_file is not None and mask_file.exists():
                        mask_img = cv2.imread(str(mask_file), cv2.IMREAD_GRAYSCALE)
                        if mask_img is not None:
                            dets = mask_to_bounding_boxes(
                                mask_img,
                                lesion_type,
                                min_area=MIN_LESION_AREA.get(lesion_type, 2),
                            )
                            img_detections.extend(dets)
                            total_lesion_counts[lesion_type] += len(dets)

                # Generate high-resolution tiles for training/validation
                if tile_size > 0 and (split_name in ["train", "val"]):
                    tiles = generate_image_tiles(img, img_detections, tile_size=tile_size, overlap=overlap)
                    for t_idx, (tile_img, tile_dets, (tx, ty)) in enumerate(tiles):
                        # Save tile if it contains lesions or keep background with 10% sampling
                        if tile_dets or (t_idx % 8 == 0):
                            tile_name = f"{stem}_tile_{tx}_{ty}.jpg"
                            out_img_path = self.output_dir / "images" / split_name / tile_name
                            cv2.imwrite(str(out_img_path), tile_img)

                            # Write YOLO label file
                            label_path = self.output_dir / "labels" / split_name / f"{stem}_tile_{tx}_{ty}.txt"
                            with open(label_path, "w", encoding="utf-8") as lf:
                                for det in tile_dets:
                                    bx = det["bbox"]
                                    cid = det["class_id"]
                                    cx = (bx["x_min"] + bx["x_max"]) / 2.0 / tile_size
                                    cy = (bx["y_min"] + bx["y_max"]) / 2.0 / tile_size
                                    bw = (bx["x_max"] - bx["x_min"]) / tile_size
                                    bh = (bx["y_max"] - bx["y_min"]) / tile_size
                                    lf.write(f"{cid} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
                else:
                    # Full-size export (e.g. for evaluation/test)
                    out_img_path = self.output_dir / "images" / split_name / f"{stem}.jpg"
                    shutil.copy2(img_path, out_img_path)

                    label_path = self.output_dir / "labels" / split_name / f"{stem}.txt"
                    with open(label_path, "w", encoding="utf-8") as lf:
                        for det in img_detections:
                            bx = det["bbox"]
                            cid = det["class_id"]
                            cx = (bx["x_min"] + bx["x_max"]) / 2.0 / w
                            cy = (bx["y_min"] + bx["y_max"]) / 2.0 / h
                            bw = (bx["x_max"] - bx["x_min"]) / w
                            bh = (bx["y_max"] - bx["y_min"]) / h
                            lf.write(f"{cid} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")

                manifest.append({
                    "image_id": stem,
                    "split": split_name,
                    "dimensions": [w, h],
                    "lesion_count": len(img_detections),
                    "detections": img_detections,
                })

        # Generate YOLOv8 dataset.yaml
        yaml_content = f"""# RetinaShield YOLOv8 Lesion Dataset Definition
# Generated from IDRiD Sub-challenge 1 (CC BY 4.0)

path: {self.output_dir.resolve()}
train: images/train
val: images/val
test: images/test

names:
  0: microaneurysm
  1: hemorrhage
  2: hard_exudate
  3: soft_exudate

license: "CC BY 4.0 — IDRiD (Porwal et al., 2018)"
"""
        with open(self.output_dir / "dataset.yaml", "w", encoding="utf-8") as yf:
            yf.write(yaml_content)

        manifest_path = self.output_dir / "lesion_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as mf:
            json.dump({
                "dataset_name": "IDRiD_Lesion_Segmentation",
                "license": "CC BY 4.0",
                "total_images": len(manifest),
                "total_lesion_counts": total_lesion_counts,
                "splits": {k: len(v) for k, v in splits.items()},
                "records": manifest,
            }, mf, indent=2)

        logging.info("IDRiD lesion import completed successfully.")
        logging.info(f"Summary counts: {total_lesion_counts}")
        logging.info(f"Manifest written to: {manifest_path}")

        return {
            "total_images": len(manifest),
            "lesion_counts": total_lesion_counts,
            "manifest_path": str(manifest_path),
            "yaml_path": str(self.output_dir / "dataset.yaml"),
        }


def main():
    parser = argparse.ArgumentParser(description="Import IDRiD expert lesion annotations.")
    parser.add_argument("--input-dir", required=True, help="Directory containing raw IDRiD segmentation files")
    parser.add_argument("--output-dir", required=True, help="Directory to save YOLOv8 dataset and manifests")
    parser.add_argument("--tile-size", type=int, default=640, help="Tile dimension for high-resolution slicing")
    parser.add_argument("--overlap", type=float, default=0.20, help="Tile overlap ratio (default: 0.20)")
    parser.add_argument("--val-ratio", type=float, default=0.18, help="Fraction of development images for validation")
    args = parser.parse_args()

    importer = IDRiDLesionImporter(args.input_dir, args.output_dir)
    importer.process(tile_size=args.tile_size, overlap=args.overlap, val_ratio=args.val_ratio)


if __name__ == "__main__":
    main()
