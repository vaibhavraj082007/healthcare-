"""
RetinaShield — Confidence Calibration
======================================
Implements:
  - Numerically-stable temperature-scaled softmax (scalar and batch)
  - Log-space inverse (probs_to_logits)
  - Shannon entropy and confidence-margin uncertainty metrics
  - Expected Calibration Error (ECE) and Maximum Calibration Error (MCE)
  - scipy-free temperature optimisation via grid search + golden-section refinement
  - Calibrator class used by the dual-engine consistency layer

Calibration dataset separation
-------------------------------
This module is used ONLY on the designated **calibration split** (dev / val).
The held-out evaluation split must NEVER be touched here.
All threshold values are versioned under CALIBRATION_VERSION so that any
change forces a refit and a new version bump.

Safety note
-----------
A calibrated probability is NOT clinical certainty.
Do not replace "is_uncertain = True" with a positive diagnosis.
"""

from __future__ import annotations

import math
import logging
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np

logger = logging.getLogger(__name__)

CALIBRATION_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Uncertainty thresholds (versioned — bump CALIBRATION_VERSION on any change)
# ---------------------------------------------------------------------------
_DEFAULT_THRESHOLDS: Dict[str, float] = {
    "min_confidence": 0.50,       # max calibrated probability below this → uncertain
    "max_entropy": 0.70,          # normalised Shannon entropy above this → uncertain
    "min_margin": 0.15,           # top-2 probability gap below this → uncertain
}


# ---------------------------------------------------------------------------
# Core numerics
# ---------------------------------------------------------------------------

def softmax(logits: np.ndarray, *, temperature: float = 1.0) -> np.ndarray:
    """
    Numerically-stable temperature-scaled softmax.

    Works for 1-D (single sample) or 2-D (batch × classes) inputs.
    Temperature > 1 flattens the distribution; < 1 sharpens it.
    """
    if temperature <= 0:
        raise ValueError(f"Temperature must be > 0, got {temperature}")
    arr = np.asarray(logits, dtype=np.float64) / temperature
    if arr.ndim == 1:
        arr = arr - np.max(arr)  # numerical stability
        e = np.exp(arr)
        return e / np.sum(e)
    elif arr.ndim == 2:
        arr = arr - np.max(arr, axis=-1, keepdims=True)
        e = np.exp(arr)
        return e / np.sum(e, axis=-1, keepdims=True)
    else:
        raise ValueError("logits must be 1-D or 2-D")


def probs_to_logits(probs: np.ndarray, *, eps: float = 1e-12) -> np.ndarray:
    """
    Convert a probability vector to log-space (unnormalised logits).
    Inverse of softmax at T=1 up to an additive constant.
    """
    probs = np.asarray(probs, dtype=np.float64)
    probs = np.clip(probs, eps, 1.0 - eps)
    return np.log(probs)


# ---------------------------------------------------------------------------
# Uncertainty metrics
# ---------------------------------------------------------------------------

