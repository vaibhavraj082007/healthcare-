"""
RetinaShield — Unit & Integration Tests for Confidence Calibration & Consistency Layer
(Rule-version: 1.0.0 — tests cover every decision branch)

Test Groups:
  1. Temperature Scaling + Uncertainty Metrics (calibrate_probabilities.py)
  2. Safety Invariants (consistency_service.py)
     A. Concordant label is 'Concordant AI findings', never 'Confirmed diagnosis'
     B. Classifier High (Grade >= 2) + 0 lesions -> NEVER downgrade severity/urgency
     C. Classifier Low  (Grade 0)  + hallmark lesions -> ESCALATE to higher grade
     D. Grade 1 + severe focal lesions (NV/multiple HE) -> ESCALATE
  3. Quality Gate — rejected image refuses autonomous grading
  4. Component Gate — untrained classifier -> component_unavailable
  5. Uncertainty Gate — high entropy/low margin -> uncertain_prediction + human review
  6. Macula Involvement — exudate near fovea escalates referral urgency to urgent
  7. Rules Version — consistency_status.rules_version must equal CONSISTENCY_RULES_VERSION
"""

from __future__ import annotations

import math
import unittest

import numpy as np

# ---------------------------------------------------------------------------
# calibrate_probabilities helpers under test
# ---------------------------------------------------------------------------
from scripts.calibrate_probabilities import (
    CALIBRATION_VERSION,
    Calibrator,
    compute_ece,
    compute_uncertainty_metrics,
    optimize_temperature,
    probs_to_logits,
    softmax,
)

# ---------------------------------------------------------------------------
# consistency_service under test
# ---------------------------------------------------------------------------
from app.services.consistency_service import (
    CONSISTENCY_RULES_VERSION,
    ConsistencyEvaluator,
)


# ---------------------------------------------------------------------------
# Helper factories to build minimal input dicts
# ---------------------------------------------------------------------------

def _severity(grade: int, *, trained: bool = True, grade_label: str = "") -> dict:
    return {
        "predicted_grade": grade,
        "grade_label": grade_label or ["No DR", "Mild", "Moderate", "Severe", "PDR"][grade],
        "model_trained": trained,
        "confidence": 0.85,
    }


def _lesions(
    *,
    trained: bool = True,
    detections: list | None = None,
    counts: dict | None = None,
    status: str = "baseline_heuristic",
) -> dict:
    return {
        "model_trained": trained,
        "status": status,
        "detections": detections if detections is not None else [],
        "model_estimated_count": counts if counts is not None else {},
    }


def _cal(
    *,
    uncertain: bool = False,
    entropy: float = 0.2,
    margin: float = 0.7,
    max_prob: float = 0.85,
) -> dict:
    return {
        "is_uncertain": uncertain,
        "shannon_entropy": entropy,
        "confidence_margin": margin,
        "max_calibrated_probability": max_prob,
    }


def _iqa(quality: str = "good") -> dict:
    return {"overall_quality": quality}


def _struct_fovea(cx: float, cy: float, r: float = 30.0) -> dict:
    return {"fovea": {"detected": True, "center_x": cx, "center_y": cy, "radius": r}}


def _lesion_bbox(lesion_type: str, x: float, y: float, w: float = 20.0) -> dict:
    return {
        "lesion_type": lesion_type,
        "confidence": 0.82,
        "bbox": {"x_min": x, "y_min": y, "x_max": x + w, "y_max": y + w},
    }


# ===========================================================================
# 1. Temperature Scaling & Uncertainty Metrics
# ===========================================================================

class TestTemperatureScaling(unittest.TestCase):
    """Temperature-scaled softmax behaves correctly."""

    def test_softmax_sums_to_one(self):
        for T in [0.5, 1.0, 2.0, 5.0]:
            logits = np.array([3.0, 1.5, -0.5, -1.0, -2.0])
            p = softmax(logits, temperature=T)
            self.assertAlmostEqual(float(np.sum(p)), 1.0, places=5,
                                   msg=f"Sum != 1 for T={T}")

    def test_warmer_temperature_flattens_distribution(self):
        logits = np.array([4.0, 1.0, 0.0, -1.0, -2.0])
        p1 = softmax(logits, temperature=1.0)
        p2 = softmax(logits, temperature=3.0)
        self.assertLess(float(np.max(p2)), float(np.max(p1)),
                        "Warmer T should give lower max probability")

    def test_probs_to_logits_roundtrip(self):
        original = np.array([0.7, 0.1, 0.1, 0.05, 0.05])
        logits = probs_to_logits(original)
        recovered = softmax(logits, temperature=1.0)
        np.testing.assert_allclose(recovered, original, atol=1e-4)

    def test_batch_softmax_shape_preserved(self):
        logits_batch = np.random.randn(8, 5)
        p_batch = softmax(logits_batch, temperature=1.5)
        self.assertEqual(p_batch.shape, (8, 5))
        np.testing.assert_allclose(np.sum(p_batch, axis=-1), 1.0, atol=1e-5)


