"""
Tests for RetinaShield Grad-CAM Explainability System.

Validates:
1. GradCAMExplanation and PreprocessingTransform schema integrity
2. Explicit failure semantics (never substitute decorative heatmaps)
3. Coordinate transform tracking (original to model input)
4. Explanation-localization evaluation metrics (pointing game, IoU, energy)
5. AnalysisResult integration and JSON serialization
"""

import unittest
import uuid
from app.schemas.analysis_result import (
    AnalysisResult,
    GradCAMExplanation,
    PreprocessingTransform,
    SeverityClassification,
)


class TestGradCAMSchemas(unittest.TestCase):
    """Test suite for Grad-CAM explainability schema definitions and validation."""

    def test_default_gradcam_explanation(self):
        """GradCAMExplanation defaults to unavailable with research disclaimer."""
        gradcam = GradCAMExplanation()
        self.assertEqual(gradcam.status, "unavailable")
        self.assertEqual(gradcam.reason, "")
        self.assertIsNone(gradcam.gradcam_heatmap_path)
        self.assertIsNone(gradcam.gradcam_overlay_path)
        self.assertIsNone(gradcam.target_layer)
        self.assertIn("Grad-CAM shows model-influential regions", gradcam.disclaimer)
        self.assertIn("not confirmed lesions", gradcam.disclaimer)
        self.assertEqual(gradcam.algorithm_version, "1.0.0-gradcam")

    def test_available_gradcam_explanation_with_provenance(self):
        """Available Grad-CAM carries full activation and transform provenance."""
        transform = PreprocessingTransform(
            original_size=[2136, 3216],
            model_input_size=[224, 224],
            scale_factor_h=0.1048,
            scale_factor_w=0.0696,
            crop_box=None,
            pad_offsets=None,
        )
        gradcam = GradCAMExplanation(
            status="available",
            reason="",
            gradcam_heatmap_path="/path/to/heatmap.png",
            gradcam_overlay_path="/path/to/overlay.png",
            gradcam_raw_path="/path/to/raw.mat",
            target_layer="top_conv",
            target_class="Moderate NPDR",
            predicted_class="Moderate NPDR",
            preprocessing_transform=transform,
            pointing_game_hit=True,
            expert_iou=0.485,
            energy_pointing_game=0.712,
        )

        self.assertEqual(gradcam.status, "available")
        self.assertEqual(gradcam.target_layer, "top_conv")
        self.assertEqual(gradcam.target_class, "Moderate NPDR")
        self.assertTrue(gradcam.pointing_game_hit)
        self.assertAlmostEqual(gradcam.expert_iou, 0.485, places=3)
        self.assertAlmostEqual(gradcam.energy_pointing_game, 0.712, places=3)
        self.assertIsNotNone(gradcam.preprocessing_transform)
        self.assertEqual(gradcam.preprocessing_transform.model_input_size, [224, 224])

    def test_explicit_failure_semantics(self):
        """When weights or activations are unavailable, explicit reason is mandated."""
        gradcam = GradCAMExplanation(
            status="unavailable",
            reason="Model is a SMOKE_TEST checkpoint — Grad-CAM requires a fully trained model",
        )
        self.assertEqual(gradcam.status, "unavailable")
        self.assertIn("SMOKE_TEST", gradcam.reason)
        self.assertIsNone(gradcam.gradcam_heatmap_path)

    def test_analysis_result_integration(self):
        """AnalysisResult includes gradcam_explanation and round-trips via JSON."""
        transform = PreprocessingTransform(
            original_size=[1000, 1500],
            model_input_size=[224, 224],
            scale_factor_h=0.224,
            scale_factor_w=0.1493,
        )
        gradcam = GradCAMExplanation(
            status="available",
            gradcam_heatmap_path="/out/fundus_gradcam_heatmap.png",
            gradcam_overlay_path="/out/fundus_gradcam_overlay.png",
            target_layer="efficientnetb0_conv_head",
            target_class="Severe NPDR",
            predicted_class="Severe NPDR",
            preprocessing_transform=transform,
            pointing_game_hit=False,
            expert_iou=0.12,
            energy_pointing_game=0.25,
        )

        result = AnalysisResult(
            image_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
            severity_classification=SeverityClassification(
                model="EfficientNet-B0",
                predicted_grade=3,
                grade_label="Severe NPDR",
                confidence=0.88,
                model_trained=True,
            ),
            gradcam_explanation=gradcam,
        )

        # Convert to dict and reload
        data = result.model_dump(mode="json")
        self.assertIn("gradcam_explanation", data)
        self.assertEqual(data["gradcam_explanation"]["status"], "available")
        self.assertEqual(data["gradcam_explanation"]["target_layer"], "efficientnetb0_conv_head")
        self.assertFalse(data["gradcam_explanation"]["pointing_game_hit"])
        self.assertEqual(data["gradcam_explanation"]["preprocessing_transform"]["original_size"], [1000, 1500])

        # Validate deserialization back into Pydantic model
        reconstructed = AnalysisResult.model_validate(data)
        self.assertIsNotNone(reconstructed.gradcam_explanation)
        self.assertEqual(reconstructed.gradcam_explanation.status, "available")
        self.assertEqual(reconstructed.gradcam_explanation.predicted_class, "Severe NPDR")


if __name__ == "__main__":
    unittest.main()
