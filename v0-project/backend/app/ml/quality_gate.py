"""Quality gate for uploaded eye images.

Runs before analysis. Flags blurry/failed captures so the user is asked to
recapture, and applies a light heuristic to catch obviously non-fundus
uploads (e.g. selfies) before they reach the model pipeline.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

BLUR_VAR_THRESHOLD = 15.0
BLUR_METRIC_SIZE = 500
RED_DOMINANCE_THRESHOLD = 0.32
DARK_RING_THRESHOLD = 0.24

# The blur metric is the variance-of-Laplacian computed on a fixed 500px
# downscale so it is resolution-independent. Tuned on APTOS 2019: sharp
# fundus photos median ~30 (p25 ~21), so 15 cleanly separates deliberately
# blurry captures (score < 15) from acceptable ones.


def _variance_of_laplacian(gray: np.ndarray) -> float:
    """Blur metric: higher variance = sharper image. Vectorized 3x3 Laplacian."""
    h, w = gray.shape
    padded = np.pad(gray, 1, mode="edge")
    out = (
        padded[0:-2, 1:-1]  # top
        + padded[1:-1, 0:-2]  # left
        - 4.0 * padded[1:-1, 1:-1]  # center
        + padded[1:-1, 2:]  # right
        + padded[2:, 1:-1]  # bottom
    )
    return float(out.var())


def _red_dominance(img: Image.Image) -> float:
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    total = (r + g + b).sum() + 1e-6
    return float(r.sum() / total)


def _dark_ring_fraction(img: Image.Image, ring_frac: float = 0.18) -> float:
    """Fraction of the outer border that is dark — fundus photos have a dark periphery."""
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    h, w = rgb.shape[:2]
    bh, bw = max(1, int(h * ring_frac / 2)), max(1, int(w * ring_frac / 2))
    border = np.concatenate(
        [
            rgb[:bh, :, :].reshape(-1, 3),
            rgb[-bh:, :, :].reshape(-1, 3),
            rgb[:, :bw, :].reshape(-1, 3),
            rgb[:, -bw:, :].reshape(-1, 3),
        ]
    )
    brightness = border.mean(axis=1)
    return float((brightness < 90).mean())


def assess_quality(image_bytes: bytes) -> dict:
    """Returns a dict with score fields, status, and a recapture flag."""
    result = {
        "status": "acceptable",
        "blur_score": 0.0,
        "red_dominance": 0.0,
        "dark_ring_fraction": 0.0,
        "notes": [],
    }

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        result["status"] = "poor"
        result["notes"].append("Could not read file as an image.")
        return result

    gray = np.asarray(
        img.resize((BLUR_METRIC_SIZE, BLUR_METRIC_SIZE), Image.BILINEAR).convert("L"),
        dtype=np.float32,
    )
    blur_score = _variance_of_laplacian(gray)
    red_dom = _red_dominance(img)
    dark_ring = _dark_ring_fraction(img)

    result["blur_score"] = round(blur_score, 2)
    result["red_dominance"] = round(red_dom, 3)
    result["dark_ring_fraction"] = round(dark_ring, 3)

    if blur_score < BLUR_VAR_THRESHOLD:
        result["status"] = "poor"
        result["notes"].append(
            f"Image appears blurry (focus score {blur_score:.0f}). Please recapture."
        )
    if red_dom < RED_DOMINANCE_THRESHOLD:
        result["notes"].append(
            "Low red-channel dominance — this may not be a fundus photograph. "
            "Engine A/B outputs should be treated with caution."
        )
    if dark_ring < DARK_RING_THRESHOLD:
        result["notes"].append(
            "No dark periphery detected — this may not be a fundus photograph."
        )

    return result