class TestUncertaintyMetrics(unittest.TestCase):
    """Uncertainty metrics correctly differentiate confident vs ambiguous outputs."""

    def test_confident_distribution(self):
        probs = [0.90, 0.05, 0.03, 0.01, 0.01]
        m = compute_uncertainty_metrics(probs)
        self.assertAlmostEqual(m["max_calibrated_probability"], 0.90, places=2)
        self.assertAlmostEqual(m["confidence_margin"], 0.85, places=2)
        self.assertLess(m["shannon_entropy"], 0.50)
        self.assertFalse(m["is_uncertain"])

    def test_uniform_distribution_is_maximally_uncertain(self):
        probs = [0.2, 0.2, 0.2, 0.2, 0.2]
        m = compute_uncertainty_metrics(probs)
        self.assertAlmostEqual(m["shannon_entropy"], 1.0, places=2)
        self.assertTrue(m["is_uncertain"])

    def test_low_margin_triggers_uncertain(self):
        # Top-2 very close together -> small margin
        probs = [0.35, 0.33, 0.17, 0.10, 0.05]
        m = compute_uncertainty_metrics(probs)
        self.assertLess(m["confidence_margin"], 0.15)
        self.assertTrue(m["is_uncertain"])

    def test_invalid_input_raises(self):
        with self.assertRaises((ValueError, Exception)):
            compute_uncertainty_metrics([])

    def test_thresholds_exposed_in_output(self):
        m = compute_uncertainty_metrics([0.9, 0.05, 0.03, 0.01, 0.01])
        self.assertIn("thresholds_used", m)
        self.assertIn("min_confidence", m["thresholds_used"])


class TestCalibrationErrors(unittest.TestCase):
    """ECE/MCE computations return bounded values."""

    def test_ece_mce_range(self):
        probs = np.array([
            [0.9, 0.05, 0.03, 0.01, 0.01],
            [0.1, 0.80, 0.05, 0.03, 0.02],
            [0.02, 0.05, 0.80, 0.10, 0.03],
        ])
        labels = np.array([0, 1, 2])
        result = compute_ece(probs, labels, n_bins=5)
        self.assertIn("ece", result)
        self.assertIn("mce", result)
        self.assertGreaterEqual(result["ece"], 0.0)
        self.assertLessEqual(result["ece"], 1.0)
        self.assertGreaterEqual(result["mce"], 0.0)
        self.assertLessEqual(result["mce"], 1.0)


class TestTemperatureOptimization(unittest.TestCase):
    """Temperature optimizer returns a sensible float."""

    def test_optimize_returns_positive_float(self):
        logits = np.array([
            [5.0, 0.5, 0.0, -0.5, -1.0],
            [0.0, 4.0, 0.5, -0.5, -1.0],
            [-1.0, 0.0, 4.0, 0.5, -0.5],
        ])
        labels = np.array([0, 1, 2])
        t = optimize_temperature(logits, labels, is_logits=True)
        self.assertIsInstance(t, float)
        self.assertGreaterEqual(t, 0.1)
        self.assertLess(t, 10.0)

    def test_calibrator_fit_tracks_temperature(self):
        probs = np.array([
            [0.9, 0.05, 0.03, 0.01, 0.01],
            [0.1, 0.80, 0.05, 0.03, 0.02],
            [0.02, 0.05, 0.80, 0.10, 0.03],
        ])
        labels = np.array([0, 1, 2])
        cal = Calibrator()
        result = cal.fit_on_calibration_split(probs, labels)
        self.assertIn("optimal_temperature", result)
        self.assertTrue(cal.is_fitted)
        self.assertGreater(cal.temperature, 0.0)

    def test_calibrator_uncertainty_dict(self):
        cal = Calibrator(temperature=1.0, is_fitted=True)
        out = cal.calibrate_with_uncertainty([0.85, 0.05, 0.05, 0.03, 0.02])
        self.assertIn("calibrated_probabilities", out)
        self.assertIn("is_uncertain", out)
        self.assertIn("shannon_entropy", out)
        self.assertEqual(len(out["calibrated_probabilities"]), 5)


