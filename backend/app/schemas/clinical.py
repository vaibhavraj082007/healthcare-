"""
RetinaShield — Clinical Review, Report & Audit Pydantic Schemas

Strictly separates clinician review decisions from AI pipeline outputs.
Includes schemas for the ophthalmologist review queue, locking,
amendment audit history, and clinical report generation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Clinician Review — Create / Update
# ---------------------------------------------------------------------------

class ClinicianReviewCreate(BaseModel):
    """Schema for clinician (ophthalmologist) to submit or update diagnostic judgment."""
    confirmed_dr_grade: int = Field(..., ge=-1, le=4, description="0-4, or -1 for ungradeable")
    macular_edema_present: bool | None = None
    referral_recommendation: Literal["none", "routine", "priority", "urgent"] = "routine"
    follow_up_months: int | None = Field(None, ge=1, le=24)
    clinical_notes: str = Field(..., min_length=5, description="Clinician diagnostic rationale and findings")
    status: Literal["draft", "final"] = "final"
    is_ungradeable: bool = False
    recapture_requested: bool = False

    # Optimistic-concurrency: client echoes back the version it last saw.
    # If absent on creation, ignored. On amendment, mismatch → HTTP 409.
    expected_version: int | None = Field(
        None,
        description="Must match current review_version to prevent lost-update conflicts"
    )
    change_reason: str | None = Field(
        None,
        description="Required when amending a previously-final review"
    )


class ClinicianReviewRead(BaseModel):
    """Response schema for clinician review."""
    id: uuid.UUID
    screening_id: uuid.UUID
    reviewer_id: uuid.UUID
    review_version: int
    confirmed_dr_grade: int
    macular_edema_present: bool | None = None
    is_ungradeable: bool
    recapture_requested: bool
    referral_recommendation: str
    follow_up_months: int | None = None
    clinical_notes: str
    status: str
    # Lock state
    locked_by_id: uuid.UUID | None = None
    locked_at: datetime | None = None
    lock_expires_at: datetime | None = None
    # Timestamps
    reviewed_at: datetime
    updated_at: datetime
    # Embedded amendments
    amendments: list[ReviewAmendmentRead] = []

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Review Amendment (audit history)
# ---------------------------------------------------------------------------

class ReviewAmendmentRead(BaseModel):
    id: uuid.UUID
    review_id: uuid.UUID
    amended_by_id: uuid.UUID | None = None
    previous_grade: int | None = None
    new_grade: int | None = None
    previous_referral: str | None = None
    new_referral: str | None = None
    previous_status: str | None = None
    new_status: str | None = None
    change_reason: str | None = None
    amendment_notes: str | None = None
    amended_at: datetime

    class Config:
        from_attributes = True


# Fix forward reference
ClinicianReviewRead.model_rebuild()


# ---------------------------------------------------------------------------
# Case Lock
# ---------------------------------------------------------------------------

class LockAcquireResponse(BaseModel):
    """Returned when a reviewer successfully acquires a case lock."""
    screening_id: uuid.UUID
    locked_by_id: uuid.UUID
    locked_at: datetime
    lock_expires_at: datetime
    message: str = "Case lock acquired. Other reviewers will see this case as locked."


class LockReleaseResponse(BaseModel):
    screening_id: uuid.UUID
    message: str = "Case lock released."


# ---------------------------------------------------------------------------
# Review Queue
# ---------------------------------------------------------------------------

class ReviewQueueItem(BaseModel):
    """A single item in the ophthalmologist review queue."""
    screening_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str | None = None
    facility_id: str | None = None
    eye: str
    screened_at: datetime
    quality_verdict: str | None = None

    # AI provisional findings
    ai_dr_grade: int | None = None
    ai_dr_grade_label: str | None = None
    ai_confidence: float | None = None
    ai_referral_urgency: str | None = None
    ai_model_trained: bool = False

    # Uncertainty / disagreement flags
    is_uncertain: bool = False
    has_disagreement: bool = False
    concordance_status: str | None = None

    # Review status
    review_status: str  # "ai_generated" | "awaiting_review" | "in_review" | "clinician_reviewed" | "recapture_requested"
    confirmed_dr_grade: int | None = None
    confirmed_grade_label: str | None = None

    # Concurrency info
    review_version: int | None = None
    locked_by_id: uuid.UUID | None = None
    lock_expires_at: datetime | None = None

    class Config:
        from_attributes = True


class ReviewQueueResponse(BaseModel):
    """Paginated review queue with prioritization metadata."""
    items: list[ReviewQueueItem]
    total: int
    skip: int
    limit: int
    priority_rule: str
    priority_rule_version: str
    priority_rule_requires_clinical_approval: bool = True
    priority_rule_approval_note: str = (
        "Prioritization rules have not been independently validated for clinical use. "
        "The order of review is advisory only. Clinical urgency assessment remains the "
        "responsibility of the reviewing ophthalmologist."
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

class ReportCreate(BaseModel):
    """Request schema to generate a signed clinical screening report."""
    report_type: Literal[
        "screening_summary",
        "ophthalmology_referral",
        "technical_report",
        "patient_summary",
    ] = "technical_report"
    language: Literal["en", "hi"] = "en"
    is_signed: bool = False
    include_ai_findings: bool = True
    include_gradcam: bool = False
    clinical_summary_override: str | None = None


class ReportGenerateRequest(BaseModel):
    """Specific request schema for generating dual reports with multilingual options."""
    report_type: Literal["technical_report", "patient_summary"] = "technical_report"
    language: Literal["en", "hi"] = "en"
    is_signed: bool = False


class VoicePlaybackRequest(BaseModel):
    """Opt-in request for local offline speech playback."""
    voice_consent: bool
    language: Literal["en", "hi"] = "en"


class VoicePlaybackResponse(BaseModel):
    """Response payload for offline speech synthesis with text fallback."""
    voice_supported: bool
    fallback_to_text: bool
    voice_name: str | None = None
    language: str
    audio_base64: str | None = None
    audio_format: str | None = None
    spoken_text: str
    status_message: str



class ReportRead(BaseModel):
    """Response schema for signed report."""
    id: uuid.UUID
    screening_id: uuid.UUID
    generated_by_id: uuid.UUID | None = None
    signed_by_id: uuid.UUID | None = None
    report_type: str
    status: str
    summary_json: dict[str, Any]
    file_path: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Audit Event
# ---------------------------------------------------------------------------

class AuditEventRead(BaseModel):
    """Response schema for audit event log entries."""
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    facility_id: str | None = None
    event_type: str
    resource_type: str
    resource_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    details: dict[str, Any] | None = None
    created_at: datetime

    class Config:
        from_attributes = True
