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

from app.config import settings
from app.schemas.analysis_result import (
    LesionBBox,
    LesionDetection,
    LesionDetectionResult,
)

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

    def __init__(self) -> None:
        self._model = None
        self._model_loaded = False
        self._weights_path = settings.yolo_weights_path
        self._confidence_threshold = settings.yolo_confidence_threshold
        self._device = settings.yolo_device

        if self._weights_path:
            self._try_load_model()

    def _try_load_model(self) -> None:
        """Attempt to load YOLOv8 model from weights file."""
        weights = Path(self._weights_path)
        if not weights.is_file():
            logger.warning(
                f"YOLOv8 weights not found at: {self._weights_path}. "
                "Lesion detection will return UNTRAINED results."
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

        Returns LesionDetectionResult with model_trained=False if
        no trained weights are available. Never fabricates results.
        """
        if not self._model_loaded or self._model is None:
            logger.info(
                "YOLOv8 model not loaded — returning UNTRAINED result. "
                "Train on IDRiD or similar dataset for real detections."
            )
            return LesionDetectionResult(
                model="YOLOv8",
                detections=[],
                model_trained=False,
            )

        # Verify image exists
        if not Path(image_path).is_file():
            logger.error(f"Image not found: {image_path}")
            return LesionDetectionResult(
                model="YOLOv8", detections=[], model_trained=self._model_loaded
            )

        try:
            # Run inference
            results = self._model.predict(
                source=image_path,
                conf=self._confidence_threshold,
                device=self._device,
                verbose=False,
            )

            detections: list[LesionDetection] = []
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
                        logger.warning(f"Unknown class ID: {cls_id}")
                        continue

                    detections.append(
                        LesionDetection(
                            lesion_type=lesion_type,
                            bbox=LesionBBox(
                                x_min=x1, y_min=y1, x_max=x2, y_max=y2
                            ),
                            confidence=conf,
                        )
                    )

            logger.info(f"YOLOv8 detected {len(detections)} lesions in {image_path}")
            return LesionDetectionResult(
                model="YOLOv8",
                detections=detections,
                model_trained=True,
            )

        except Exception as e:
            logger.error(f"YOLOv8 inference failed: {e}")
            return LesionDetectionResult(
                model="YOLOv8", detections=[], model_trained=self._model_loaded
            )

    @property
    def is_ready(self) -> bool:
        """Whether a trained model is loaded and ready for inference."""
        return self._model_loaded


# Singleton
yolo_service = YOLOService()
