"""Preprocessing used by both training and live inference.

Must stay identical between train_classifier.py and the /analyze endpoint so
that inference never silently diverges from training: resize -> CLAHE ->
denoising -> ImageNet normalization.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

IMAGE_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGE_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _cv2_available() -> bool:
    try:
        import cv2  # noqa: F401

        return True
    except ImportError:
        return False


def preprocess_image(image: Image.Image, size: int = 380) -> np.ndarray:
    """Return a CHW float32 tensor normalized with ImageNet mean/std.

    Pipeline: center-crop to square -> resize to ``size`` -> CLAHE ->
    fast denoise -> normalize. Uses OpenCV when installed (recommended) and
    falls back to PIL+numpy otherwise.
    """
    img_pp = _make_display_image(image, size)
    arr = img_pp.astype(np.float32) / 255.0
    arr = (arr - IMAGE_MEAN[None, None, :]) / IMAGE_STD[None, None, :]
    return np.transpose(arr, (2, 0, 1)).astype(np.float32)


def preprocess_image_display(image: Image.Image, size: int = 380) -> np.ndarray:
    """Return the HWC uint8 display image the model actually saw (crop -> resize
    -> CLAHE -> denoise, WITHOUT the final ImageNet normalization).

    Used by Grad-CAM so the heatmap overlay aligns pixel-for-pixel with the
    preprocessed fundus image fed to the classifier.
    """
    return _make_display_image(image, size)


def _make_display_image(image: Image.Image, size: int) -> np.ndarray:
    img = _square_center_crop(image.convert("RGB"))
    img = img.resize((size, size), Image.BILINEAR)

    if _cv2_available():
        arr = _preprocess_cv2(img)
    else:
        arr = _preprocess_pil(img)

    # (3, H, W) float -> (H, W, 3) uint8
    arr = np.transpose(arr, (1, 2, 0))
    return np.clip(arr, 0, 255).astype(np.uint8)


def _square_center_crop(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def _preprocess_cv2(img: Image.Image) -> np.ndarray:
    import cv2

    bgr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    l_eq = clahe.apply(l_channel)
    merged = cv2.merge((l_eq, a_channel, b_channel))
    bgr_eq = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
    denoised = cv2.fastNlMeansDenoisingColored(bgr_eq, None, h=5, hColor=5, templateWindowSize=7, searchWindowSize=21)
    rgb = cv2.cvtColor(denoised, cv2.COLOR_BGR2RGB)
    return np.transpose(rgb, (2, 0, 1)).astype(np.float32)


def _preprocess_pil(img: Image.Image) -> np.ndarray:
    """PIL+numpy fallback: grayscale-equalized-round-trip via CLAHE-lite."""
    arr = np.asarray(img, dtype=np.float32)
    # simple contrast-limited equalization per channel on the L approximation
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    # percentile clip + histogram stretch (blocks of 64x64)
    h, w = gray.shape
    bs = 64
    for y0 in range(0, h, bs):
        for x0 in range(0, w, bs):
            block = gray[y0 : y0 + bs, x0 : x0 + bs]
            if block.size == 0:
                continue
            lo = np.percentile(block, 2)
            hi = np.percentile(block, 98)
            span = max(hi - lo, 1e-3)
            block_stretched = np.clip((block - lo) / span, 0, 1) * 255.0
            factor = 2.5
            gray[y0 : y0 + bs, x0 : x0 + bs] = np.clip(
                block + (block_stretched - block) * min(factor, 1.0),
                0,
                255,
            )
    # blend equalized luminance back into RGB (approximation of CLAHE)
    gray_eq = gray / 255.0
    arr_norm = arr / 255.0
    luminance = arr_norm.mean(axis=2, keepdims=True) + 1e-6
    scaled = arr_norm * (gray_eq[..., None] / luminance)
    return np.transpose(np.clip(scaled * 255.0, 0, 255).astype(np.float32), (2, 0, 1))