def compute_uncertainty_metrics(
    probs: Sequence[float],
    *,
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Compute uncertainty indicators for a single calibrated probability vector.

    Parameters
    ----------
    probs : sequence of float, length == num_classes (must sum to ~1)
    thresholds : optional override of _DEFAULT_THRESHOLDS

    Returns
    -------
    dict with keys:
        max_calibrated_probability, confidence_margin, shannon_entropy,
        is_uncertain, thresholds_used
    """
    if len(probs) == 0:
        raise ValueError("probs must be a non-empty sequence")

    p = np.asarray(probs, dtype=np.float64)
    if p.ndim != 1:
        raise ValueError("probs must be a 1-D sequence for a single sample")
    p = np.clip(p, 1e-15, 1.0)
    p = p / p.sum()  # re-normalise defensively

    thr = _DEFAULT_THRESHOLDS.copy()
    if thresholds:
        thr.update(thresholds)

    n = len(p)
    max_prob = float(np.max(p))
    sorted_p = np.sort(p)[::-1]
    margin = float(sorted_p[0] - sorted_p[1]) if n >= 2 else float(sorted_p[0])

    # Normalised Shannon entropy: H / log2(n)  ∈ [0, 1]
    raw_entropy = float(-np.sum(p * np.log2(p + 1e-15)))
    max_entropy = math.log2(n) if n > 1 else 1.0
    norm_entropy = raw_entropy / max_entropy

    is_uncertain = (
        max_prob < thr["min_confidence"]
        or norm_entropy > thr["max_entropy"]
        or margin < thr["min_margin"]
    )

    return {
        "max_calibrated_probability": max_prob,
        "confidence_margin": margin,
        "shannon_entropy": norm_entropy,
        "is_uncertain": is_uncertain,
        "thresholds_used": thr,
    }


# ---------------------------------------------------------------------------
# Calibration evaluation (ECE / MCE)
# ---------------------------------------------------------------------------

def compute_ece(
    probs: np.ndarray,
    labels: np.ndarray,
    *,
    n_bins: int = 10,
) -> Dict[str, float]:
    """
    Expected Calibration Error (ECE) and Maximum Calibration Error (MCE).

    Parameters
    ----------
    probs  : (N, C) float array of class probabilities
    labels : (N,)  int array of true class indices
    n_bins : number of confidence bins

    Returns
    -------
    dict with 'ece', 'mce', 'n_bins', 'bin_accuracies', 'bin_confidences', 'bin_counts'
    """
    probs = np.asarray(probs, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)

    confidences = np.max(probs, axis=-1)
    predictions = np.argmax(probs, axis=-1)
    correct = (predictions == labels).astype(np.float64)

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_accs, bin_confs, bin_counts = [], [], []

    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        mask = (confidences > lo) & (confidences <= hi)
        cnt = int(np.sum(mask))
        if cnt == 0:
            bin_accs.append(0.0)
            bin_confs.append(0.0)
            bin_counts.append(0)
        else:
            bin_accs.append(float(np.mean(correct[mask])))
            bin_confs.append(float(np.mean(confidences[mask])))
            bin_counts.append(cnt)

    n = len(labels)
    bin_counts_arr = np.array(bin_counts, dtype=np.float64)
    bin_gaps = np.abs(np.array(bin_accs) - np.array(bin_confs))
    ece = float(np.sum(bin_gaps * bin_counts_arr) / n)
    mce = float(np.max(bin_gaps))

    return {
        "ece": ece,
        "mce": mce,
        "n_bins": n_bins,
        "bin_accuracies": bin_accs,
        "bin_confidences": bin_confs,
        "bin_counts": bin_counts,
    }


# ---------------------------------------------------------------------------
# Temperature optimisation (calibration-split only)
# ---------------------------------------------------------------------------

def _nll_at_temperature(logits: np.ndarray, labels: np.ndarray, T: float) -> float:
    """Negative log-likelihood at temperature T."""
    p = softmax(logits, temperature=T)
    # Clip for numerical safety
    p = np.clip(p, 1e-15, 1.0)
    n = len(labels)
    nll = -np.sum(np.log(p[np.arange(n), labels])) / n
    return float(nll)


def optimize_temperature(
    logits_or_probs: np.ndarray,
    labels: np.ndarray,
    *,
    is_logits: bool = True,
    t_min: float = 0.1,
    t_max: float = 10.0,
    n_grid: int = 50,
) -> float:
    """
    Find the temperature T* that minimises NLL on the calibration split.

    Uses a coarse grid search followed by golden-section refinement.
    Requires only numpy — no scipy dependency.

    Parameters
    ----------
    logits_or_probs : (N, C) array
    labels          : (N,) integer true-class indices
    is_logits       : True if input is logits; False if probabilities (converted via log)
    t_min, t_max    : search bracket
    n_grid          : number of grid points for coarse search

    Returns
    -------
    optimal temperature as float
    """
    arr = np.asarray(logits_or_probs, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.int64)
    if not is_logits:
        arr = probs_to_logits(arr)

    # Coarse grid
    grid = np.linspace(t_min, t_max, n_grid)
    nll_vals = [_nll_at_temperature(arr, labels, float(T)) for T in grid]
    best_idx = int(np.argmin(nll_vals))

    lo = float(grid[max(0, best_idx - 1)])
    hi = float(grid[min(n_grid - 1, best_idx + 1)])

    # Golden-section refinement
    phi = (math.sqrt(5) - 1) / 2
    for _ in range(50):
        if hi - lo < 1e-6:
            break
        c = hi - phi * (hi - lo)
        d = lo + phi * (hi - lo)
        if _nll_at_temperature(arr, labels, c) < _nll_at_temperature(arr, labels, d):
            hi = d
        else:
            lo = c

    return float((lo + hi) / 2)


# ---------------------------------------------------------------------------
# Calibrator class
# ---------------------------------------------------------------------------

class Calibrator:
    """
    Wraps temperature scaling with fit / predict semantics.

    Usage
    -----
    1. fit_on_calibration_split(probs_cal, labels_cal)  — uses calibration set only
    2. calibrate_with_uncertainty(probs_single)         — at inference time

    Never call fit on the held-out evaluation set.
    """

    def __init__(
        self,
        *,
        temperature: float = 1.0,
        is_fitted: bool = False,
        thresholds: Optional[Dict[str, float]] = None,
    ):
        self.temperature = temperature
        self.is_fitted = is_fitted
        self.calibration_version = CALIBRATION_VERSION
        self._thresholds = thresholds or _DEFAULT_THRESHOLDS.copy()
        self._fit_ece: Optional[float] = None

    # ------------------------------------------------------------------
    def fit_on_calibration_split(
        self,
        probs: np.ndarray,
        labels: np.ndarray,
        *,
        is_logits: bool = False,
    ) -> Dict[str, Any]:
        """
        Fit temperature on calibration probabilities (NOT the eval set).

        Parameters
        ----------
        probs   : (N, C) float array — softmax probabilities from the classifier
        labels  : (N,) int array — ground-truth class indices
        is_logits : whether probs are raw logits

        Returns
        -------
        dict with optimal_temperature, pre_ece, post_ece, calibration_version
        """
        probs = np.asarray(probs, dtype=np.float64)
        labels = np.asarray(labels, dtype=np.int64)

        pre_ece = compute_ece(probs, labels)["ece"]

        logits = probs if is_logits else probs_to_logits(probs)
        self.temperature = optimize_temperature(logits, labels, is_logits=True)
        self.is_fitted = True

        calibrated = softmax(logits, temperature=self.temperature)
        post_ece = compute_ece(calibrated, labels)["ece"]
        self._fit_ece = post_ece

        logger.info(
            "Calibrator fitted: T=%.4f, ECE %.4f → %.4f (version %s)",
            self.temperature, pre_ece, post_ece, CALIBRATION_VERSION,
        )

        return {
            "optimal_temperature": self.temperature,
            "pre_calibration_ece": pre_ece,
            "post_calibration_ece": post_ece,
            "calibration_version": CALIBRATION_VERSION,
        }

    # ------------------------------------------------------------------
    def calibrate_with_uncertainty(
        self,
        probs: Union[Sequence[float], np.ndarray],
        *,
        is_logits: bool = False,
    ) -> Dict[str, Any]:
        """
        Apply temperature scaling and compute uncertainty metrics for a single sample.

        Parameters
        ----------
        probs     : 1-D probability (or logit) vector, length == num_classes
        is_logits : True if input is raw logits

        Returns
        -------
        dict with calibrated_probabilities, predicted_class, is_uncertain,
        shannon_entropy, confidence_margin, max_calibrated_probability,
        calibration_status, calibration_version
        """
        arr = np.asarray(probs, dtype=np.float64)
        if arr.ndim != 1:
            raise ValueError("calibrate_with_uncertainty expects a 1-D vector")

        if not is_logits:
            arr = probs_to_logits(arr)

        calibrated = softmax(arr, temperature=self.temperature)
        uncertainty = compute_uncertainty_metrics(calibrated, thresholds=self._thresholds)

        calibration_status = "fitted" if self.is_fitted else "unfitted_T=1"

        return {
            "calibrated_probabilities": calibrated.tolist(),
            "predicted_class": int(np.argmax(calibrated)),
            "is_uncertain": uncertainty["is_uncertain"],
            "shannon_entropy": uncertainty["shannon_entropy"],
            "confidence_margin": uncertainty["confidence_margin"],
            "max_calibrated_probability": uncertainty["max_calibrated_probability"],
            "calibration_status": calibration_status,
            "calibration_version": self.calibration_version,
            "thresholds_used": uncertainty["thresholds_used"],
        }
