"""
RetinaShield — Audit Event ORM Model

Records security, access, role changes, and data export events.
Keeps sensitive patient content OUT of the audit records to comply with DPDP Act.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import GUID


class AuditEvent(Base):
    """Immutable audit trail for security, authentication, and data access."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    facility_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )

    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="e.g. login_success, login_failure, view_patient, view_image, export_report, role_change"
    )
    resource_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="e.g. user, patient, screening, image, report"
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )

    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Details dictionary — MUST NOT contain plain passwords, full Aadhaar, or sensitive patient PII
    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="Sanitized event metadata (no patient names or secrets)"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    def __repr__(self) -> str:
        return f"<AuditEvent {self.event_type} user={self.user_id} resource={self.resource_type}:{self.resource_id}>"
