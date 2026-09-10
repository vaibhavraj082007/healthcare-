"""
RetinaShield — Sliding-Window Tiled Inference for Lesion Detection
===================================================================
Provides:
  - generate_tiles      : non-uniform stride sliding-window tile coordinates
  - compute_iou         : axis-aligned IoU for two bounding boxes
  - nms_merge_detections: per-class NMS over tiled detections
  - compute_approximate_extent : area / diameter / w / h from bbox
  - run_tiled_inference : run an inference callable over all tiles and merge

These functions are pure Python + NumPy — no YOLO / torch import at module level
so that unit tests can run without GPU dependencies.

Coordinate convention
---------------------
All bounding boxes are in absolute pixel coordinates of the *full* image,
mapped from tile-local coordinates before returning.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Tile generation
# ---------------------------------------------------------------------------

def generate_tiles(
    *,
    img_w: int,
    img_h: int,
    tile_size: int = 640,
    overlap: float = 0.20,
) -> List[Tuple[int, int, int, int]]:
    """
    Generate non-overlapping sliding-window tiles that cover the full image.

    Parameters
    ----------
    img_w, img_h : full image dimensions in pixels
    tile_size    : square tile edge length
    overlap      : fractional overlap between adjacent tiles  (0 ≤ overlap < 1)

    Returns
    -------
    List of (x1, y1, x2, y2) tuples in absolute pixel coordinates.
    Tiles that would extend past image boundaries are clipped and padded
    conceptually (the caller is responsible for zero-padding when cropping).
    """
    if overlap < 0 or overlap >= 1:
        raise ValueError("overlap must be in [0, 1)")

    stride = int(math.floor(tile_size * (1.0 - overlap)))
    stride = max(stride, 1)

    tiles: List[Tuple[int, int, int, int]] = []

    y = 0
    while True:
        x = 0
        while True:
            x1 = x
            y1 = y
            x2 = min(x + tile_size, img_w)
            y2 = min(y + tile_size, img_h)

            # Shift tile left/up if it's smaller than tile_size at the boundary
            if x2 - x1 < tile_size and img_w >= tile_size:
                x1 = max(0, img_w - tile_size)
                x2 = img_w
            if y2 - y1 < tile_size and img_h >= tile_size:
                y1 = max(0, img_h - tile_size)
                y2 = img_h

            # Enforce exact tile size
            x2 = x1 + tile_size
            y2 = y1 + tile_size

            # Clip to image bounds
            x2 = min(x2, img_w)
            y2 = min(y2, img_h)

            tiles.append((x1, y1, x2, y2))

            if x + tile_size >= img_w:
                break
            x += stride

        if y + tile_size >= img_h:
            break
        y += stride

    return tiles


# ---------------------------------------------------------------------------
# IoU
# ---------------------------------------------------------------------------

def compute_iou(
    box_a: List[float],
    box_b: List[float],
) -> float:
    """
    Compute Intersection over Union for two axis-aligned bounding boxes.

    Each box is [x_min, y_min, x_max, y_max].
    """
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    inter_w = max(0.0, ix2 - ix1)
    inter_h = max(0.0, iy2 - iy1)
    inter_area = inter_w * inter_h

    if inter_area == 0.0:
        return 0.0

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union_area = area_a + area_b - inter_area

    return float(inter_area / union_area) if union_area > 0 else 0.0


# ---------------------------------------------------------------------------
# Approximate extent
# ---------------------------------------------------------------------------

def compute_approximate_extent(bbox: Dict[str, float]) -> Dict[str, float]:
    """
    Compute area, equivalent diameter, width, and height from a bbox dict.

    Parameters
    ----------
    bbox : dict with keys x_min, y_min, x_max, y_max

    Returns
    -------
    dict with area_pixels, equivalent_diameter, width, height
    """
    w = max(0.0, bbox.get("x_max", 0.0) - bbox.get("x_min", 0.0))
    h = max(0.0, bbox.get("y_max", 0.0) - bbox.get("y_min", 0.0))
    area = w * h
    diameter = 2.0 * math.sqrt(area / math.pi) if area > 0 else 0.0
    return {
        "area_pixels": area,
        "equivalent_diameter": diameter,
        "width": w,
        "height": h,
    }


# ---------------------------------------------------------------------------
# Per-class Non-Maximum Suppression (greedy)
# ---------------------------------------------------------------------------

def nms_merge_detections(
    detections: List[Dict[str, Any]],
    *,
    iou_thresh: float = 0.40,
) -> List[Dict[str, Any]]:
    """
    Greedy per-class NMS over a list of detection dicts.

    Each detection dict must have:
      - lesion_type : str
      - bbox        : dict with x_min, y_min, x_max, y_max
      - confidence  : float

    Parameters
    ----------
    detections : list of detection dicts (from tiled inference)
    iou_thresh : IoU above which a lower-confidence box is suppressed

    Returns
    -------
    Filtered list of detection dicts (no duplicate fields added).
    """
    if not detections:
        return []

    # Group by lesion_type
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for d in detections:
        by_type.setdefault(d["lesion_type"], []).append(d)

    kept: List[Dict[str, Any]] = []
    for ltype, dets in by_type.items():
        # Sort descending by confidence
        dets_sorted = sorted(dets, key=lambda x: x["confidence"], reverse=True)
        suppressed = [False] * len(dets_sorted)

        for i, det_i in enumerate(dets_sorted):
            if suppressed[i]:
                continue
            kept.append(det_i)
            b_i = det_i["bbox"]
            box_i = [b_i["x_min"], b_i["y_min"], b_i["x_max"], b_i["y_max"]]
            for j in range(i + 1, len(dets_sorted)):
                if suppressed[j]:
                    continue
                b_j = dets_sorted[j]["bbox"]
                box_j = [b_j["x_min"], b_j["y_min"], b_j["x_max"], b_j["y_max"]]
                if compute_iou(box_i, box_j) >= iou_thresh:
                    suppressed[j] = True

    return kept


# ---------------------------------------------------------------------------
# Tiled inference runner
# ---------------------------------------------------------------------------

def run_tiled_inference(
    image: np.ndarray,
    inference_fn: Callable[[np.ndarray], List[Dict[str, Any]]],
    *,
    tile_size: int = 640,
    overlap: float = 0.20,
    nms_iou_thresh: float = 0.40,
    conf_thresh: float = 0.25,
) -> List[Dict[str, Any]]:
    """
    Run an inference callable over all tiles of an image and merge results.

    Parameters
    ----------
    image        : (H, W, 3) uint8 numpy array
    inference_fn : callable(tile_img) → list of detection dicts in tile coordinates
                   Each dict: {lesion_type, bbox: {x_min, y_min, x_max, y_max},
                               confidence, approximate_extent?}
    tile_size    : square tile edge in pixels
    overlap      : fractional tile overlap
    nms_iou_thresh : IoU threshold for NMS
    conf_thresh  : minimum confidence to keep a raw detection

    Returns
    -------
    List of detection dicts with bboxes mapped to full-image coordinates,
    after cross-tile NMS.
    """
    h, w = image.shape[:2]
    tiles = generate_tiles(img_w=w, img_h=h, tile_size=tile_size, overlap=overlap)
    all_dets: List[Dict[str, Any]] = []

    for x1, y1, x2, y2 in tiles:
        # Crop (and possibly zero-pad if tile extends beyond image)
        tile_crop = image[y1:y2, x1:x2]

        try:
            raw = inference_fn(tile_crop)
        except Exception:
            continue

        for det in raw:
            if det.get("confidence", 0.0) < conf_thresh:
                continue
            # Map bbox to full-image coordinates
            b = det.get("bbox", {})
            mapped_bbox = {
                "x_min": b.get("x_min", 0.0) + x1,
                "y_min": b.get("y_min", 0.0) + y1,
                "x_max": b.get("x_max", 0.0) + x1,
                "y_max": b.get("y_max", 0.0) + y1,
            }
            mapped_det = {**det, "bbox": mapped_bbox}
            if "approximate_extent" not in mapped_det:
                mapped_det["approximate_extent"] = compute_approximate_extent(mapped_bbox)
            all_dets.append(mapped_det)

    return nms_merge_detections(all_dets, iou_thresh=nms_iou_thresh)
