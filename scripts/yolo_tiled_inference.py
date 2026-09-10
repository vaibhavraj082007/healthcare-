#!/usr/bin/env python3
"""
RetinaShield — YOLOv8 Tiled Inference & Bounding-Box Merging Adapter

High-resolution sliding-window inference:
  1. Slices full-resolution fundus images (e.g. 4288x2848) into overlapping tiles.
  2. Runs YOLOv8 inference per tile, preserving microaneurysm resolution.
  3. Projects tile-relative coordinates back into original image space.
  4. Merges multi-tile overlapping detections using IoU Non-Maximum Suppression (NMS).
  5. Computes approximate lesion extent and aggregates model-estimated counts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

LESION_CLASSES = {
    0: "microaneurysm",
    1: "hemorrhage",
    2: "hard_exudate",
    3: "soft_exudate",
    4: "neovascularization",
}


def compute_approximate_extent(x_min: float, y_min: float, x_max: float, y_max: float) -> Dict[str, float]:
    """Compute width, height, area in pixels, and equivalent diameter."""
    w = max(0.0, x_max - x_min)
    h = max(0.0, y_max - y_min)
    area = w * h
    diam = float(np.sqrt(4.0 * area / np.pi)) if area > 0 else 0.0
    return {
        "area_pixels": round(area, 1),
        "equivalent_diameter": round(diam, 1),
        "width": round(w, 1),
        "height": round(h, 1),
    }


def generate_tiles(img_w: int, img_h: int, tile_size: int = 640, overlap: float = 0.20) -> List[Tuple[int, int, int, int]]:
    """Generate (x1, y1, x2, y2) bounds for sliding-window tiles across the image."""
    step = int(tile_size * (1.0 - overlap))
    if step <= 0:
        step = tile_size

    x_starts = list(range(0, max(1, img_w - tile_size + 1), step))
    if not x_starts or x_starts[-1] + tile_size < img_w:
        x_starts.append(max(0, img_w - tile_size))

    y_starts = list(range(0, max(1, img_h - tile_size + 1), step))
    if not y_starts or y_starts[-1] + tile_size < img_h:
        y_starts.append(max(0, img_h - tile_size))

    tiles: List[Tuple[int, int, int, int]] = []
    for y_off in y_starts:
        for x_off in x_starts:
            tiles.append((x_off, y_off, min(img_w, x_off + tile_size), min(img_h, y_off + tile_size)))
    return tiles


def compute_iou(boxA: Any, boxB: Any) -> float:
    """Compute Intersection-over-Union between two bounding boxes (supports dict or [x1, y1, x2, y2])."""
    if isinstance(boxA, (list, tuple)):
        ax1, ay1, ax2, ay2 = boxA[:4]
    else:
        ax1, ay1, ax2, ay2 = boxA["x_min"], boxA["y_min"], boxA["x_max"], boxA["y_max"]

    if isinstance(boxB, (list, tuple)):
        bx1, by1, bx2, by2 = boxB[:4]
    else:
        bx1, by1, bx2, by2 = boxB["x_min"], boxB["y_min"], boxB["x_max"], boxB["y_max"]

    xA = max(ax1, bx1)
    yA = max(ay1, by1)
    xB = min(ax2, bx2)
    yB = min(ay2, by2)

    inter_w = max(0.0, xB - xA)
    inter_h = max(0.0, yB - yA)
    inter_area = inter_w * inter_h

    boxA_area = max(1e-5, (ax2 - ax1) * (ay2 - ay1))
    boxB_area = max(1e-5, (bx2 - bx1) * (by2 - by1))

    return inter_area / float(boxA_area + boxB_area - inter_area)


def nms_merge_detections(
    detections: List[Dict[str, Any]],
    iou_thresh: float = 0.45,
) -> List[Dict[str, Any]]:
    """
    Merge duplicate detections across overlapping tile boundaries using class-aware NMS.
    """
    if not detections:
        return []

    merged: List[Dict[str, Any]] = []

    # Group by lesion type
    by_class: Dict[str, List[Dict[str, Any]]] = {}
    for det in detections:
        by_class.setdefault(det["lesion_type"], []).append(det)

    for l_type, det_list in by_class.items():
        # Sort by confidence descending
        det_list.sort(key=lambda d: d["confidence"], reverse=True)
        keep: List[Dict[str, Any]] = []

        while det_list:
            current = det_list.pop(0)
            overlapping = [current]
            remaining = []

            for other in det_list:
                iou = compute_iou(current["bbox"], other["bbox"])
                if iou >= iou_thresh:
                    overlapping.append(other)
                else:
                    remaining.append(other)

            # Fuse overlapping boxes: take bounding union with highest confidence
            min_x = min(d["bbox"]["x_min"] for d in overlapping)
            min_y = min(d["bbox"]["y_min"] for d in overlapping)
            max_x = max(d["bbox"]["x_max"] for d in overlapping)
            max_y = max(d["bbox"]["y_max"] for d in overlapping)
            max_conf = max(d["confidence"] for d in overlapping)

            bw = max_x - min_x
            bh = max_y - min_y
            area = bw * bh
            diam = float(np.sqrt(4.0 * area / np.pi))

            fused = {
                "lesion_type": l_type,
                "bbox": {
                    "x_min": round(min_x, 1),
                    "y_min": round(min_y, 1),
                    "x_max": round(max_x, 1),
                    "y_max": round(max_y, 1),
                },
                "confidence": round(max_conf, 3),
                "approximate_extent": {
                    "area_pixels": round(area, 1),
                    "equivalent_diameter": round(diam, 1),
                    "width": round(bw, 1),
                    "height": round(bh, 1),
                },
                "is_heuristic_candidate": False,
            }
            keep.append(fused)
            det_list = remaining

        merged.extend(keep)

    return merged


def run_tiled_inference(
    model: Any,
    image_path: str | Path,
    tile_size: int = 640,
    overlap: float = 0.20,
    conf_thresh: float = 0.25,
    device: str = "cpu",
) -> Dict[str, Any]:
    """
    Execute resolution-preserving tiled YOLOv8 inference on a full fundus image.
    Maps all detections back to original image space and merges overlapping boxes.
    """
    img_path = Path(image_path)
    if not img_path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    img = cv2.imread(str(img_path))
    if img is None:
        raise ValueError(f"Could not read image: {image_path}")

    img_h, img_w = img.shape[:2]
    step = int(tile_size * (1.0 - overlap))

    y_starts = list(range(0, max(1, img_h - tile_size + 1), step))
    if y_starts[-1] + tile_size < img_h:
        y_starts.append(img_h - tile_size)

    x_starts = list(range(0, max(1, img_w - tile_size + 1), step))
    if x_starts[-1] + tile_size < img_w:
        x_starts.append(img_w - tile_size)

    raw_detections: List[Dict[str, Any]] = []

    for y_off in y_starts:
        for x_off in x_starts:
            tile = img[y_off : y_off + tile_size, x_off : x_off + tile_size]
            results = model.predict(source=tile, conf=conf_thresh, device=device, verbose=False)

            for res in results:
                boxes = res.boxes
                if boxes is None:
                    continue
                for i in range(len(boxes)):
                    cls_id = int(boxes.cls[i].item())
                    conf = float(boxes.conf[i].item())
                    bx1, by1, bx2, by2 = boxes.xyxy[i].tolist()

                    lesion_type = LESION_CLASSES.get(cls_id, f"lesion_{cls_id}")

                    # Map coordinates back to original image coordinates
                    orig_x1 = bx1 + x_off
                    orig_y1 = by1 + y_off
                    orig_x2 = bx2 + x_off
                    orig_y2 = by2 + y_off

                    raw_detections.append({
                        "lesion_type": lesion_type,
                        "bbox": {
                            "x_min": orig_x1,
                            "y_min": orig_y1,
                            "x_max": orig_x2,
                            "y_max": orig_y2,
                        },
                        "confidence": conf,
                    })

    # Merge overlapping boxes across tiles
    merged_detections = nms_merge_detections(raw_detections, iou_thresh=0.45)

    # Count estimated lesions per class
    counts: Dict[str, int] = {}
    for det in merged_detections:
        lt = det["lesion_type"]
        counts[lt] = counts.get(lt, 0) + 1

    return {
        "status": "ready",
        "model": "YOLOv8-tiled",
        "model_trained": True,
        "detections": merged_detections,
        "model_estimated_count": counts,
        "tiling_config": {
            "tile_size": tile_size,
            "overlap": overlap,
            "tiles_processed": len(x_starts) * len(y_starts),
        },
    }
