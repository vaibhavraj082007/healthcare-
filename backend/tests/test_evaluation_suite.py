"""
RetinaShield — Evaluation Suite Unit Tests

Tests:
  - Confusion matrix & Quadratic Weighted Kappa (QWK)
  - Macro-F1, Balanced Accuracy, Per-Class Sensitivity/Specificity
  - Clinical Screening Endpoints (Referable DR & Sight-Threatening DR, AUROC, AUPR)
  - Probability Calibration (ECE, MCE, Brier Score, NLL)
  - Patient-level cluster bootstrap resampling for 95% Confidence Intervals
  - Prespecified frozen ablation studies
  - Camera subgroup sample size gating (honestly reports N < 20)
  - EvaluationReport Pydantic schema validation & serialization
"""

import unittest
import numpy as np

from app.schemas.evaluation import EvaluationReport
from app.services.evaluation_service import (
    compute_confusion_matrix,
    compute_quadratic_weighted_kappa,
    compute_per_class_metrics,
    compute_auroc_and_aupr,
    compute_endpoint_metrics,
    compute_calibration_details,
    run_patient_cluster_bootstrap,
    evaluate_prespecified_ablations,
    evaluate_camera_subgroups,
    evaluate_degradations,
    EvaluationSuite,
)


class TestEvaluationMetrics(unittest.TestCase):
    """Test suite for statistical and clinical metrics in evaluation_service."""

    def test_confusion_matrix_and_perfect_qwk(self):
        """Identical predictions yield diagonal confusion matrix and kappa = 1.0."""
        y_true = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
        y_pred = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]

        mat = compute_confusion_matrix(y_true, y_pred, num_classes=5)
        self.assertEqual(mat.shape, (5, 5))
        self.assertEqual(np.trace(mat), 10)
        self.assertEqual(np.sum(mat), 10)

        qwk = compute_quadratic_weighted_kappa(y_true, y_pred, num_classes=5)
        self.assertAlmostEqual(qwk, 1.0, places=4)

    def test_qwk_quadratic_penalty(self):
        """Predictions off by 4 grades receive much harsher penalty than off by 1."""
        y_true = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
        # Off by 1 (Mild distance)
        y_off_1 = [1, 2, 3, 4, 3, 1, 2, 3, 4, 3]
        qwk_off_1 = compute_quadratic_weighted_kappa(y_true, y_off_1, num_classes=5)

        # Off by 3-4 (Severe distance)
        y_off_4 = [4, 4, 0, 0, 0, 4, 4, 0, 0, 0]
        qwk_off_4 = compute_quadratic_weighted_kappa(y_true, y_off_4, num_classes=5)

        # Harsher penalty means lower kappa score
        self.assertLess(qwk_off_4, qwk_off_1)

    def test_per_class_metrics_and_macro_f1(self):
        """Verifies Precision, Recall, Specificity, F1, and Macro-averages."""
        # 2 samples per class, one misclassification in class 1
        y_true = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
        y_pred = [0, 0, 1, 2, 2, 2, 3, 3, 4, 4]  # one 1 predicted as 2

        mat = compute_confusion_matrix(y_true, y_pred, num_classes=5)
        per_class, macro_f1, bal_acc = compute_per_class_metrics(mat, num_classes=5)

        self.assertEqual(len(per_class), 5)
        self.assertEqual(per_class[0].f1_score, 1.0)
        self.assertEqual(per_class[0].support, 2)
        # Class 1 recall is 1/2 = 0.5
        self.assertEqual(per_class[1].recall, 0.5)
        self.assertGreater(macro_f1, 0.7)
        self.assertGreater(bal_acc, 0.7)

    def test_screening_endpoint_rdr(self):
        """Tests Referable DR (rDR: Grade >= 2) binary screening metrics."""
        y_true = np.array([0, 1, 2, 3, 4])
        # Probabilities with high confidence on true classes
        probs = np.zeros((5, 5))
        for i in range(5):
            probs[i, i] = 0.95
            probs[i, (i + 1) % 5] = 0.05

        endpoint = compute_endpoint_metrics(
            y_true=y_true,
            probs=probs,
            threshold_grade=2,
            endpoint_name="Referable DR (Grade >= 2)",
        )

        self.assertEqual(endpoint.support_positive, 3)  # Grades 2, 3, 4
        self.assertEqual(endpoint.support_negative, 2)  # Grades 0, 1
        self.assertEqual(endpoint.sensitivity.value, 1.0)
        self.assertEqual(endpoint.specificity.value, 1.0)
        self.assertAlmostEqual(endpoint.auroc.value, 1.0, places=3)
        self.assertAlmostEqual(endpoint.aupr, 1.0, places=3)

    def test_probability_calibration_metrics(self):
        """Tests ECE, MCE, and Brier Score calculations."""
        y_true = np.array([0, 1, 2, 3, 4])
        # Perfect probabilities: prob = 1.0 on true class
        probs_perfect = np.zeros((5, 5))
        for i in range(5):
            probs_perfect[i, i] = 1.0

        cal_perfect = compute_calibration_details(y_true, probs_perfect, num_bins=5)
        self.assertEqual(cal_perfect.ece.value, 0.0)
        self.assertEqual(cal_perfect.mce, 0.0)
        self.assertEqual(cal_perfect.brier_score, 0.0)
        self.assertAlmostEqual(cal_perfect.negative_log_likelihood, 0.0, places=3)

        # Overconfident erroneous probabilities
        probs_wrong = np.zeros((5, 5))
        for i in range(5):
            probs_wrong[i, (i + 1) % 5] = 1.0  # completely confident and wrong

        cal_wrong = compute_calibration_details(y_true, probs_wrong, num_bins=5)
        self.assertGreater(cal_wrong.ece.value, 0.5)
        self.assertGreater(cal_wrong.brier_score, 1.0)

    def test_patient_level_cluster_bootstrap(self):
        """Verifies cluster bootstrap correctly samples patients with replacement."""
        # 10 patients with bilateral images (20 images total)
        records = []
        for p in range(10):
            p_id = f"PAT_{p}"
            for eye in ["OD", "OS"]:
                grade = p % 5
                probs = [0.1] * 5
                probs[grade] = 0.6
                records.append({
                    "patient_id": p_id,
                    "image_id": f"{p_id}_{eye}",
                    "true_grade": grade,
                    "pred_grade": grade,
                    "probs": probs,
                })

        ci_dict = run_patient_cluster_bootstrap(records, num_iterations=100, seed=42)

        self.assertIn("qwk", ci_dict)
        self.assertIn("macro_f1", ci_dict)
        self.assertIn("rdr_sensitivity", ci_dict)
        self.assertIn("rdr_specificity", ci_dict)

        qwk_low, qwk_high = ci_dict["qwk"]
        self.assertTrue(qwk_low <= qwk_high)
        self.assertGreaterEqual(qwk_high, 0.8)

    def test_prespecified_ablations(self):
        """Verifies 5 prespecified frozen variants are evaluated without retuning."""
        records = [
            {
                "true_grade": i % 5,
                "pred_grade": i % 5,
                "raw_pred_grade": (i + 1) % 5,
                "enhanced_pred_grade": i % 5,
                "calibrated_pred_grade": i % 5,
                "consistency_recommended_grade": i % 5,
                "quality": "good",
            }
            for i in range(25)
        ]

        ablations = evaluate_prespecified_ablations(records)
        self.assertEqual(len(ablations), 5)
        ab_names = [a.ablation_id for a in ablations]
        self.assertIn("ablation_1_raw_classifier", ab_names)
        self.assertIn("ablation_2_enhancement", ab_names)
        self.assertIn("ablation_3_quality_gating", ab_names)
        self.assertIn("ablation_4_calibration", ab_names)
        self.assertIn("ablation_5_full_system", ab_names)

    def test_camera_subgroups_honestly_flags_small_n(self):
        """Subgroups with sample size N < 20 are honestly flagged as insufficient."""
        records = [
            {"camera": "Canon CR-2", "true_grade": 0, "pred_grade": 0} for _ in range(30)
        ] + [
            {"camera": "Smartphone Adapter", "true_grade": 1, "pred_grade": 1} for _ in range(5)
        ]

        subgroups = evaluate_camera_subgroups(records)
        self.assertEqual(len(subgroups), 2)

        canon_sg = next(s for s in subgroups if s.subgroup_name == "Canon CR-2")
        self.assertFalse(canon_sg.is_insufficient_sample)
        self.assertIsNotNone(canon_sg.macro_f1)

        phone_sg = next(s for s in subgroups if s.subgroup_name == "Smartphone Adapter")
        self.assertTrue(phone_sg.is_insufficient_sample)
        self.assertIn("below statistical threshold", phone_sg.notes)

    def test_full_evaluation_report_generation(self):
        """Tests full evaluation report assembly and Pydantic serialization."""
        from scripts.run_evaluation_suite import create_synthetic_eval_cohort

        records = create_synthetic_eval_cohort(n_patients=20, seed=42)
        suite = EvaluationSuite(bootstrap_iterations=50, seed=42)
        report = suite.evaluate_cohort(records)

        self.assertIsInstance(report, EvaluationReport)
        self.assertTrue(report.is_frozen)
        self.assertEqual(report.total_images, len(records))
        self.assertEqual(report.total_patients, 20)
        self.assertGreater(report.quadratic_weighted_kappa.value, 0.7)

        # Test dictionary export
        data = report.model_dump(mode="json")
        self.assertIn("quadratic_weighted_kappa", data)
        self.assertIn("referable_dr", data)
        self.assertIn("ablations", data)
        self.assertEqual(len(data["ablations"]), 5)


if __name__ == "__main__":
    unittest.main()
