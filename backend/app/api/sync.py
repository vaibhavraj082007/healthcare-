"""
RetinaShield — Sync API Routes

Endpoints for offline facility → cloud synchronisation.

Endpoints:
    POST   /api/sync/batch                             — legacy batch upsert
    POST   /api/sync/encounter                         — single encounter upsert (idempotent)
    PATCH  /api/sync/encounter/{id}/image-chunk        — chunked image upload
    GET    /api/sync/encounter/{id}/upload-status      — partial-upload resume query
    GET    /api/sync/status/{facility_id}              — facility sync dashboard
    GET    /api/sync/conflicts                         — list unresolved conflicts
    GET    /api/sync/conflicts/{conflict_id}           — single conflict detail
    POST   /api/sync/conflicts/{conflict_id}/resolve   — human conflict resolution

Authentication:
    All endpoints require a valid Bearer token.  In production this should be
    a facility-specific service account token, not a clinician session token.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.sync_service import sync_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sync", tags=["sync"])


# ── Request / response models ─────────────────────────────────────────────────

class SyncBatchRequest(BaseModel):
    facility_id: str
    screenings: list[dict]


class SyncBatchResponse(BaseModel):
    facility_id: str
    total_received: int
    created: int
    updated: int
    errors: list[dict]
    synced_at: str


class EncounterSyncPayload(BaseModel):
    local_encounter_id: str
    patient_id: str | None = None
    facility_id: str
    eye: str = "unknown"
    image_sha256: str | None = None
    analysis_result: dict | None = None
    consent_recorded: bool = False
    clinician_approved_locally: bool = False
    created_at: str | None = None
    processed_at: str | None = None


class ConflictResolveRequest(BaseModel):
    resolution: str  # 'keep_server' | 'keep_facility' | 'manual_merge' | 'escalated'
    notes: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/batch", response_model=SyncBatchResponse)
async def sync_batch(
    request: SyncBatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Receive a batch of screening results from an offline facility.

    Legacy endpoint — prefer /encounter for new integrations.
    """
    if not request.screenings:
        raise HTTPException(status_code=400, detail="No screenings to sync.")

    result = await sync_service.receive_sync_batch(
        db=db,
        facility_id=request.facility_id,
        screenings_data=request.screenings,
    )
    return result


@router.post("/encounter")
async def sync_encounter(
    payload: EncounterSyncPayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_idempotency_key: Annotated[str | None, Header()] = None,
) -> dict:
    """
    Upsert a single encounter from a facility.

    - Idempotent: re-submitting the same `local_encounter_id` returns the
      original result without creating a duplicate.
    - Conflict: returns HTTP 409 if the incoming payload disagrees with a
      clinician-approved record already on the server.
    - Checksum: server echoes `image_sha256` so the client can verify integrity.
    """
    # Honour explicit idempotency key header if provided
    data = payload.model_dump()
    if x_idempotency_key and not data.get("local_encounter_id"):
        data["local_encounter_id"] = x_idempotency_key

    result = await sync_service.receive_encounter(db=db, payload=data)

    if result.get("status") == "conflict":
        raise HTTPException(
            status_code=409,
            detail=result,
        )

    return result


@router.patch("/encounter/{encounter_id}/image-chunk")
async def upload_image_chunk(
    encounter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    content_range: Annotated[str | None, Header()] = None,
    x_image_sha256: Annotated[str | None, Header()] = None,
    x_facility_id: Annotated[str | None, Header()] = None,
) -> dict:
    """
    Upload a single chunk of a fundus image using Content-Range.

    Supports partial-upload resume: if a previous chunk upload was interrupted,
    the client queries /upload-status first to get the confirmed offset, then
    re-sends from that offset.

    Content-Range format: bytes <start>-<end>/<total>
    """
    chunk_data = await request.body()

    if not content_range:
        raise HTTPException(status_code=400, detail="Content-Range header required.")
    if not x_image_sha256:
        raise HTTPException(status_code=400, detail="X-Image-SHA256 header required.")

    # Parse Content-Range: bytes 0-2047/10240
    try:
        range_part, total_str = content_range.removeprefix("bytes ").split("/")
        start_str, end_str = range_part.split("-")
        offset = int(start_str)
        total_bytes = int(total_str)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid Content-Range: {content_range}")

    try:
        result = await sync_service.append_chunk(
            db=db,
            encounter_id=encounter_id,
            chunk_data=chunk_data,
            offset=offset,
            sha256_expected=x_image_sha256,
            facility_id=x_facility_id or "unknown",
            expected_bytes=total_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    status_code = 200 if result["complete"] else 206
    from fastapi.responses import JSONResponse
    return JSONResponse(content=result, status_code=status_code)


@router.get("/encounter/{encounter_id}/upload-status")
async def get_upload_status(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Return how many bytes the server has already received for this encounter's
    image, so the client can resume a partial upload from the correct offset.
    """
    return await sync_service.get_upload_status(db=db, encounter_id=encounter_id)


@router.get("/status/{facility_id}")
async def get_sync_status(
    facility_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get sync dashboard statistics for a facility."""
    return await sync_service.get_facility_sync_status(db, facility_id)


@router.get("/conflicts")
async def list_conflicts(
    facility_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """
    List all unresolved sync conflicts.

    Conflicts require human review — clinician-approved records are NEVER
    silently overwritten by incoming facility data.
    """
    return await sync_service.list_conflicts(db, facility_id=facility_id)


@router.get("/conflicts/{conflict_id}")
async def get_conflict(
    conflict_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return detail for a single unresolved conflict."""
    conflicts = await sync_service.list_conflicts(db)
    for c in conflicts:
        if c["id"] == conflict_id:
            return c
    raise HTTPException(status_code=404, detail="Conflict not found.")


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(
    conflict_id: str,
    body: ConflictResolveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Record a human resolution decision for a sync conflict.

    Valid resolutions:
        keep_server    — discard facility data, keep server record
        keep_facility  — overwrite server record with facility data
        manual_merge   — clinician will manually reconcile
        escalated      — escalate to supervising clinician
    """
    valid = {"keep_server", "keep_facility", "manual_merge", "escalated"}
    if body.resolution not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"resolution must be one of: {sorted(valid)}",
        )

    try:
        return await sync_service.resolve_conflict(
            db=db,
            conflict_id=conflict_id,
            resolution=body.resolution,
            notes=body.notes,
            resolved_by_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
