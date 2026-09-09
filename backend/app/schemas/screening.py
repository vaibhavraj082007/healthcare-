"""
RetinaShield — Screening Pydantic Schemas

Request/response schemas for screening sessions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.analysis_result import AnalysisResult


class ScreeningCreate(BaseModel):
    """Schema for creating a new screening session."""

    patient_id: uuid.UUID
    facility_id: str | None = None
    screener_name: str | None = None
    eye: Literal["left", "right", "both"] = "both"


class ScreeningRead(BaseModel):
    """Full screening record with analysis results."""

    id: uuid.UUID
    patient_id: uuid.UUID
    facility_id: str | None = None
    screener_name: str | None = None
    eye: str
    status: str
    quality_verdict: str | None = None
    dr_grade: int | None = None
    dr_grade_label: str | None = None
    dr_confidence: float | None = None
    referral_urgency: str | None = None
    model_trained: bool = False
    disclaimer: str
    analysis_result: dict | None = None
    screened_at: datetime
    analyzed_at: datetime | None = None
    created_at: datetime
    synced: bool = False

    class Config:
        from_attributes = True


class ScreeningSummary(BaseModel):
    """Compact screening summary for list views."""

    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str | None = None
    eye: str
    status: str
    dr_grade: int | None = None
    dr_grade_label: str | None = None
    referral_urgency: str | None = None
    model_trained: bool = False
    screened_at: datetime

    class Config:
        from_attributes = True


class AnalysisRequest(BaseModel):
    """Request to trigger analysis on a screening's images."""

    screening_id: uuid.UUID
    run_matlab: bool = Field(
        True, description="Run the MATLAB pipeline (IQA, enhance, segment, classify)"
    )
    run_yolo: bool = Field(
        True, description="Run YOLOv8 lesion detection"
    )
    force_rerun: bool = Field(
        False, description="Force re-analysis even if results already exist"
    )


class AnalysisResponse(BaseModel):
    """Response from analysis trigger."""

    screening_id: uuid.UUID
    status: str
    message: str
    result: AnalysisResult | None = None
