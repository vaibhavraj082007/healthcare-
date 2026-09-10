"""
RetinaShield — Evaluation Suite Pydantic Schemas

Defines schemas for reproducible benchmark evaluation:
  - Multi-class classification metrics (Macro-F1, Balanced Accuracy, Quadratic Weighted Kappa)
  - Clinical screening endpoints (Referable DR, Sight-Threatening DR, ROC/PR metrics)
  - Calibration metrics (ECE, MCE, Brier, NLL)
  - Quality gating and ungradeable rates
  - Patient-level cluster bootstrap confidence intervals
  - Prespecified ablation studies
  - Subgroup and degradation analyses
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class MetricWithCI(BaseModel):
    """A metric value accompanied by empirical bootstrap confidence intervals."""

    value: float
    ci_lower: float
    ci_upper: float
    confidence_level: float = 0.95


class PerClassMetric(BaseModel):
    """Performance metrics for a specific DR severity grade."""

    grade: int = Field(ge=0, le=4)
    class_name: str
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)  # Sensitivity
    specificity: float = Field(ge=0, le=1)
    f1_score: float = Field(ge=0, le=1)
    support: int = Field(ge=0)


class ConfusionMatrixData(BaseModel):
    """5x5 multi-class confusion matrix."""

    matrix: List[List[int]]
    class_labels: List[str] = [
        "No DR",
        "Mild NPDR",
        "Moderate NPDR",
        "Severe NPDR",
        "Proliferative DR",
    ]


class ScreeningEndpointMetrics(BaseModel):
    """Performance on explicitly defined clinical screening thresholds."""

    endpoint_name: str  # e.g. "Referable DR (Grade >= 2)"
    threshold_rule: str
    sensitivity: MetricWithCI
    specificity: MetricWithCI
    ppv: Optional[float] = None
    npv: Optional[float] = None
    auroc: Optional[MetricWithCI] = None
    aupr: Optional[float] = None
    f1_score: Optional[float] = None
    support_positive: int = 0
    support_negative: int = 0


class ReliabilityBin(BaseModel):
    """A single confidence bin in a calibration reliability diagram."""

    bin_index: int
    confidence_mean: float
    accuracy: float
    sample_count: int


class CalibrationMetrics(BaseModel):
    """Multi-class probability calibration evaluation."""

    status: Literal["calibrated", "uncalibrated_raw_softmax", "fallback_uniform"] = "calibrated"
    ece: MetricWithCI
    mce: float
    brier_score: float
    negative_log_likelihood: float
    reliability_bins: List[ReliabilityBin] = Field(default_factory=list)


class QualityCoverageMetrics(BaseModel):
    """Quality gating rates, coverage, and whole-pipeline failure accounting."""

    total_images: int = 0
    accepted_images: int = 0
    ungradeable_images: int = 0
    ungradeable_rate: float = 0.0
    accepted_coverage: float = 1.0
    whole_pipeline_failures: int = 0
    whole_pipeline_failure_rate: float = 0.0


class LesionEvaluationMetrics(BaseModel):
    """Evaluation on lesion detection & segmentation ground-truth annotations."""

    status: Literal["ready", "unavailable", "heuristic_only"] = "unavailable"
    message: str = ""
    map_50: Optional[float] = None
    map_50_95: Optional[float] = None
    dice_coefficient: Optional[float] = None
    jaccard_iou: Optional[float] = None
    per_class_f1: Dict[str, float] = Field(default_factory=dict)


class AblationResult(BaseModel):
    """Performance of a prespecified system variant evaluated on held-out data."""

    ablation_id: str
    ablation_name: str
    description: str
    macro_f1: float
    quadratic_weighted_kappa: float
    rdr_sensitivity: float
    rdr_specificity: float
    ungradeable_rate: float
    notes: str = ""


class SubgroupResult(BaseModel):
    """Evaluation stratified by domain, camera model, or demographic subgroup."""

    subgroup_name: str
    category: str  # "camera", "facility", "severity"
    sample_size: int
    is_insufficient_sample: bool = False  # Flagged if N < 20
    macro_f1: Optional[float] = None
    quadratic_weighted_kappa: Optional[float] = None
    rdr_sensitivity: Optional[float] = None
    rdr_specificity: Optional[float] = None
    notes: str = ""


class DegradationPoint(BaseModel):
    """Robustness measurement under a specific synthetic degradation."""

    corruption_type: str  # "gaussian_blur", "underexposure", "overexposure", "sensor_noise", "jpeg_compression"
    severity_label: str   # e.g. "sigma=2.0", "-30%", "quality=50"
    severity_value: float
    macro_f1: float
    quadratic_weighted_kappa: float
    rdr_sensitivity: float


class EvaluationReport(BaseModel):
    """
    Comprehensive reproducible evaluation report.

    Strictly reflects actual benchmark runs on frozen models and held-out data.
    """

    report_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    pipeline_version: str = "1.0.0-frozen"
    rules_version: str = "1.0.0"
    dataset_name: str = "RetinaShield Held-Out Evaluation Benchmark"
    evaluation_manifest_hash: str = ""
    is_frozen: bool = True

    # Cohort demographics & cluster resampling metadata
    total_images: int = 0
    total_patients: int = 0
    resampling_method: Literal["patient_cluster", "image_level"] = "patient_cluster"
    bootstrap_iterations: int = 1000

    # Primary Multi-Class Metrics
    quadratic_weighted_kappa: MetricWithCI
    macro_f1: MetricWithCI
    balanced_accuracy: MetricWithCI
    per_class_metrics: List[PerClassMetric] = Field(default_factory=list)
    confusion_matrix: ConfusionMatrixData

    # Explicit Clinical Screening Endpoints
    referable_dr: ScreeningEndpointMetrics
    sight_threatening_dr: ScreeningEndpointMetrics

    # Calibration & Quality
    calibration: CalibrationMetrics
    quality_coverage: QualityCoverageMetrics

    # Focal Lesion & Structure Metrics
    lesion_metrics: LesionEvaluationMetrics

    # Prespecified Ablation Studies
    ablations: List[AblationResult] = Field(default_factory=list)

    # Subgroup & Robustness Stress Tests
    subgroup_analysis: List[SubgroupResult] = Field(default_factory=list)
    degradation_analysis: List[DegradationPoint] = Field(default_factory=list)

    disclaimer: str = (
        "RESEARCH SCREENING BENCHMARK — Metrics computed on strictly held-out evaluation cohorts. "
        "Models, thresholds, and calibration parameters were frozen prior to assessment. "
        "Not an autonomous clinical diagnosis. Must be reviewed by a qualified ophthalmologist."
    )
