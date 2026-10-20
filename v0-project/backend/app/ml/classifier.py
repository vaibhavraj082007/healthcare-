"""Engine B — EfficientNet-B0 ICDR severity classifier.

Loaded once at server startup by ModelRegistry. Raises ModelUnavailableError
when weights are missing so the API can respond honestly instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import settings


class ModelUnavailableError(RuntimeError):
    pass


@dataclass
class ClassifierResult:
    grade: int
    confidence: float
    class_scores: list[float]


class DRClassifier:
    """Thin wrapper around an EfficientNet-B0 with a 5-unit or 1-unit head."""

    def __init__(self, weights_path=None, device: str = "cpu"):
        self.weights_path = weights_path or settings.classifier_weights
        self.device = device
        self.ordinal = False
        self._model = None
        self._meta = {}

    def load(self) -> "DRClassifier":
        if not self.weights_path.exists():
            raise ModelUnavailableError(
                f"Classifier weights not found at {self.weights_path}. "
                "Run backend/train_classifier.py using the APTOS 2019 dataset "
                "to produce efficientnet_b0_dr.pt."
            )
        try:
            import torch
            import torch.nn as nn
            from torchvision.models import efficientnet_b0
        except ImportError as exc:
            raise ModelUnavailableError(
                "PyTorch / torchvision are not installed. "
                "Install backend/requirements-ml.txt to run inference."
            ) from exc

        state = torch.load(self.weights_path, map_location=self.device)
        self._meta = state.get("meta", {})
        out_features = state.get("out_features", 5)
        self.ordinal = out_features == 1

        model = efficientnet_b0(weights=None)
        model.classifier[1] = nn.Linear(model.classifier[1].in_features, out_features)
        model.load_state_dict(state["model_state"])
        model.eval()
        model.to(self.device)
        self._model = model
        return self

    def predict(self, tensor: np.ndarray) -> ClassifierResult:
        """tensor: CHW float32, ImageNet-normalized, shape (3, H, W)."""
        if self._model is None:
            raise ModelUnavailableError("Classifier not loaded — call load() first.")
        import torch

        with torch.no_grad():
            x = torch.from_numpy(tensor).unsqueeze(0).to(self.device)
            logits = self._model(x)
            probs = torch.softmax(logits, dim=1)

        if self.ordinal:
            # Ordinal-regression head: predict a continuous score in [0, 4],
            # round to the nearest grade.
            score = float(probs[0, 0].item() * 4.0)
            grade = int(round(max(0.0, min(4.0, score))))
            # confidence = proximity to nearest grade boundary
            diff = abs(score - grade)
            confidence = float(max(0.0, 1.0 - diff))
            scores = [round(score, 3)]
        else:
            p = probs[0].cpu().numpy()
            grade = int(np.argmax(p))
            confidence = float(p[grade])
            scores = [round(float(v), 4) for v in p]

        return ClassifierResult(grade=grade, confidence=confidence, class_scores=scores)


def build_classifier() -> DRClassifier:
    return DRClassifier().load() if DRClassifier().weights_path.exists() else None