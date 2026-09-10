"""
RetinaShield — Background Analysis Job API Routes

Provides endpoints for dispatching, monitoring, and cancelling asynchronous
MATLAB inference jobs with full persistence and audit logging.
"""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    require_health_worker,
    verify_facility_access,
    log_audit_event,
)
from app.db.session import get_db
from app.models.job import AnalysisJob
from app.models.screening import Screening
from app.models.user import User
from app.schemas.job import (
    JobCreateRequest,
    JobReadResponse,
    JobListResponse,
    JobCancelResponse,
)
from app.services.job_queue import job_queue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/", response_model=JobReadResponse, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_analysis_job(
    data: JobCreateRequest,
    request: Request,
    current_user: User = Depends(require_health_worker),
    db: AsyncSession = Depends(get_db),
) -> AnalysisJob:
    """
    Enqueue an asynchronous fundus analysis job.
    Enforces idempotency and facility authorization.
    """
    # Verify screening exists
    stmt = select(Screening).where(Screening.id == data.screening_id)
    screening = (await db.execute(stmt)).scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    if screening.facility_id:
        verify_facility_access(current_user, screening.facility_id)

    job = await job_queue.submit_job(
        screening_id=data.screening_id,
        image_id=data.image_id,
        facility_id=screening.facility_id,
        run_matlab=data.run_matlab,
        run_yolo=data.run_yolo,
        timeout_seconds=data.timeout_seconds,
        idempotency_key=data.idempotency_key,
    )

    await log_audit_event(
        db=db,
        event_type="JOB_ENQUEUED",
        resource_type="analysis_job",
        user=current_user,
        resource_id=str(job.id),
        facility_id=screening.facility_id,
        request=request,
        details={
            "screening_id": str(screening.id),
            "image_id": str(data.image_id) if data.image_id else None,
            "idempotency_key": job.idempotency_key,
            "timeout_seconds": job.timeout_seconds,
        },
    )

    return job


@router.get("/{job_id}", response_model=JobReadResponse)
async def get_job_status(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisJob:
    """Retrieve detailed status, timings, and results of an analysis job."""
    stmt = select(AnalysisJob).where(AnalysisJob.id == job_id)
    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Analysis job not found")

    if job.facility_id:
        verify_facility_access(current_user, job.facility_id)

    return job


@router.post("/{job_id}/cancel", response_model=JobCancelResponse)
async def cancel_analysis_job(
    job_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_health_worker),
    db: AsyncSession = Depends(get_db),
) -> JobCancelResponse:
    """Abort an in-flight or queued analysis job."""
    stmt = select(AnalysisJob).where(AnalysisJob.id == job_id)
    job = (await db.execute(stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Analysis job not found")

    if job.facility_id:
        verify_facility_access(current_user, job.facility_id)

    if job.status in ("completed", "failed"):
        return JobCancelResponse(
            job_id=job.id,
            status=job.status,
            message=f"Job cannot be cancelled because it is already {job.status}.",
        )

    success = await job_queue.cancel_job(job_id)

    await log_audit_event(
        db=db,
        event_type="JOB_CANCELLED",
        resource_type="analysis_job",
        user=current_user,
        resource_id=str(job.id),
        facility_id=job.facility_id,
        request=request,
        details={"previous_status": job.status},
    )


    return JobCancelResponse(
        job_id=job.id,
        status="cancelled" if success else job.status,
        message="Job successfully cancelled." if success else "Failed to cancel job.",
    )


@router.get("/", response_model=JobListResponse)
async def list_jobs(
    screening_id: uuid.UUID | None = None,
    facility_id: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobListResponse:
    """List analysis jobs filtered by facility, screening, or status."""
    effective_facility = facility_id
    if current_user.role.value != "ADMINISTRATOR" and current_user.facility_id:
        effective_facility = current_user.facility_id

    query = select(AnalysisJob)
    count_query = select(func.count(AnalysisJob.id))

    if screening_id:
        query = query.where(AnalysisJob.screening_id == screening_id)
        count_query = count_query.where(AnalysisJob.screening_id == screening_id)
    if effective_facility:
        query = query.where(AnalysisJob.facility_id == effective_facility)
        count_query = count_query.where(AnalysisJob.facility_id == effective_facility)
    if status_filter:
        query = query.where(AnalysisJob.status == status_filter)
        count_query = count_query.where(AnalysisJob.status == status_filter)

    total_res = await db.execute(count_query)
    total = total_res.scalar_one() or 0

    query = query.order_by(AnalysisJob.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    items_res = await db.execute(query)
    items = list(items_res.scalars().all())

    return JobListResponse(
        items=[JobReadResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )
