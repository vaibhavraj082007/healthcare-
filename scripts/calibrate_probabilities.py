#!/usr/bin/env python3
"""
RetinaShield — Confidence Calibration & Uncertainty Estimation Module

Uses designated calibration subsets (e.g. calibration_manifest.csv) exclusively.
Prevents hyperparameter tuning and evaluation data leakage.

Features:
  - Post-hoc Temperature Scaling (Guo et al., 2017)
  - Expected Calibration Error (ECE) & Maximum Calibration Error (MCE)
  - Multi-metric Uncertainty: Max calibrated probability, margin of confidence, Shannon entropy
  - Uncertainty flagging when confidence is low or class separation is ambiguous
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

CALIBRATION_VERSION = "1.0.0"
CONFIDENCE_THRESHOLD_DEFAULT = 0.65
MARGIN_THRESHOLD_DEFAULT = 0.15
ENTROPY_THRESHOLD_DEFAULT = 0.60


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    """Compute temperature-scaled softmax over 1D or 2D array of logits."""
    t = max(1e-4, float(temperature))
    scaled = logits / t
    if scaled.ndim == 1:
        e_x = np.exp(scaled - np.max(scaled))
        return e_x / np.sum(e_x)
    else:
        e_x = np.exp(scaled - np.max(scaled, axis=-1, keepdims=True))
        return e_x / np.sum(e_x, axis=-1, keepdims=True)


def probs_to_logits(probs: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Convert softmax probabilities to pseudo-logits via log transform."""
    clamped = np.clip(probs, eps, 1.0 - eps)
    return np.log(clamped)


def compute_uncertainty_metrics(
    calibrated_probs: np.ndarray | List[float],
    conf_thresh: float = CONFIDENCE_THRESHOLD_DEFAULT,
    margin_thresh: float = MARGIN_THRESHOLD_DEFAULT,
    entropy_thresh: float = ENTROPY_THRESHOLD_DEFAULT,
) -> Dict[str, Any]:
    """
    Compute comprehensive uncertainty metrics beyond raw softmax:
      - max_calibrated_probability: Confidence of top predicted grade
      - confidence_margin: Difference between top-1 and top-2 class probabilities
      - shannon_entropy: Normalized Shannon entropy in [0, 1]
      - is_uncertain: Flag raised if confidence < threshold, margin < threshold, or entropy > threshold
    """
    p = np.asarray(calibrated_probs, dtype=float)
    if p.ndim != 1 or len(p) == 0:
        raise ValueError("Probabilities must be a 1D non-empty array")

    p = np.clip(p, 1e-12, 1.0)
    p = p / np.sum(p)  # Ensure exact normalization

    sorted_p = np.sort(p)[::-1]
    max_prob = float(sorted_p[0])
    second_prob = float(sorted_p[1]) if len(sorted_p) > 1 else 0.0
    margin = float(max_prob - second_prob)

    num_classes = len(p)
    raw_entropy = -np.sum(p * np.log(p))
    max_entropy = math.log(num_classes) if num_classes > 1 else 1.0
    norm_entropy = float(raw_entropy / max_entropy) if max_entropy > 0 else 0.0

    is_uncertain = (
        max_prob < conf_thresh or
        margin < margin_thresh or
        norm_entropy > entropy_thresh
    )

    return {
        "max_calibrated_probability": round(max_prob, 4),
        "confidence_margin": round(margin, 4),
        "shannon_entropy": round(norm_entropy, 4),
        "is_uncertain": bool(is_uncertain),
        "thresholds_used": {
            "min_confidence": conf_thresh,
            "min_margin": margin_thresh,
            "max_entropy": entropy_thresh,
        },
    }


