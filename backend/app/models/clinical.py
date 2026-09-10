"""
RetinaShield — Clinical & AI ORM Models

Enforces architectural separation between:
1. AI pipeline model outputs (research screening results).
2. Clinician reviews and diagnosis decisions (authoritative medical judgment).
3. Image provenance, image quality assessment (IQA), and signed reports.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    String, DateTime, Integer, Float, Boolean, Text, ForeignKey, JSON, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import GUID

if TYPE_CHECKING:
    from app.models.screening import Screening, ScreeningImage
    from app.models.user import User


class ImageProvenance(Base):
    """Camera, acquisition settings, and integrity hash for an uploaded fundus image."""

    __tablename__ = "image_provenance"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )

    image_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("screening_images.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    camera_make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    camera_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lens_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fov_angle_degrees: Mapped[float | None] = mapped_column(Float, nullable=True)
    capture_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Cryptographic integrity
    sha256_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="SHA-256 hash of original raw image bytes"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationship
    image: Mapped[ScreeningImage] = relationship("ScreeningImage", back_populates="provenance")

    def __repr__(self) -> str:
        return f"<ImageProvenance image={self.image_id} hash={self.sha256_hash[:8]}...>"


class QualityResult(Base):
    """Detailed Image Quality Assessment (IQA) verdict and metrics."""

    __tablename__ = "quality_results"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )

    image_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("screening_images.id", ondelete="CASCADE"), nullable=False, index=True
    )
    screening_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("screenings.id", ondelete="CASCADE"), nullable=False, index=True
    )

    verdict: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="good, acceptable, poor, rejected"
    )
    ungradeable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    overall_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Detailed metrics
    contrast: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpness: Mapped[float | None] = mapped_column(Float, nullable=True)
    illumination_uniformity: Mapped[float | None] = mapped_column(Float, nullable=True)
    blur_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid_retina_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)

    failure_reasons: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, comment="List of failure reasons (e.g. ['severe_blur', 'underexposed'])"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<QualityResult image={self.image_id} verdict={self.verdict} ungradeable={self.ungradeable}>"


class ModelOutput(Base):
    """
    Research AI model output (MATLAB classifier + YOLOv8 lesion detector).

    IMPORTANT: This is strictly an AI candidate output, NEVER an autonomous diagnosis.
    It remains preserved and is never overwritten by clinician reviews.
    """

    __tablename__ = "model_outputs"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )

    screening_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("screenings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("screening_images.id", ondelete="SET NULL"), nullable=True
    )

    # Model provenance
    model_name: Mapped[str] = mapped_column(String(100), default="RetinaShield-EfficientNetB0")
    model_version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    model_trained: Mapped[bool] = mapped_column(Boolean, default=False)

    # Predictions
    predicted_dr_grade: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="DR grade 0-4"
    )
    predicted_grade_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    class_probabilities: Mapped[list[float] | None] = mapped_column(
        JSON, nullable=True, comment="Probabilities [p0, p1, p2, p3, p4]"
    )
    calibrated: Mapped[bool] = mapped_column(Boolean, default=False)

    # Uncertainty indicators
    uncertainty_entropy: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty_margin: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Consistency & Explanations
    concordance_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="'Concordant AI findings', 'Discrepant', etc."
    )
    lesion_detections_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="Estimated counts of microaneurysms, hemorrhages, etc."
    )
    gradcam_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    disclaimer: Mapped[str] = mapped_column(
        Text,
        default="RESEARCH SCREENING RESULT — Not a clinical diagnosis. Must be reviewed by an ophthalmologist."
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ModelOutput screening={self.screening_id} grade={self.predicted_dr_grade} conf={self.confidence}>"


class ClinicianReview(Base):
    """
    Authoritative diagnosis decision entered by a qualified ophthalmologist.

    Maintained strictly separate from AI model outputs.
    Supports optimistic concurrency locking to prevent conflicting concurrent edits.
    All grade/status changes are appended to ReviewAmendment for an auditable history.
    """

    __tablename__ = "clinician_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )

    screening_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("screenings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # Optimistic-concurrency version stamp
    review_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="Incremented on each accepted edit. Client must send matching version to prevent lost-update."
    )

    # Case-lock to prevent conflicting concurrent edits
    locked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        comment="User who currently holds the editing lock"
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Stale locks older than this may be reclaimed by another reviewer"
    )

    # Clinical judgment
    confirmed_dr_grade: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="0: No DR, 1: Mild, 2: Moderate, 3: Severe, 4: PDR, -1: Ungradeable"
    )
    macular_edema_present: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Explicit ungradeable and recapture flags (separate from grade=-1 for clarity)
    is_ungradeable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="True when the image cannot be assessed regardless of grade"
    )
    recapture_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="True when reviewer requests a new image capture"
    )

    referral_recommendation: Mapped[str] = mapped_column(
        String(30), nullable=False, default="routine",
        comment="'none', 'routine', 'priority', 'urgent'"
    )
    follow_up_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clinical_notes: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(
        String(20), default="final",
        comment="'draft', 'final', 'amended'"
    )

    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    reviewer: Mapped[User] = relationship("User", foreign_keys=[reviewer_id], back_populates="reviews")
    locked_by: Mapped[User | None] = relationship("User", foreign_keys=[locked_by_id])
    screening: Mapped[Screening] = relationship("Screening", back_populates="clinician_review")
    amendments: Mapped[list[ReviewAmendment]] = relationship(
        "ReviewAmendment", back_populates="review", cascade="all, delete-orphan",
        order_by="ReviewAmendment.amended_at",
    )

    def __repr__(self) -> str:
        return f"<ClinicianReview screening={self.screening_id} reviewer={self.reviewer_id} grade={self.confirmed_dr_grade}>"


class ReviewAmendment(Base):
    """
    Immutable append-only audit record of each change to a ClinicianReview.

    Created whenever a final review is subsequently amended (grade/referral/status change).
    NEVER deleted — forms part of the permanent clinical audit trail.
    """

    __tablename__ = "review_amendments"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )

    review_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("clinician_reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amended_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # What changed
    previous_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_referral: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_referral: Mapped[str | None] = mapped_column(String(30), nullable=True)
    previous_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Mandatory reason when amending a final review
    change_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Required free-text reason when changing a previously-finalized review"
    )
    amendment_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    amended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # Relationships
    review: Mapped[ClinicianReview] = relationship("ClinicianReview", back_populates="amendments")
    amended_by: Mapped[User | None] = relationship("User", foreign_keys=[amended_by_id])

    def __repr__(self) -> str:
        return (
            f"<ReviewAmendment review={self.review_id} "
            f"grade={self.previous_grade}→{self.new_grade} by={self.amended_by_id}>"
        )


class Report(Base):
    """Generated clinical summary report combining screening metadata and review sign-off."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )

    screening_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("screenings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    generated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    signed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    report_type: Mapped[str] = mapped_column(
        String(50), default="teleophthalmology_report"
    )
    status: Mapped[str] = mapped_column(
        String(30), default="signed",
        comment="'draft', 'signed', 'archived'"
    )

    summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False,
        comment="Structured clinical report contents including findings, disclaimer, and signature"
    )
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    signed_by: Mapped[User | None] = relationship("User", foreign_keys=[signed_by_id], back_populates="signed_reports")
    screening: Mapped[Screening] = relationship("Screening", back_populates="reports")

    def __repr__(self) -> str:
        return f"<Report {self.id} screening={self.screening_id} status={self.status}>"
