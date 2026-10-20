"""Engine A — YOLOv8 lesion detector.

APTOS provides no lesion bounding boxes. Two honest options:
  A) fine-tune a pretrained YOLOv8 on IDRiD (masks -> boxes -> YOLO labels)
  B) load an openly published pretrained DR-lesion checkpoint as-is

The chosen provenance string is surfaced in the UI Model Info panel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings

LESION_LABELS = {
    0: "microaneurysm",
    1: "hemorrhage",
    2: "hard_exudate",
    3: "soft_exudate",
}


class ModelUnavailableError(RuntimeError):
    pass


@dataclass
class Detection:
    label: str
    confidence: float
    box: list[int]


@dataclass
class DetectorResult:
    detections: list[Detection] = field(default_factory=list)

    @property
    def lesion_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for det in self.detections:
            counts[det.label] = counts.get(det.label, 0) + 1
        return counts

    @property
    def total_count(self) -> int:
        return len(self.detections)


class DRDetector:
    """YOLOv8 lesion detector loaded from a checkpoint."""

    PROVENANCE = {
        "option": "pretrained",
        "detail": (
            "Loaded a public DR-lesion YOLO checkpoint. Not fine-tuned on the APTOS "
            "dataset (APTOS has no lesion annotations). See IDRiD fine-tune option in "
            "backend/train_detector.py for fully in-house training."
        ),
    }

    @classmethod
    def provenance_for(cls, weights_path) -> dict:
        """Honest provenance: prefer the IDRiD fine-tune marker when present."""
        marker = Path(weights_path).with_suffix(".pt.meta.json") if weights_path else None
        if marker is not None and marker.exists():
            try:
                meta = json.loads(marker.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                meta = {}
            if meta:
                return {
                    "option": "idrid_fine_tuned",
                    "detail": (
                        f"YOLOv8n fine-tuned in-house on the IDRiD lesion dataset "
                        f"({meta.get('train_images')} train / {meta.get('val_images')} val "
                        f"images, {meta.get('lesion_boxes')} boxes, val mAP50 "
                        f"{meta.get('val_map50'):.3f}, {meta.get('training_date')})."
                    ),
                }
        return cls.PROVENANCE

    def __init__(self, weights_path=None):
        self.weights_path = weights_path or settings.detector_weights
        self._model = None

    def load(self) -> "DRDetector":
        if not self.weights_path.exists():
            raise ModelUnavailableError(
                f"Detector weights not found at {self.weights_path}. "
                "Provide a lesion-detection YOLO checkpoint or run "
                "backend/train_detector.py on IDRiD."
            )
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise ModelUnavailableError(
                "ultralytics is not installed. Install backend/requirements-ml.txt."
            ) from exc

        self._model = YOLO(str(self.weights_path))
        self.PROVENANCE = self.provenance_for(self.weights_path)
        return self

    def predict(self, image_bytes: bytes, conf: float = 0.25) -> DetectorResult:
        if self._model is None:
            raise ModelUnavailableError("Detector not loaded — call load() first.")
        import numpy as np
        from PIL import Image

        import io

        img = np.asarray(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
        results = self._model(img, verbose=False, conf=conf)
        detections: list[Detection] = []
        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0].item())
                label = LESION_LABELS.get(cls_id, f"class_{cls_id}")
                detections.append(
                    Detection(
                        label=label,
                        confidence=float(box.conf[0].item()),
                        box=[int(v) for v in box.xyxy[0].tolist()],
                    )
                )
        return DetectorResult(detections=detections)


def build_detector() -> DRDetector:
    return DRDetector().load() if DRDetector().weights_path.exists() else None