def compute_ece(probs: np.ndarray, labels: np.ndarray, n_bins: int = 10) -> Dict[str, float]:
    """
    Compute Expected Calibration Error (ECE) and Maximum Calibration Error (MCE).
    """
    preds = np.argmax(probs, axis=1)
    confs = np.max(probs, axis=1)
    accuracies = (preds == labels).astype(float)

    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    mce = 0.0
    n_samples = len(labels)

    for i in range(n_bins):
        bin_lower = bin_boundaries[i]
        bin_upper = bin_boundaries[i + 1]

        in_bin = (confs > bin_lower) & (confs <= bin_upper) if i > 0 else (confs >= bin_lower) & (confs <= bin_upper)
        prop_in_bin = np.mean(in_bin.astype(float))

        if prop_in_bin > 0:
            accuracy_in_bin = np.mean(accuracies[in_bin])
            avg_confidence_in_bin = np.mean(confs[in_bin])
            diff = abs(avg_confidence_in_bin - accuracy_in_bin)
            ece += diff * (np.sum(in_bin) / n_samples)
            mce = max(mce, diff)

    # Brier score
    one_hot = np.zeros_like(probs)
    for idx, l in enumerate(labels):
        one_hot[idx, int(l)] = 1.0
    brier_score = float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))

    return {
        "ece": round(float(ece), 4),
        "mce": round(float(mce), 4),
        "brier_score": round(brier_score, 4),
    }


def optimize_temperature(
    logits_or_probs: np.ndarray,
    labels: np.ndarray,
    is_logits: bool = True,
) -> float:
    """
    Optimize scalar temperature T by minimizing Cross-Entropy / NLL on calibration data.
    Uses grid search + golden section refinement.
    """
    logits = logits_or_probs if is_logits else probs_to_logits(logits_or_probs)
    labels = np.asarray(labels, dtype=int)

    def nll_loss(temp: float) -> float:
        p = softmax(logits, temperature=temp)
        eps = 1e-12
        loss = 0.0
        for idx, lbl in enumerate(labels):
            loss -= math.log(max(eps, p[idx, lbl]))
        return loss / len(labels)

    # Search in range T in [0.2, 5.0]
    best_t = 1.0
    best_loss = float("inf")

    candidates = np.linspace(0.2, 5.0, 49)
    for cand in candidates:
        loss = nll_loss(cand)
        if loss < best_loss:
            best_loss = loss
            best_t = cand

    # Refine around best_t
    refined_cands = np.linspace(max(0.1, best_t - 0.2), best_t + 0.2, 41)
    for cand in refined_cands:
        loss = nll_loss(cand)
        if loss < best_loss:
            best_loss = loss
            best_t = cand

    return round(float(best_t), 3)


class Calibrator:
    """Stateful confidence calibrator tracking temperature and metrics."""

    def __init__(self, temperature: float = 1.0, is_fitted: bool = False):
        self.temperature = float(temperature)
        self.is_fitted = is_fitted
        self.calibration_version = CALIBRATION_VERSION

    def fit_on_calibration_split(
        self,
        calibration_probs: np.ndarray,
        calibration_labels: np.ndarray,
    ) -> Dict[str, Any]:
        """Fit optimal temperature on designated calibration set."""
        uncalibrated_metrics = compute_ece(calibration_probs, calibration_labels)
        opt_t = optimize_temperature(calibration_probs, calibration_labels, is_logits=False)
        self.temperature = opt_t
        self.is_fitted = True

        calibrated_probs = self.calibrate(calibration_probs)
        calibrated_metrics = compute_ece(calibrated_probs, calibration_labels)

        return {
            "calibration_version": self.calibration_version,
            "optimal_temperature": self.temperature,
            "uncalibrated_metrics": uncalibrated_metrics,
            "calibrated_metrics": calibrated_metrics,
            "samples_calibrated": len(calibration_labels),
        }

    def calibrate(self, raw_probs: np.ndarray | List[float]) -> np.ndarray:
        """Apply temperature scaling to raw softmax probabilities."""
        p = np.asarray(raw_probs, dtype=float)
        logits = probs_to_logits(p)
        return softmax(logits, temperature=self.temperature)

    def calibrate_with_uncertainty(self, raw_probs: np.ndarray | List[float]) -> Dict[str, Any]:
        """Produce calibrated probabilities and full uncertainty metadata."""
        cal_p = self.calibrate(raw_probs)
        unc = compute_uncertainty_metrics(cal_p)
        status = "calibrated" if self.is_fitted else "uncalibrated_raw_softmax"

        return {
            "status": status,
            "temperature": self.temperature if self.is_fitted else None,
            "calibrated_probabilities": [round(float(x), 4) for x in cal_p],
            "max_calibrated_probability": unc["max_calibrated_probability"],
            "confidence_margin": unc["confidence_margin"],
            "shannon_entropy": unc["shannon_entropy"],
            "is_uncertain": unc["is_uncertain"],
        }
