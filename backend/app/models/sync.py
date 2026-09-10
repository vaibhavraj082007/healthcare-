"""
RetinaShield — Sync ORM Models

Tables supporting offline→cloud synchronisation:
    SyncIdempotencyKey    — deduplication table; prevents double-processing
    SyncConflict          — human-reviewable conflict log
    ChunkedUploadSession  — tracks partial image uploads for resume
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import GUID

if __name__ == "typing":
    from app.models.user import User


class SyncIdempotencyKey(Base):
    """
    Prevents a facility from creating duplicate records when it retries a
    failed upload.

    The `key` is the `local_encounter_id` sent by the facility as
    `X-Idempotency-Key`.  If a row with the same key already exists,
    the server returns the original result rather than creating a new record.
    """

    __tablename__ = "sync_idempotency_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    key: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True,
        comment="local_encounter_id from the facility"
    )
    facility_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    result_screening_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True,
        comment="ID of the Screening record created or updated"
    )
    result_status: Mapped[str] = mapped_column(
        String(30), default="created",
        comment="'created', 'updated', 'rejected', 'conflict'"
    )

    def __repr__(self) -> str:
        return (
            f"<SyncIdempotencyKey key={self.key[:12]}... "
            f"status={self.result_status}>"
        )


class SyncConflict(Base):
    """
    Immutable conflict record created when an incoming facility sync disagrees
    with a clinician-approved record that already exists on the server.

    Clinician-approved records are NEVER silently overwritten.  This table
    surfaces the conflict for human resolution.
    """

    __tablename__ = "sync_conflicts"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    screening_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True, index=True,
        comment="Server-side Screening.id (if it exists)"
    )
    local_encounter_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    facility_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    conflict_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="'grade_mismatch', 'referral_mismatch', 'approved_overwrite_attempt', 'checksum_mismatch'"
    )
    local_data_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="Facility-side payload that triggered the conflict"
    )
    server_data_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="Snapshot of server record at conflict time"
    )

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolution: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="'keep_server', 'keep_facility', 'manual_merge', 'escalated'"
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<SyncConflict encounter={self.local_encounter_id[:12]} "
            f"type={self.conflict_type} resolved={self.resolved_at is not None}>"
        )


class ChunkedUploadSession(Base):
    """
    Tracks a multi-chunk image upload so it can be resumed after interruption.

    Chunks are stored in a temporary staging directory on the server.
    When `received_bytes == expected_bytes` and the SHA-256 matches,
    the session is marked complete and the image is committed to permanent
    storage.
    """

    __tablename__ = "chunked_upload_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    encounter_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True,
        comment="local_encounter_id from the facility"
    )
    facility_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    expected_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    received_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    sha256_expected: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="SHA-256 the facility computed over raw image bytes"
    )
    sha256_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    staging_path: Mapped[str | None] = mapped_column(
        String(1000), nullable=True,
        comment="Absolute path to the reassembled temp file on the server"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        pct = (
            f"{self.received_bytes / self.expected_bytes * 100:.0f}%"
            if self.expected_bytes
            else "?"
        )
        return (
            f"<ChunkedUploadSession encounter={self.encounter_id[:12]} "
            f"{pct} verified={self.sha256_verified}>"
        )
