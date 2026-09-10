"""
RetinaShield — Analysis Job ORM Model

Persists asynchronous analysis jobs tracking state transitions:
  queued -> running -> completed | failed | cancelled

Provides idempotency, timeouts, safe retry accounting, and worker metadata.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import (
    String, DateTime, Integer, Text, ForeignKey, JSON, func, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import GUID

if TYPE_CHECKING:
    from app.models.screening import Screening, ScreeningImage


class AnalysisJob(Base):
    """
    Persisted background inference job for a screening image.
    
    States:
      - 'queued': Awaiting worker execution
      - 'running': Currently being processed by worker
      - 'completed': Finished successfully with results
      - 'failed': Terminated with error (exhausted retries or non-retriable)
      - 'cancelled': Manually aborted by staff or system
    """

    __tablename__ = "analysis_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )

    screening_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("screenings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("screening_images.id", ondelete="SET NULL"), nullable=True, index=True
    )

    facility_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )

    # Idempotency token (e.g. sha256(screening_id + image_id + config_hash))
    idempotency_key: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True,
        comment="Unique idempotency token preventing duplicate job dispatch"
    )

    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="queued", index=True,
        comment="queued, running, completed, failed, cancelled"
    )

    priority: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
        comment="Queue priority (higher executes first)"
    )

    retry_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, default=2, nullable=False
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer, default=300, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    error_trace: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    worker_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Identifier of worker process handling this job"
    )

    parameters: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="Run parameters (run_matlab, run_yolo, model_path, etc.)"
    )

    result_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="Final analysis result dictionary matching AnalysisResult schema"
    )

    timings: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="Per-stage and total execution latency breakdown"
    )

    model_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="Worker adapter type, model hashes, and preprocessing versions"
    )

    # Relationships
    screening: Mapped[Screening] = relationship("Screening")
    image: Mapped[ScreeningImage | None] = relationship("ScreeningImage")

    __table_args__ = (
        Index("ix_analysis_jobs_facility_status", "facility_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<AnalysisJob {self.id} [{self.status}] retries={self.retry_count}/{self.max_retries}>"