# ===========================================================================
# 2A. Safety Invariant — Concordant label
# ===========================================================================

class TestConcordantLabel(unittest.TestCase):
    """Result must say 'Concordant AI findings', never 'Confirmed diagnosis'."""

    def test_no_dr_concordant_label(self):
        ev = ConsistencyEvaluator()
        consistency, referral = ev.evaluate(
            _severity(0), _lesions(), _cal(), _iqa()
        )
        self.assertEqual(consistency.consistency_status, "concordant")
        self.assertEqual(consistency.finding_label, "Concordant AI findings")
        self.assertNotIn("Confirmed diagnosis", consistency.finding_label)
        self.assertNotIn("Confirmed diagnosis", referral.reason)
        self.assertFalse(consistency.human_review_required)
        self.assertEqual(referral.urgency, "none")

    def test_mild_dr_concordant_label(self):
        ev = ConsistencyEvaluator()
        detections = [_lesion_bbox("microaneurysm", 200, 200)]
        consistency, referral = ev.evaluate(
            _severity(1), _lesions(detections=detections, counts={"microaneurysm": 1}),
            _cal(), _iqa()
        )
        self.assertNotIn("Confirmed diagnosis", consistency.finding_label)
        self.assertNotIn("Confirmed diagnosis", referral.reason)

    def test_rules_version_present(self):
        ev = ConsistencyEvaluator()
        consistency, _ = ev.evaluate(_severity(0), _lesions(), _cal(), _iqa())
        self.assertEqual(consistency.rules_version, CONSISTENCY_RULES_VERSION)


# ===========================================================================
# 2B. Safety Invariant — Downgrade Prevention
# ===========================================================================

class TestDowngradePrevention(unittest.TestCase):
    """Classifier high + 0 lesions must NEVER reduce grade or referral urgency."""

    def _assert_not_downgraded(self, grade: int, expected_urgency: str):
        ev = ConsistencyEvaluator()
        consistency, referral = ev.evaluate(
            _severity(grade), _lesions(), _cal(), _iqa()
        )
        self.assertEqual(consistency.consistency_status, "discordant_classifier_high",
                         f"Grade {grade}: expected discordant_classifier_high")
        self.assertEqual(consistency.recommended_grade, grade,
                         f"Grade {grade} must not be downgraded to 0")
        self.assertNotEqual(consistency.recommended_grade, 0,
                            "Grade must not be silently reset to 0")
        self.assertIn(expected_urgency, referral.urgency)
        self.assertTrue(consistency.human_review_required)
        self.assertTrue(any("conservatively retained" in r for r in consistency.review_reasons))

    def test_grade_2_moderate_retained(self):
        self._assert_not_downgraded(2, "priority")

    def test_grade_3_severe_retained(self):
        self._assert_not_downgraded(3, "priority")

    def test_grade_4_pdr_retained(self):
        ev = ConsistencyEvaluator()
        consistency, referral = ev.evaluate(
            _severity(4), _lesions(), _cal(), _iqa()
        )
        self.assertEqual(consistency.recommended_grade, 4)
        self.assertEqual(referral.urgency, "urgent")
        self.assertTrue(consistency.human_review_required)


# ===========================================================================
# 2C. Safety Invariant — Escalation (Classifier Low, Hallmark Lesions)
# ===========================================================================

class TestEscalationRules(unittest.TestCase):
    """Classifier Grade 0 + hallmark lesions must ESCALATE grade and urgency."""

    def test_neovascularization_escalates_to_pdr(self):
        ev = ConsistencyEvaluator()
        consistency, referral = ev.evaluate(
            _severity(0),
            _lesions(
                detections=[_lesion_bbox("neovascularization", 300, 300)],
                counts={"neovascularization": 1}
            ),
            _cal(), _iqa()
        )
        self.assertEqual(consistency.consistency_status, "discordant_lesions_high")
        self.assertEqual(consistency.recommended_grade, 4,
                         "NV must escalate to Grade 4 (PDR)")
        self.assertEqual(referral.urgency, "urgent")
        self.assertTrue(consistency.human_review_required)

    def test_multiple_hemorrhages_escalates(self):
        ev = ConsistencyEvaluator()
        detections = [_lesion_bbox("hemorrhage", 100 * i, 100 * i) for i in range(3)]
        consistency, referral = ev.evaluate(
            _severity(0),
            _lesions(detections=detections, counts={"hemorrhage": 3}),
            _cal(), _iqa()
        )
        self.assertEqual(consistency.consistency_status, "discordant_lesions_high")
        self.assertGreaterEqual(consistency.recommended_grade, 2)
        self.assertTrue(consistency.human_review_required)

    def test_multiple_hard_exudates_escalates(self):
        ev = ConsistencyEvaluator()
        detections = [_lesion_bbox("hard_exudate", 50 * i, 50 * i) for i in range(3)]
        consistency, referral = ev.evaluate(
            _severity(0),
            _lesions(detections=detections, counts={"hard_exudate": 3}),
            _cal(), _iqa()
        )
        self.assertEqual(consistency.consistency_status, "discordant_lesions_high")
        self.assertGreaterEqual(consistency.recommended_grade, 2)


