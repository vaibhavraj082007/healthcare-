"""
RetinaShield — YOLOv8 Lesion Detection Service

Detects DR-related lesions in fundus images using YOLOv8:
  - Microaneurysms
  - Hemorrhages
  - Hard exudates
  - Soft exudates (cotton-wool spots)
  - Neovascularization

This is a Python service (not MATLAB) used alongside the MATLAB core pipeline.

WARNING: Without trained weights, this returns an empty UNTRAINED result.
         Never fabricate detections.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from app.config import settings
    DEFAULT_WEIGHTS_PATH = getattr(settings, "yolo_weights_path", "models/weights/yolov8_lesions.pt")
    DEFAULT_CONF_THRESH = getattr(settings, "yolo_confidence_threshold", 0.25)
    DEFAULT_DEVICE = getattr(settings, "yolo_device", "cpu")
except ImportError:
    settings = None
    DEFAULT_WEIGHTS_PATH = "models/weights/yolov8_lesions.pt"
    DEFAULT_CONF_THRESH = 0.25
    DEFAULT_DEVICE = "cpu"

try:
    from app.schemas.analysis_result import (
        ApproximateExtent,
        LesionBBox,
        LesionDetection,
        LesionDetectionResult,
    )
except ImportError:
    from dataclasses import dataclass, field

    @dataclass
    class ApproximateExtent:
        area_pixels: float | None = None
        equivalent_diameter: float | None = None
        width: float | None = None
        height: float | None = None

    @dataclass
    class LesionBBox:
        x_min: float
        y_min: float
        x_max: float
        y_max: float

    @dataclass
    class LesionDetection:
        lesion_type: str
        bbox: LesionBBox
        confidence: float
        approximate_extent: ApproximateExtent | None = None
        is_heuristic_candidate: bool = False

    @dataclass
    class LesionDetectionResult:
        model: str = "YOLOv8"
        status: str = "unavailable"
        message: str = "Lesion detector unavailable"
        detections: list[Any] = field(default_factory=list)
        model_estimated_count: dict[str, int] = field(default_factory=dict)
        model_trained: bool = False

logger = logging.getLogger(__name__)

# Lesion class mapping (must match training data class order)
LESION_CLASSES = {
    0: "microaneurysm",
    1: "hemorrhage",
    2: "hard_exudate",
    3: "soft_exudate",
    4: "neovascularization",
}


class YOLOService:
    """YOLOv8-based lesion detection for diabetic retinopathy."""

    def __init__(
        self,
        weights_path: str | None = None,
        confidence_threshold: float | None = None,
        device: str | None = None,
    ) -> None:
        self._model = None
        self._model_loaded = False
        self._weights_path = weights_path or DEFAULT_WEIGHTS_PATH
        self._confidence_threshold = confidence_threshold or DEFAULT_CONF_THRESH
        self._device = device or DEFAULT_DEVICE

        if self._weights_path:
            self._try_load_model()

    def is_available(self) -> bool:
        """Check if trained weights are loaded and detector is ready for inference."""
        return self._model_loaded

    def _try_load_model(self) -> None:
        """Attempt to load YOLOv8 model from weights file."""
        weights = Path(self._weights_path)
        if not weights.is_file():
            logger.warning(
                f"YOLOv8 weights not found at: {self._weights_path}. "
                "Lesion detection will expose 'Lesion detector unavailable'."
            )
            return

        try:
            from ultralytics import YOLO  # type: ignore

            self._model = YOLO(str(weights))
            self._model_loaded = True
            logger.info(f"YOLOv8 model loaded from: {self._weights_path}")
        except ImportError:
            logger.error(
                "ultralytics not installed. Run: pip install ultralytics"
            )
        except Exception as e:
            logger.error(f"Failed to load YOLOv8 model: {e}")

    async def detect_lesions(self, image_path: str) -> LesionDetectionResult:
        """
        Run lesion detection on a fundus image.

        Returns LesionDetectionResult with status='unavailable' if
        no trained weights are available. Never fabricates results.
        Preserves resolution via overlapping tiling when image dimensions are large.
        """
        if not self._model_loaded or self._model is None:
            logger.info(
                "YOLOv8 model not loaded — returning 'Lesion detector unavailable'. "
                "Train on IDRiD or similar annotated lesion dataset for real detections."
            )
            return LesionDetectionResult(
                model="YOLOv8",
                status="unavailable",
                message="Lesion detector unavailable — Trained YOLOv8 weights not found. Model training on expert-annotated lesion dataset required.",
                detections=[],
                model_estimated_count={},
                model_trained=False,
            )

        # Verify image exists
        if not Path(image_path).is_file():
            logger.error(f"Image not found: {image_path}")
            return LesionDetectionResult(
                model="YOLOv8",
                status="unavailable",
                message=f"Image file not found: {image_path}",
                detections=[],
                model_estimated_count={},
                model_trained=self._model_loaded,
            )

        try:
            # Check image dimensions for tiling decision
            import cv2
            import numpy as np
            from scripts.yolo_tiled_inference import run_tiled_inference

            img = cv2.imread(image_path)
            h, w = img.shape[:2]

            # If image is high-resolution (min dimension > 800px), use resolution-preserving tiling
            if min(h, w) > 800:
                logger.info(f"Running high-resolution tiled inference on {w}x{h} image...")
                tiled_res = run_tiled_inference(
                    self._model,
                    image_path,
                    tile_size=640,
                    overlap=0.20,
                    conf_thresh=self._confidence_threshold,
                    device=self._device,
                )
                detections: list[LesionDetection] = [
                    LesionDetection(
                        lesion_type=d["lesion_type"],
                        bbox=LesionBBox(**d["bbox"]),
                        confidence=d["confidence"],
                        approximate_extent=ApproximateExtent(**d["approximate_extent"]),
                        is_heuristic_candidate=False,
                    )
                    for d in tiled_res["detections"]
                ]
                counts = tiled_res["model_estimated_count"]
            else:
                # Standard full-image inference for smaller images
                results = self._model.predict(
                    source=image_path,
                    conf=self._confidence_threshold,
                    device=self._device,
                    verbose=False,
                )

                detections = []
                counts = {}
                for result in results:
                    boxes = result.boxes
                    if boxes is None:
                        continue

                    for i in range(len(boxes)):
                        cls_id = int(boxes.cls[i].item())
                        conf = float(boxes.conf[i].item())
                        x1, y1, x2, y2 = boxes.xyxy[i].tolist()

                        lesion_type = LESION_CLASSES.get(cls_id)
                        if lesion_type is None:
                            continue

                        bw = x2 - x1
                        bh = y2 - y1
                        area = bw * bh
                        diam = float(np.sqrt(4.0 * area / np.pi))

                        detections.append(
                            LesionDetection(
                                lesion_type=lesion_type,
                                bbox=LesionBBox(x_min=x1, y_min=y1, x_max=x2, y_max=y2),
                                confidence=conf,
                                approximate_extent=ApproximateExtent(
                                    area_pixels=round(area, 1),
                                    equivalent_diameter=round(diam, 1),
                                    width=round(bw, 1),
                                    height=round(bh, 1),
                                ),
                                is_heuristic_candidate=False,
                            )
                        )
                        counts[lesion_type] = counts.get(lesion_type, 0) + 1

            logger.info(f"YOLOv8 detected {len(detections)} lesions in {image_path}")
            return LesionDetectionResult(
                model="YOLOv8",
                status="ready",
                message=f"Detected {len(detections)} lesions across 4 classes",
                detections=detections,
                model_estimated_count=counts,
                model_trained=True,
            )

        except Exception as e:
            logger.error(f"YOLOv8 inference failed: {e}")
            return LesionDetectionResult(
                model="YOLOv8",
                status="unavailable",
                message=f"YOLOv8 inference error: {e}",
                detections=[],
                model_estimated_count={},
                model_trained=self._model_loaded,
            )

    @property
    def is_ready(self) -> bool:
        """Whether a trained model is loaded and ready for inference."""
        return self._model_loaded


# Singleton
yolo_service = YOLOService()

