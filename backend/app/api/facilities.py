"""
RetinaShield — Facility Management API

Handles healthcare facility registration, details, and listing.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.facility import Facility
from app.models.user import User

router = APIRouter(prefix="/api/facilities", tags=["facilities"])


class FacilityCreate(BaseModel):
    facility_code: str = Field(..., min_length=3, max_length=100)
    name: str = Field(..., min_length=2, max_length=300)
    facility_type: str = "PHC"
    state: str | None = None
    district: str | None = None
    block: str | None = None
    pin_code: str | None = None
    has_fundus_camera: bool = True
    camera_model: str | None = None
    has_internet: bool = False
    offline_capable: bool = True
    contact_person: str | None = None
    contact_phone: str | None = None
    notes: str | None = None


class FacilityRead(FacilityCreate):
    id: uuid.UUID
    is_active: bool
    pending_sync_count: int = 0

    class Config:
        from_attributes = True


@router.post("/", response_model=FacilityRead, status_code=status.HTTP_201_CREATED)
async def register_facility(
    data: FacilityCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Facility:
    """Register a new healthcare facility (Administrator only)."""
    existing = await db.execute(
        select(Facility).where(Facility.facility_code == data.facility_code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Facility code '{data.facility_code}' is already registered",
        )

    facility = Facility(**data.model_dump())
    db.add(facility)
    await db.flush()
    await db.refresh(facility)
    return facility


@router.get("/", response_model=list[FacilityRead])
async def list_facilities(
    is_active: bool | None = Query(True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Sequence[Facility]:
    """List registered healthcare facilities (All authenticated staff)."""
    query = select(Facility).order_by(Facility.name.asc())
    if is_active is not None:
        query = query.where(Facility.is_active == is_active)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{facility_code}", response_model=FacilityRead)
async def get_facility(
    facility_code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Facility:
    """Get details of a specific facility by code."""
    result = await db.execute(
        select(Facility).where(Facility.facility_code == facility_code)
    )
    facility = result.scalar_one_or_none()
    if not facility:
        raise HTTPException(status_code=404, detail="Facility not found")
    return facility
