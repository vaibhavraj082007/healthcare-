"""
RetinaShield — Consent Record ORM Model

Records informed consent for screening and tele-ophthalmology review
in accordance with Indian DPDP Act 2023 requirements.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, DateTime, Boolean, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import GUID

if TYPE_CHECKING:
    from app.models.patient import Patient


class ConsentRecord(Base):
    """Explicit patient consent record for diabetic retinopathy screening."""

    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )

    consent_type: Mapped[str] = mapped_column(
        String(100),
        default="dr_screening_and_teleophthalmology",
        comment="Type/scope of consent granted",
    )

    granted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    consent_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    obtained_by_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Name of health worker who obtained consent"
    )
    witness_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Optional witness name if patient cannot sign"
    )

    # Consent withdrawal tracking
    withdrawn: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    withdrawal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationship
    patient: Mapped[Patient] = relationship("Patient", back_populates="consents")

    def __repr__(self) -> str:
        return f"<ConsentRecord {self.id} patient={self.patient_id} granted={self.granted} withdrawn={self.withdrawn}>"
