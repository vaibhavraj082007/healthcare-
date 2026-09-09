"""
RetinaShield — Sync API Routes

Endpoints for facility offline→cloud synchronization.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.sync_service import sync_service

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncBatchRequest(BaseModel):
    """Batch of screening data from an offline facility."""

    facility_id: str
    screenings: list[dict]


class SyncBatchResponse(BaseModel):
    """Response to a sync batch request."""

    facility_id: str
    total_received: int
    created: int
    updated: int
    errors: list[dict]
    synced_at: str


@router.post("/batch", response_model=SyncBatchResponse)
async def sync_batch(
    request: SyncBatchRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Receive a batch of screening results from an offline facility.

    Called by the facility sync client when connectivity is available.
    """
    if not request.screenings:
        raise HTTPException(status_code=400, detail="No screenings to sync")

    result = await sync_service.receive_sync_batch(
        db=db,
        facility_id=request.facility_id,
        screenings_data=request.screenings,
    )
    return result


@router.get("/status/{facility_id}")
async def get_sync_status(
    facility_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the sync status for a facility."""
    return await sync_service.get_facility_sync_status(db, facility_id)
