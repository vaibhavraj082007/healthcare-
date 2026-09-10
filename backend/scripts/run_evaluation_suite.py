"""
RetinaShield — Evaluation Suite Runner Script
==============================================
Provides:
  - create_synthetic_eval_cohort : reproducible synthetic dataset for unit testing
    and dry-run validation of the EvaluationSuite pipeline.

IMPORTANT: This module is for DEVELOPMENT and UNIT-TEST purposes only.
Never substitute synthetic cohort outputs for real held-out evaluation results.
The frozen evaluation must be run on genuine labelled data with the frozen model.
"""

from __future__ import annotations

import random
import math
from typing import Any, Dict, List

import numpy as np


# ---------------------------------------------------------------------------
# Synthetic cohort factory
# ---------------------------------------------------------------------------

def create_synthetic_eval_cohort(
    *,
    n_patients: int = 50,
    images_per_patient: int = 1,
    seed: int = 42,
    noise: float = 0.05,
    near_perfect_accuracy: bool = True,
) -> List[Dict[str, Any]]:
    """
    Generate a deterministic synthetic evaluation cohort for unit tests.

    Each record contains the fields expected by EvaluationSuite.evaluate_cohort():
      - patient_id      : str  — patient-level clustering key for bootstrap CI
      - true_grade      : int  — ICDR severity label  [0..4]
      - pred_grade      : int  — model prediction  [0..4]
      - probs           : List[float] — 5-class calibrated probability vector
      - quality         : str  — "good" | "poor" | "rejected"
      - pipeline_failed : bool
      - camera          : str  — camera model for subgroup analysis

    Parameters
    ----------
    n_patients           : number of unique patients
    images_per_patient   : retinal images per patient
    seed                 : RNG seed for reproducibility
    noise                : fraction of predictions to introduce grade-1 errors
    near_perfect_accuracy: if True, predictions are mostly correct (QWK > 0.7)

    Returns
    -------
    List of record dicts, one per image.
    """
    rng = random.Random(seed)
    np_rng = np.random.RandomState(seed)

    # DR grade prior (class frequencies loosely matching APTOS 2019 distribution)
    grade_weights = [0.49, 0.10, 0.27, 0.06, 0.08]  # No DR, Mild, Mod, Sev, PDR
    grades = list(range(5))

    records: List[Dict[str, Any]] = []

    for patient_idx in range(n_patients):
        patient_id = f"P{patient_idx:04d}"
        true_grade = rng.choices(grades, weights=grade_weights)[0]

        for img_idx in range(images_per_patient):
            # Prediction: mostly correct with configurable noise
            if near_perfect_accuracy and rng.random() > noise:
                pred_grade = true_grade
            else:
                # Off-by-one error (realistic confusions between adjacent grades)
                delta = rng.choice([-1, 1])
                pred_grade = max(0, min(4, true_grade + delta))

            # Build calibrated probability vector around pred_grade
            probs = _make_prob_vector(pred_grade, np_rng, confidence=0.85)

            # Quality: 95% good, 4% poor, 1% rejected
            q_roll = rng.random()
            if q_roll < 0.01:
                quality = "rejected"
            elif q_roll < 0.05:
                quality = "poor"
            else:
                quality = "good"

            # Camera label for subgroup analysis
            camera = rng.choice(["Canon CR-2", "Canon CR-2", "Canon CR-2", "Smartphone Adapter"])

            records.append({
                "patient_id": patient_id,
                "image_id": f"{patient_id}_E{img_idx:02d}",
                "true_grade": true_grade,
                "pred_grade": pred_grade,
                "probs": probs,
                "quality": quality,
                "pipeline_failed": False,
                "camera": camera,
                "calibration_temperature": 1.0,
            })

    return records


def _make_prob_vector(
    pred_grade: int,
    rng: np.random.RandomState,
    *,
    confidence: float = 0.85,
    n_classes: int = 5,
) -> List[float]:
    """
    Build a calibrated probability vector peaking at pred_grade.

    Parameters
    ----------
    pred_grade  : predicted class (0-4)
    rng         : numpy RandomState for reproducibility
    confidence  : probability mass assigned to pred_grade
    n_classes   : number of DR severity classes

    Returns
    -------
    List of n_classes floats summing to 1.0
    """
    remaining = 1.0 - confidence
    # Distribute remaining mass as a Dirichlet draw over adjacent classes
    alpha = np.ones(n_classes) * 0.5
    alpha[pred_grade] = 0.0  # exclude pred_grade from residual draw
    residual = rng.dirichlet(alpha + 1e-6) * remaining

    probs = residual.tolist()
    probs[pred_grade] = confidence

    # Renormalise
    total = sum(probs)
    probs = [p / total for p in probs]
    return probs
