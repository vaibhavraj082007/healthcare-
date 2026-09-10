"""
RetinaShield — Analysis Result Pydantic Schema

Python equivalent of shared/analysis_result_schema.json.
This is the canonical schema returned by the MATLAB + YOLOv8 pipeline.

IMPORTANT: All outputs include a mandatory disclaimer labelling them as
RESEARCH SCREENING RESULTS, not autonomous clinical diagnoses.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------

class QualityAssessment(BaseModel):
    """Image quality metrics from MATLAB IQA module."""

    overall_quality: Literal["good", "acceptable", "poor", "rejected"]
    brisque_score: float | None = None
    sharpness_score: float | None = None
    illumination_uniformity: float | None = Field(None, ge=0, le=1)
    field_of_view_adequate: bool | None = None
    artifacts_detected: list[str] = Field(default_factory=list)


class Enhancement(BaseModel):
    """Enhancement outputs from MATLAB preprocessing."""

    method: str | None = None
    enhanced_image_path: str | None = None
    green_channel_path: str | None = None


class FieldOfView(BaseModel):
    """Retinal field of view segmentation result."""

    mask_path: str | None = None
    bounding_box: list[float] | None = None
    center_x: float | None = None
    center_y: float | None = None
    radius: float | None = None
    area_pixels: int | None = None
    area_ratio: float | None = Field(None, ge=0, le=1)
    is_reliable: bool = False
    failure_reason: str = ""
    algorithm_version: str = "0.2.0-classical"


class OpticDisc(BaseModel):
    """Optic disc detection and segmentation result."""

    detected: bool = False
    center_x: float | None = None
    center_y: float | None = None
    radius: float | None = None
    mask_path: str | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    is_reliable: bool = False
    failure_reason: str = ""
    algorithm_version: str = "0.2.0-classical"


class Macula(BaseModel):
    """Macula / Fovea detection result."""

    detected: bool = False
    center_x: float | None = None
    center_y: float | None = None
    radius: float | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    is_reliable: bool = False
    failure_reason: str = ""
    inferred_laterality: Literal["OD", "OS", "unknown"] = "unknown"
    algorithm_version: str = "0.2.0-classical"


class Vasculature(BaseModel):
    """Vessel segmentation and biomarker metrics."""

    segmentation_mask_path: str | None = None
    vessel_density: float | None = Field(None, ge=0, le=1)
    tortuosity_index: float | None = None
    caliber_proxy: float | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    is_reliable: bool = False
    failure_reason: str = ""
    algorithm_version: str = "0.2.0-classical"


class StructureAnalysis(BaseModel):
    """Retinal structure segmentation and localization."""

    is_experimental: bool = True
    field_of_view: FieldOfView = Field(default_factory=FieldOfView)
    optic_disc: OpticDisc = Field(default_factory=OpticDisc)
    macula: Macula = Field(default_factory=Macula)
    fovea: Macula = Field(default_factory=Macula)
    vasculature: Vasculature = Field(default_factory=Vasculature)


class SeverityClassification(BaseModel):
    """DR severity from MATLAB EfficientNet-B0."""

    model: str = "EfficientNet-B0"
    predicted_grade: int | None = Field(None, ge=-1, le=4)
    grade_label: str | None = None
    confidence: float | None = Field(None, ge=0, le=1)
    class_probabilities: list[float] | None = Field(
        None, min_length=5, max_length=5
    )
    gradcam_heatmap_path: str | None = None
    model_trained: bool = False


class PreprocessingTransform(BaseModel):
    """Spatial coordinate transformation tracking between original and model space."""

    original_size: list[int] | None = None
    model_input_size: list[int] | None = None
    scale_factor_h: float | None = None
    scale_factor_w: float | None = None
    crop_box: list[int] | None = None
    pad_offsets: list[int] | None = None


class GradCAMExplanation(BaseModel):
    """Grad-CAM explainability heatmap from actual model activations."""

    status: Literal["available", "unavailable", "error"] = "unavailable"
    reason: str = ""
    gradcam_heatmap_path: str | None = None
    gradcam_overlay_path: str | None = None
    gradcam_raw_path: str | None = None
    target_layer: str | None = None
    target_class: str | None = None
    predicted_class: str | None = None
    preprocessing_transform: PreprocessingTransform | None = None
    algorithm_version: str = "1.0.0-gradcam"
    disclaimer: str = (
        "Grad-CAM shows model-influential regions, not confirmed lesions or proof that a prediction is correct. "
        "RESEARCH SCREENING RESULT — not for autonomous diagnosis."
    )
    pointing_game_hit: bool | None = None
    expert_iou: float | None = None
    energy_pointing_game: float | None = None


class ApproximateExtent(BaseModel):
    """Approximate spatial extent of a lesion."""

    area_pixels: float | None = None
    equivalent_diameter: float | None = None
    width: float | None = None
    height: float | None = None


class LesionBBox(BaseModel):
    """Bounding box for a detected lesion."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float


