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


class OpticDisc(BaseModel):
    """Optic disc detection result."""

    detected: bool = False
    center_x: float | None = None
    center_y: float | None = None
    radius: float | None = None
    confidence: float | None = Field(None, ge=0, le=1)


class Macula(BaseModel):
    """Macula detection result."""

    detected: bool = False
    center_x: float | None = None
    center_y: float | None = None
    confidence: float | None = Field(None, ge=0, le=1)


class Vasculature(BaseModel):
    """Vessel segmentation metrics."""

    segmentation_mask_path: str | None = None
    vessel_density: float | None = Field(None, ge=0, le=1)
    tortuosity_index: float | None = None


class StructureAnalysis(BaseModel):
    """Retinal structure segmentation from MATLAB."""

    optic_disc: OpticDisc = Field(default_factory=OpticDisc)
    macula: Macula = Field(default_factory=Macula)
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


class LesionBBox(BaseModel):
    """Bounding box for a detected lesion."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float


class LesionDetection(BaseModel):
    """A single lesion detected by YOLOv8."""

    lesion_type: Literal[
        "microaneurysm", "hemorrhage", "hard_exudate",
        "soft_exudate", "neovascularization"
    ]
    bbox: LesionBBox
    confidence: float = Field(ge=0, le=1)


class LesionDetectionResult(BaseModel):
    """YOLOv8-based lesion detection results."""

    model: str = "YOLOv8"
    detections: list[LesionDetection] = Field(default_factory=list)
    model_trained: bool = False


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
    lesion_detection: LesionDetectionResult | None = None
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
