"""
RetinaShield — Patient API Routes

CRUD operations for minimal patient records complying with Indian DPDP Act 2023.
- No mandatory Aadhaar or ABHA identifiers for basic screening.
- Facility scoping and authorized reviewer access control.
- Soft-deletion with statutory retention tracking.
- Immutable security audit logging.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    require_health_worker,
    verify_facility_access,
    log_audit_event,
)
from app.db.session import get_db
from app.models.patient import Patient
from app.models.screening import Screening
from app.models.user import User, UserRole
from app.schemas.patient import PatientCreate, PatientRead, PatientUpdate

router = APIRouter(prefix="/api/patients", tags=["patients"])


@router.post("/", response_model=PatientRead, status_code=status.HTTP_201_CREATED)
async def create_patient(
    data: PatientCreate,
    request: Request,
    current_user: User = Depends(require_health_worker),
    db: AsyncSession = Depends(get_db),
) -> Patient:
    """
    Register a new patient for DR screening.
    No Aadhaar or ABHA identifier is required.
    """
    patient_dict = data.model_dump()

    # If facility_id is not supplied or user is a health-worker, enforce their assigned facility
    user_role_val = (
        current_user.role.value
        if isinstance(current_user.role, UserRole)
        else str(current_user.role)
    )
    if user_role_val == UserRole.HEALTH_WORKER.value:
        patient_dict["facility_id"] = current_user.facility_id
    elif not patient_dict.get("facility_id"):
        patient_dict["facility_id"] = current_user.facility_id

    patient = Patient(**patient_dict)
    db.add(patient)
    await db.flush()
    await db.refresh(patient)

    await log_audit_event(
        db=db,
        event_type="patient_registered",
        resource_type="patient",
        user=current_user,
        facility_id=patient.facility_id,
        resource_id=str(patient.id),
        details={"has_phone": bool(patient.phone), "has_aadhaar_last4": bool(patient.aadhaar_last4)},
        request=request,
    )

    return patient


@router.get("/", response_model=list[PatientRead])
async def list_patients(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str | None = Query(None, description="Search by name"),
    facility_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Sequence[Patient]:
    """List non-deleted patients with role-based facility filtering."""
    query = select(Patient).where(Patient.is_deleted == False).order_by(Patient.created_at.desc())

    user_role_val = (
        current_user.role.value
        if isinstance(current_user.role, UserRole)
        else str(current_user.role)
    )

    # Health worker can only see patients from their assigned facility
    if user_role_val == UserRole.HEALTH_WORKER.value:
        if current_user.facility_id:
            query = query.where(Patient.facility_id == current_user.facility_id)
    elif facility_id:
        query = query.where(Patient.facility_id == facility_id)

    if search:
        search_term = f"%{search}%"
        query = query.where(
            (Patient.first_name.ilike(search_term))
            | (Patient.last_name.ilike(search_term))
        )

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{patient_id}", response_model=PatientRead)
async def get_patient(
    patient_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Patient:
    """Get a single patient by ID with facility access verification."""
    result = await db.execute(
        select(Patient).where(Patient.id == patient_id, Patient.is_deleted == False)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    verify_facility_access(current_user, patient.facility_id)

    await log_audit_event(
        db=db,
        event_type="patient_accessed",
        resource_type="patient",
        user=current_user,
        facility_id=patient.facility_id,
        resource_id=str(patient.id),
        request=request,
    )

    return patient


@router.patch("/{patient_id}", response_model=PatientRead)
async def update_patient(
    patient_id: uuid.UUID,
    data: PatientUpdate,
    request: Request,
    current_user: User = Depends(require_health_worker),
    db: AsyncSession = Depends(get_db),
) -> Patient:
    """Update patient details."""
    result = await db.execute(
        select(Patient).where(Patient.id == patient_id, Patient.is_deleted == False)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    verify_facility_access(current_user, patient.facility_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(patient, field, value)

    await db.flush()
    await db.refresh(patient)

    await log_audit_event(
        db=db,
        event_type="patient_updated",
        resource_type="patient",
        user=current_user,
        facility_id=patient.facility_id,
        resource_id=str(patient.id),
        details={"updated_fields": list(update_data.keys())},
        request=request,
    )

    return patient


@router.delete("/{patient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient(
    patient_id: uuid.UUID,
    request: Request,
    reason: str = Query("Patient requested deletion / consent withdrawn"),
    current_user: User = Depends(require_health_worker),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft delete a patient record (maintains statutory audit trail)."""
    result = await db.execute(
        select(Patient).where(Patient.id == patient_id, Patient.is_deleted == False)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    verify_facility_access(current_user, patient.facility_id)

    patient.is_deleted = True
    patient.deleted_at = datetime.now(timezone.utc)
    patient.deletion_reason = reason

    await log_audit_event(
        db=db,
        event_type="patient_soft_deleted",
        resource_type="patient",
        user=current_user,
        facility_id=patient.facility_id,
        resource_id=str(patient.id),
        details={"reason": reason},
        request=request,
    )