class LesionDetection(BaseModel):
    """A single detected or proposed lesion."""

    lesion_type: Literal[
        "microaneurysm", "hemorrhage", "hard_exudate",
        "soft_exudate", "neovascularization", "cotton_wool_spot"
    ]
    bbox: LesionBBox
    confidence: float = Field(ge=0, le=1)
    approximate_extent: ApproximateExtent | None = None
    is_heuristic_candidate: bool = False


class LesionDetectionResult(BaseModel):
    """Lesion detection results."""

    model: str = "YOLOv8"
    status: Literal["ready", "unavailable", "heuristic_only"] = "unavailable"
    message: str = ""
    detections: list[LesionDetection] = Field(default_factory=list)
    model_estimated_count: dict[str, int] = Field(default_factory=dict)
    model_trained: bool = False


class ConfidenceCalibration(BaseModel):
    """Post-hoc confidence calibration and predictive uncertainty indicators."""

    status: Literal["calibrated", "uncalibrated_raw_softmax", "fallback_uniform"] = "uncalibrated_raw_softmax"
    temperature: float | None = None
    max_calibrated_probability: float | None = None
    confidence_margin: float | None = None
    shannon_entropy: float | None = None
    is_uncertain: bool = False


class ConsistencyAnalysis(BaseModel):
    """Conservative dual-engine consistency evaluation between DR classifier, lesions, and IQA."""

    consistency_status: Literal[
        "concordant",
        "discordant_classifier_high",
        "discordant_lesions_high",
        "uncertain_prediction",
        "quality_compromised",
        "component_unavailable",
    ] = "concordant"
    finding_label: str = "Concordant AI findings"
    human_review_required: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    recommended_grade: int | None = None
    recommended_urgency: Literal["none", "routine", "priority", "urgent"] = "none"
    rules_version: str = "1.0.0"


class ReferralRecommendation(BaseModel):
    """Rule-based referral suggestion."""

    urgency: Literal["none", "routine", "priority", "urgent"]
    reason: str
    suggested_followup_weeks: int | None = Field(None, ge=0)


# ---------------------------------------------------------------------------
# Main Analysis Result
# ---------------------------------------------------------------------------

DISCLAIMER = (
    "RESEARCH SCREENING RESULT — Not a clinical diagnosis. "
    "Must be reviewed by a qualified ophthalmologist."
)


class AnalysisResult(BaseModel):
    """
    Complete analysis result from the RetinaShield pipeline.

    Conforms to shared/analysis_result_schema.json.
    """

    analysis_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    image_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    facility_id: str | None = None
    pipeline_version: str = "0.1.0-dev"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    disclaimer: str = Field(default=DISCLAIMER)

    quality_assessment: QualityAssessment | None = None
    enhancement: Enhancement | None = None
    structure_analysis: StructureAnalysis | None = None
    severity_classification: SeverityClassification | None = None
    gradcam_explanation: GradCAMExplanation | None = None
    confidence_calibration: ConfidenceCalibration | None = None
    lesion_detection: LesionDetectionResult | None = None
    consistency_analysis: ConsistencyAnalysis | None = None
    referral_recommendation: ReferralRecommendation | None = None

    processing_time_seconds: float | None = None

    class Config:
        json_schema_extra = {
            "example": {
                "analysis_id": "550e8400-e29b-41d4-a716-446655440000",
                "pipeline_version": "0.1.0-dev",
                "disclaimer": DISCLAIMER,
                "quality_assessment": {
                    "overall_quality": "good",
                    "brisque_score": 23.5,
                    "sharpness_score": 450.2,
                },
                "severity_classification": {
                    "model": "EfficientNet-B0",
                    "model_trained": False,
                    "predicted_grade": -1,
                    "grade_label": "UNTRAINED — No prediction available",
                },
            }
        }
