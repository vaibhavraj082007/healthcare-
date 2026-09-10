"""
RetinaShield — Patient ORM Model

Stores minimal patient demographic information for DR screening.
All data handling strictly complies with Indian DPDP Act 2023 requirements:
- Minimal demographic data
- No Aadhaar or ABHA identifiers required for basic screening
- Soft-deletion with statutory retention support
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, Date, DateTime, Integer, Boolean, Float, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import GUID

if TYPE_CHECKING:
    from app.models.screening import Screening
    from app.models.consent import ConsentRecord


class Patient(Base):
    """Patient record for diabetic retinopathy screening."""

    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )

    # Demographics (minimum necessary for screening)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Contact (for follow-up referrals only)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    aadhaar_last4: Mapped[str | None] = mapped_column(
        String(4), nullable=True,
        comment="Optional last 4 digits only — never store full Aadhaar, not required for screening"
    )

    # Clinical context
    diabetes_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="Type 1, Type 2, Gestational, etc."
    )
    diabetes_duration_years: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Years since diabetes diagnosis"
    )
    on_insulin: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hba1c_latest: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Latest HbA1c value (%)"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Facility linkage
    facility_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True,
        comment="Healthcare facility where patient was registered"
    )

    # Soft deletion & Retention
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deletion_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    screenings: Mapped[list[Screening]] = relationship(
        "Screening", back_populates="patient", cascade="all, delete-orphan"
    )
    consents: Mapped[list[ConsentRecord]] = relationship(
        "ConsentRecord", back_populates="patient", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Patient {self.id} {self.first_name} {self.last_name}>"
