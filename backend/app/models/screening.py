"""
RetinaShield — Screening & ScreeningImage ORM Models

Stores screening sessions and their associated fundus images and analysis results.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    String, DateTime, Integer, Float, Boolean, Text, ForeignKey, JSON, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Screening(Base):
    """A single DR screening session for a patient."""

    __tablename__ = "screenings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Patient link
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )

    # Facility info
    facility_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    screener_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="Name of the health worker who performed screening"
    )

    # Clinical eye info
    eye: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="'left', 'right', or 'both'"
    )

    # Pipeline status
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending",
        comment="pending, processing, completed, failed, rejected"
    )

    # Analysis result — the full JSON conforming to analysis_result_schema.json
    analysis_result: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="Complete analysis result from MATLAB + YOLOv8 pipeline"
    )

    # Summary fields (denormalized for query efficiency)
    quality_verdict: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="good, acceptable, poor, rejected"
    )
    dr_grade: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Predicted DR severity grade 0-4"
    )
    dr_grade_label: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    dr_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Classification confidence [0, 1]"
    )
    referral_urgency: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="none, routine, priority, urgent"
    )
    model_trained: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="Whether the model used was actually trained (false = placeholder)"
    )

    # Disclaimer always present
    disclaimer: Mapped[str] = mapped_column(
        Text,
        default="RESEARCH SCREENING RESULT — Not a clinical diagnosis. Must be reviewed by a qualified ophthalmologist.",
    )

    # Timestamps
    screened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Sync tracking (for offline facility service)
    synced: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    patient: Mapped["Patient"] = relationship("Patient", back_populates="screenings")
    images: Mapped[list["ScreeningImage"]] = relationship(
        "ScreeningImage", back_populates="screening", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Screening {self.id} patient={self.patient_id} eye={self.eye} status={self.status}>"


class ScreeningImage(Base):
    """A fundus image captured during a screening session."""

    __tablename__ = "screening_images"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    screening_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("screenings.id", ondelete="CASCADE"), nullable=False
    )

    # Image metadata
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_filename: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="UUID-based filename in private storage"
    )
    storage_path: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="Full path in private image store"
    )
    content_type: Mapped[str] = mapped_column(
        String(50), default="image/jpeg"
    )
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Image properties
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eye: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="'left' or 'right'"
    )

    # Enhanced/derived image paths
    enhanced_image_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    gradcam_image_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    vessel_mask_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Timestamps
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationship
    screening: Mapped["Screening"] = relationship("Screening", back_populates="images")

    def __repr__(self) -> str:
        return f"<ScreeningImage {self.id} screening={self.screening_id} eye={self.eye}>"
