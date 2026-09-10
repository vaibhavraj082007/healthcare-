"""
RetinaShield — Analysis Job Schemas

Pydantic V2 schemas for job creation, status polling, cancellation, and listings.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class JobCreateRequest(BaseModel):
    """Payload to enqueue a new inference analysis job."""
    screening_id: uuid.UUID
    image_id: uuid.UUID | None = None
    run_matlab: bool = True
    run_yolo: bool = True
    timeout_seconds: int = Field(default=300, ge=10, le=1800)
    idempotency_key: str | None = Field(
        default=None,
        description="Optional client-provided idempotency key. If omitted, generated from screening+image."
    )

    model_config = ConfigDict(extra="ignore")


class JobReadResponse(BaseModel):
    """Full detail view of an analysis job."""
    id: uuid.UUID
    screening_id: uuid.UUID
    image_id: uuid.UUID | None = None
    facility_id: str | None = None
    idempotency_key: str
    status: JobStatus
    priority: int = 0
    retry_count: int = 0
    max_retries: int = 2
    timeout_seconds: int = 300
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    worker_id: str | None = None
    parameters: dict[str, Any] | None = None
    result: dict[str, Any] | None = Field(default=None, alias="result_json")
    timings: dict[str, Any] | None = None
    model_metadata: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class JobListResponse(BaseModel):
    """Paginated collection of jobs."""
    items: list[JobReadResponse]
    total: int
    page: int
    page_size: int

    model_config = ConfigDict(from_attributes=True)


class JobCancelResponse(BaseModel):
    """Response returned when cancelling a job."""
    job_id: uuid.UUID
    status: str
    message: str

    model_config = ConfigDict(from_attributes=True)
