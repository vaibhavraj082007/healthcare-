"""
RetinaShield — Patient ORM Model

Stores patient demographic information for DR screening.
All data handling must comply with Indian DPDP Act 2023 requirements.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import String, Date, DateTime, Integer, Boolean, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Patient(Base):
    """Patient record for diabetic retinopathy screening."""

    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Demographics (minimum necessary for screening)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Contact (for follow-up referrals)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    aadhaar_last4: Mapped[str | None] = mapped_column(
        String(4), nullable=True, comment="Last 4 digits only — never store full Aadhaar"
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
        nullable=True, comment="Latest HbA1c value (%)"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Facility linkage
    facility_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Healthcare facility where patient was registered"
    )

    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    screenings: Mapped[list["Screening"]] = relationship(
        "Screening", back_populates="patient", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Patient {self.id} {self.first_name} {self.last_name}>"
