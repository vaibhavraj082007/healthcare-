"""ModelRegistry loads both engines once at app startup.

Inference endpoints go through here so Engine A/B and Phase 3 (Grad-CAM)
share the same loaded model instances instead of reloading weights.
"""

from __future__ import annotations

from typing import Optional

from .classifier import DRClassifier, ModelUnavailableError as CErr
from .detector import DRDetector, ModelUnavailableError as DErr


class ModelRegistry:
    def __init__(self) -> None:
        self.classifier: Optional[DRClassifier] = None
        self.detector: Optional[DRDetector] = None
        self.classifier_error: Optional[str] = None
        self.detector_error: Optional[str] = None

    def load(self) -> None:
        try:
            self.classifier = DRClassifier().load()
            self.classifier_error = None
        except CErr as exc:
            self.classifier = None
            self.classifier_error = str(exc)

        try:
            self.detector = DRDetector().load()
            self.detector_error = None
        except DErr as exc:
            self.detector = None
            self.detector_error = str(exc)

    def ready(self) -> bool:
        return self.classifier is not None and self.detector is not None


registry = ModelRegistry()