# ===========================================================================
# 2D. Grade 1 + Severe Focal Lesions -> ESCALATE
# ===========================================================================

class TestGrade1Escalation(unittest.TestCase):

    def test_grade_1_neovascularization_escalates(self):
        ev = ConsistencyEvaluator()
        consistency, referral = ev.evaluate(
            _severity(1),
            _lesions(
                detections=[_lesion_bbox("neovascularization", 400, 300)],
                counts={"neovascularization": 1}
            ),
            _cal(), _iqa()
        )
        self.assertEqual(consistency.consistency_status, "discordant_lesions_high")
        self.assertEqual(consistency.recommended_grade, 4)
        self.assertEqual(referral.urgency, "urgent")

    def test_grade_1_four_hemorrhages_escalates(self):
        ev = ConsistencyEvaluator()
        detections = [_lesion_bbox("hemorrhage", 80 * i, 80 * i) for i in range(5)]
        consistency, referral = ev.evaluate(
            _severity(1),
            _lesions(detections=detections, counts={"hemorrhage": 5}),
            _cal(), _iqa()
        )
        self.assertEqual(consistency.consistency_status, "discordant_lesions_high")
        self.assertGreaterEqual(consistency.recommended_grade, 3)


# ===========================================================================
# 3. Image Quality Gate
# ===========================================================================

class TestImageQualityGate(unittest.TestCase):

    def test_rejected_image_refuses_grading(self):
        ev = ConsistencyEvaluator()
        consistency, referral = ev.evaluate(
            _severity(0), _lesions(), _cal(), _iqa("rejected")
        )
        self.assertEqual(consistency.consistency_status, "quality_compromised")
        self.assertIsNone(consistency.recommended_grade)
        self.assertTrue(consistency.human_review_required)
        # Finding label must signal ungradeability
        label_lower = consistency.finding_label.lower()
        self.assertTrue("ungradeable" in label_lower or "refused" in label_lower,
                        f"Unexpected label: {consistency.finding_label}")
        # Referral reason must mention ungradeable or repeat
        reason_lower = referral.reason.lower()
        self.assertTrue("ungradeable" in reason_lower or "repeat" in reason_lower,
                        f"Unexpected reason: {referral.reason}")

    def test_poor_image_triggers_human_review_but_not_rejected(self):
        ev = ConsistencyEvaluator()
        consistency, _ = ev.evaluate(
            _severity(0), _lesions(), _cal(), _iqa("poor")
        )
        # poor quality should flag review but not refuse grading outright
        self.assertTrue(consistency.human_review_required)
        self.assertNotEqual(consistency.consistency_status, "quality_compromised")


# ===========================================================================
# 4. Component Availability Gate
# ===========================================================================

class TestComponentAvailabilityGate(unittest.TestCase):

    def test_untrained_classifier_triggers_unavailable(self):
        ev = ConsistencyEvaluator()
        consistency, referral = ev.evaluate(
            # grade -1 signals invalid/unknown prediction
            {"predicted_grade": -1, "model_trained": False},
            _lesions(trained=False, status="unavailable"),
            _cal(), _iqa()
        )
        self.assertEqual(consistency.consistency_status, "component_unavailable")
        self.assertIsNone(consistency.recommended_grade)
        self.assertTrue(consistency.human_review_required)

    def test_missing_classifier_weights_flags_reason(self):
        ev = ConsistencyEvaluator()
        consistency, _ = ev.evaluate(
            {"predicted_grade": 0, "model_trained": False},
            _lesions(), _cal(), _iqa()
        )
        self.assertTrue(consistency.human_review_required)
        self.assertTrue(any("Classifier" in r or "classifier" in r
                             for r in consistency.review_reasons))

    def test_missing_lesion_weights_flags_reason(self):
        ev = ConsistencyEvaluator()
        consistency, _ = ev.evaluate(
            _severity(0),
            _lesions(trained=False, status="unavailable"),
            _cal(), _iqa()
        )
        self.assertTrue(consistency.human_review_required)
        self.assertTrue(any("lesion" in r.lower() or "Lesion" in r
                             for r in consistency.review_reasons))


