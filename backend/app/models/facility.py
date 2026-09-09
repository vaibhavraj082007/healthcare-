"""
RetinaShield — Facility ORM Model

Represents a healthcare facility (Primary Health Centre) that can perform
screenings, potentially in offline mode.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, Float, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Facility(Base):
    """A healthcare facility registered for DR screening."""

    __tablename__ = "facilities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Facility identification
    facility_code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False,
        comment="Unique facility code (e.g., PHC-MH-PUNE-001)"
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    facility_type: Mapped[str] = mapped_column(
        String(50), default="PHC",
        comment="PHC (Primary Health Centre), CHC, District Hospital, etc."
    )

    # Location
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district: Mapped[str | None] = mapped_column(String(100), nullable=True)
    block: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pin_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Capabilities
    has_fundus_camera: Mapped[bool] = mapped_column(Boolean, default=True)
    camera_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    has_internet: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="Whether the facility has reliable internet connectivity"
    )
    offline_capable: Mapped[bool] = mapped_column(
        Boolean, default=True,
        comment="Whether the facility can operate in offline mode"
    )

    # Contact
    contact_person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Sync status
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pending_sync_count: Mapped[int] = mapped_column(default=0)

    # Activation
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<Facility {self.facility_code} '{self.name}'>"
