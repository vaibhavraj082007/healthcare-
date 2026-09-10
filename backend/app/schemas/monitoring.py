"""
RetinaShield — Operational Monitoring Schemas

Defines structured responses for:
1. Operational metrics (throughput, ungradeable rates, backlog, failures, sync, latency, model versions).
2. Input-quality and prediction-distribution shifts.
3. Privacy-preserving small-cell suppression rules.
4. Strict regulatory and clinical accuracy separation disclaimers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


# ---------------------------------------------------------------------------
# Privacy-Preserving Cell Wrapper
# ---------------------------------------------------------------------------

class AggregationCell(BaseModel):
    """
    Privacy-preserving count cell.
    If actual count is below threshold (e.g. < 5), is_suppressed is True and
    display_count is '< 5' to prevent patient re-identification under DPDP Act 2023.
    """
    model_config = ConfigDict(from_attributes=True)

    category: str
    count: Optional[int] = Field(None, description="Actual count if not suppressed")
    display_count: str = Field(..., description="Human-readable count or '< 5' when suppressed")
    is_suppressed: bool = Field(False, description="True if cell was masked due to small-group threshold")


# ---------------------------------------------------------------------------
# Operational Monitoring Schemas
# ---------------------------------------------------------------------------

class ScreeningVolumeMetrics(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_screenings: int
    last_24h: int
    last_7d: int
    last_30d: int
    daily_trend: List[AggregationCell] = Field(
        default_factory=list,
        description="Daily screening volume with small-cell suppression"
    )
    by_facility: List[AggregationCell] = Field(
        default_factory=list,
        description="Screening volume aggregated by facility with small-cell suppression"
    )


class UngradeableRateMetrics(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_screenings_evaluated: int
    total_ungradeable_count: int
    ungradeable_rate_pct: float = Field(..., description="Overall ungradeable rate percentage")
    ai_ungradeable_count: int
    ai_ungradeable_pct: float
    clinician_ungradeable_count: int
    clinician_ungradeable_pct: float
    quality_verdict_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="Counts of good, acceptable, poor, rejected"
    )
    failure_reasons_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="Aggregated counts of quality failure reasons (e.g., severe_blur, underexposed)"
    )


class ReviewBacklogMetrics(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_backlog: int = Field(..., description="Total completed screenings awaiting clinician review")
    awaiting_review_count: int = Field(..., description="Screenings with no clinician review yet")
    draft_review_count: int = Field(..., description="Screenings with in-progress draft review")
    age_distribution: Dict[str, int] = Field(
        default_factory=dict,
        description="Backlog age: {'under_24h': N, 'between_24_72h': N, 'over_72h': N}"
    )
    urgency_distribution: Dict[str, int] = Field(
        default_factory=dict,
        description="Backlog by AI provisional urgency: {'none': N, 'routine': N, 'priority': N, 'urgent': N}"
    )
    oldest_pending_hours: Optional[float] = Field(None, description="Age in hours of the oldest unreviewed case")


class ProcessingFailureMetrics(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    failure_rate_pct: float
    failure_categories: Dict[str, int] = Field(
        default_factory=dict,
        description="Error classification (e.g. timeout, memory, matlab_error, corrupt_image)"
    )
    recent_failures: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Recent failure events with sanitized non-PII error messages"
    )


class SynchronizationFailureMetrics(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_synced_screenings: int
    pending_sync_screenings: int
    sync_conflicts_total: int
    sync_conflicts_unresolved: int
    incomplete_chunk_sessions: int
    conflict_type_breakdown: Dict[str, int] = Field(
        default_factory=dict,
        description="Breakdown by conflict type (e.g. grade_mismatch, approved_overwrite_attempt)"
    )


class LatencyMetrics(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_measured_jobs: int
    mean_seconds: Optional[float] = None
    median_seconds: Optional[float] = None
    p95_seconds: Optional[float] = None
    min_seconds: Optional[float] = None
    max_seconds: Optional[float] = None
    stage_breakdown_mean_seconds: Dict[str, float] = Field(
        default_factory=dict,
        description="Mean duration for each pipeline stage (IQA, segmentation, classification, lesion detection)"
    )


class ModelVersionUsage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model_name: str
    model_version: str
    runs_count: int
    percentage: float
    model_trained: bool = Field(..., description="True if trained weights used; False if placeholder fallback")


class OperationalMetricsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    generated_at: datetime
    facility_id_filter: Optional[str] = None
    time_window_days: int
    privacy_suppression_threshold: int

    screening_volume: ScreeningVolumeMetrics
    ungradeable_rates: UngradeableRateMetrics
    review_backlog: ReviewBacklogMetrics
    processing_failures: ProcessingFailureMetrics
    synchronization_failures: SynchronizationFailureMetrics
    latency: LatencyMetrics
    model_version_usage: List[ModelVersionUsage]

    clinical_accuracy_separation_disclaimer: str = Field(
        default=(
            "ARCHITECTURAL & CLINICAL SEPARATION: Operational monitoring measures system throughput, "
            "review backlog, queue latency, and pipeline execution failures. It does NOT evaluate "
            "clinical model accuracy (sensitivity, specificity, or AUC). Clinical accuracy strictly requires "
            "ground-truth outcome labels from qualified ophthalmologist consensus panels or frozen benchmark suites."
        )
    )


# ---------------------------------------------------------------------------
# Shift Monitoring Schemas
# ---------------------------------------------------------------------------

class QualityShiftMetric(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_name: str
    baseline_mean: Optional[float] = None
    baseline_std: Optional[float] = None
    current_mean: Optional[float] = None
    current_std: Optional[float] = None
    delta_mean: Optional[float] = None
    shift_flag: bool = Field(False, description="True if |delta| exceeds 1.5 baseline standard deviations")


class ShiftMonitoringResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    generated_at: datetime
    current_window_days: int
    baseline_window_days: int
    current_sample_size: int
    baseline_sample_size: int
    small_cell_suppression_applied: bool

    quality_shift_metrics: List[QualityShiftMetric] = Field(default_factory=list)
    quality_verdict_shift: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="Comparison of quality verdict proportions: {'baseline': {...}, 'current': {...}}"
    )
    ungradeable_rate_shift: Dict[str, float] = Field(
        default_factory=dict,
        description="Comparison of ungradeable rates: {'baseline_pct': X, 'current_pct': Y}"
    )

    prediction_dr_grade_shift: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="Comparison of predicted DR grade proportions (0-4): {'baseline': {...}, 'current': {...}}"
    )
    confidence_shift: Dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="Mean confidence comparison: {'baseline': X, 'current': Y}"
    )
    entropy_shift: Dict[str, Optional[float]] = Field(
        default_factory=dict,
        description="Mean uncertainty entropy comparison: {'baseline': X, 'current': Y}"
    )

    regulatory_safety_notice: str = Field(
        default=(
            "REGULATORY & CLINICAL SAFETY NOTICE: Input-quality and prediction-distribution shifts "
            "detect operational changes in data streams (such as camera optical changes, clinic lighting variations, "
            "or demographic differences). They DO NOT prove clinical performance drift, model degradation, or clinical superiority. "
            "AUTONOMOUS RETRAINING FROM UNVERIFIED AI OUTPUTS IS STRICTLY PROHIBITED. Any model update requires qualified "
            "ophthalmologist-reviewed data, adjudicated ground truth labels, and a controlled offline evaluation protocol before deployment."
        )
    )