# ===========================================================================
# 5. Predictive Uncertainty Gate
# ===========================================================================

class TestUncertaintyGate(unittest.TestCase):

    def test_high_entropy_triggers_uncertain_status(self):
        ev = ConsistencyEvaluator()
        consistency, _ = ev.evaluate(
            _severity(1),
            _lesions(),
            _cal(uncertain=True, entropy=0.88, margin=0.04, max_prob=0.31),
            _iqa()
        )
        self.assertEqual(consistency.consistency_status, "uncertain_prediction")
        self.assertTrue(consistency.human_review_required)
        self.assertTrue(any("uncertainty" in r.lower() for r in consistency.review_reasons))

    def test_confident_prediction_no_uncertainty_flag(self):
        ev = ConsistencyEvaluator()
        consistency, _ = ev.evaluate(
            _severity(0),
            _lesions(),
            _cal(uncertain=False, entropy=0.05, margin=0.88, max_prob=0.92),
            _iqa()
        )
        self.assertEqual(consistency.consistency_status, "concordant")
        self.assertFalse(consistency.human_review_required)


# ===========================================================================
# 6. Macula Involvement — Referral Escalation
# ===========================================================================

class TestMaculaInvolvement(unittest.TestCase):

    def test_exudate_near_fovea_escalates_to_urgent(self):
        ev = ConsistencyEvaluator()
        fovea_cx, fovea_cy, fovea_r = 512.0, 512.0, 30.0
        # Place exudate within 2*r of fovea center
        ex_x = fovea_cx + fovea_r  # Just inside zone
        consistency, referral = ev.evaluate(
            _severity(2),
            _lesions(
                detections=[_lesion_bbox("hard_exudate", ex_x - 10, fovea_cy - 10, w=20)],
                counts={"hard_exudate": 1}
            ),
            _cal(), _iqa(),
            _struct_fovea(fovea_cx, fovea_cy, fovea_r)
        )
        self.assertEqual(referral.urgency, "urgent",
                         "Macular exudate must escalate referral urgency to urgent")
        self.assertIn("Macular involvement", referral.reason)

    def test_exudate_far_from_fovea_no_macula_escalation(self):
        ev = ConsistencyEvaluator()
        fovea_cx, fovea_cy, fovea_r = 512.0, 512.0, 30.0
        # Place exudate far from fovea (5+ disc diameters away)
        consistency, referral = ev.evaluate(
            _severity(2),
            _lesions(
                detections=[_lesion_bbox("hard_exudate", 50, 50, w=20)],
                counts={"hard_exudate": 1}
            ),
            _cal(), _iqa(),
            _struct_fovea(fovea_cx, fovea_cy, fovea_r)
        )
        # Grade 2 without macular involvement should be priority, not urgent
        self.assertIn(referral.urgency, ["priority"])


# ===========================================================================
# 7. Referral Urgency Mapping
# ===========================================================================

class TestReferralUrgency(unittest.TestCase):
    """Verify each ICDR grade maps to the correct referral tier."""

    def _get_referral(self, grade: int) -> str:
        ev = ConsistencyEvaluator()
        # Provide just enough lesions to avoid triggering discordance for Grade>=2
        detections = [_lesion_bbox("hemorrhage", 100, 100)] * max(1, grade)
        counts = {"hemorrhage": max(1, grade)}
        _, referral = ev.evaluate(
            _severity(grade),
            _lesions(detections=detections, counts=counts),
            _cal(), _iqa()
        )
        return referral.urgency

    def test_grade_0_no_urgency(self):
        ev = ConsistencyEvaluator()
        _, referral = ev.evaluate(_severity(0), _lesions(), _cal(), _iqa())
        self.assertEqual(referral.urgency, "none")

    def test_grade_1_routine(self):
        ev = ConsistencyEvaluator()
        _, referral = ev.evaluate(
            _severity(1),
            _lesions(detections=[_lesion_bbox("microaneurysm", 100, 100)],
                     counts={"microaneurysm": 1}),
            _cal(), _iqa()
        )
        self.assertEqual(referral.urgency, "routine")

    def test_grade_4_urgent(self):
        ev = ConsistencyEvaluator()
        _, referral = ev.evaluate(
            _severity(4),
            _lesions(
                detections=[_lesion_bbox("neovascularization", 200, 200)],
                counts={"neovascularization": 1}
            ),
            _cal(), _iqa()
        )
        self.assertEqual(referral.urgency, "urgent")


if __name__ == "__main__":
    unittest.main()
