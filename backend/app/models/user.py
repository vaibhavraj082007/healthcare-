"""
RetinaShield — User & Staff ORM Model

Represents health workers, ophthalmologists, and administrators.
Staff provisioning and privileged role assignment are strictly administrator-controlled.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, DateTime, Boolean, Enum, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import GUID

if TYPE_CHECKING:
    from app.models.facility import Facility
    from app.models.consent import ConsentRecord
    from app.models.clinical import ClinicianReview, Report


class UserRole(str, enum.Enum):
    """Staff roles within RetinaShield."""
    HEALTH_WORKER = "health-worker"
    OPHTHALMOLOGIST = "ophthalmologist"
    ADMINISTRATOR = "administrator"


class User(Base):
    """Staff user account for PHC health-workers, ophthalmologists, and admins."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )

    username: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=UserRole.HEALTH_WORKER,
        index=True,
    )

    facility_id: Mapped[str | None] = mapped_column(
        String(100),
        ForeignKey("facilities.facility_code", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Facility code where the staff member is stationed",
    )

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    facility: Mapped[Facility | None] = relationship("Facility", back_populates="staff_members")
    reviews: Mapped[list[ClinicianReview]] = relationship(
        "ClinicianReview",
        foreign_keys="ClinicianReview.reviewer_id",
        back_populates="reviewer",
    )
    signed_reports: Mapped[list[Report]] = relationship("Report", foreign_keys="Report.signed_by_id", back_populates="signed_by")

    def __repr__(self) -> str:
        return f"<User {self.username} role={self.role.value} facility={self.facility_id}>"
