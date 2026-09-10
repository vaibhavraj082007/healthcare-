"""
RetinaShield — Consent Management API

Handles patient screening and tele-ophthalmology consent tracking,
including withdrawal of consent under the Indian DPDP Act 2023.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    require_health_worker,
    verify_facility_access,
    log_audit_event,
)
from app.db.session import get_db
from app.models.consent import ConsentRecord
from app.models.patient import Patient
from app.models.user import User
from app.schemas.consent import ConsentCreate, ConsentRead, ConsentWithdraw

router = APIRouter(prefix="/api/consent", tags=["consent"])


@router.post("/", response_model=ConsentRead, status_code=status.HTTP_201_CREATED)
async def record_consent(
    data: ConsentCreate,
    request: Request,
    current_user: User = Depends(require_health_worker),
    db: AsyncSession = Depends(get_db),
) -> ConsentRecord:
    """Record informed screening consent for a patient."""
    result = await db.execute(
        select(Patient).where(Patient.id == data.patient_id, Patient.is_deleted == False)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    verify_facility_access(current_user, patient.facility_id)

    consent = ConsentRecord(
        patient_id=data.patient_id,
        consent_type=data.consent_type,
        granted=data.granted,
        obtained_by_name=data.obtained_by_name or current_user.full_name,
        witness_name=data.witness_name,
        notes=data.notes,
    )
    db.add(consent)
    await db.flush()
    await db.refresh(consent)

    await log_audit_event(
        db=db,
        event_type="consent_recorded",
        resource_type="consent",
        user=current_user,
        facility_id=patient.facility_id,
        resource_id=str(consent.id),
        details={"patient_id": str(patient.id), "consent_type": data.consent_type},
        request=request,
    )

    return consent


@router.get("/patient/{patient_id}", response_model=list[ConsentRead])
async def get_patient_consents(
    patient_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Sequence[ConsentRecord]:
    """Retrieve all consent records for a specific patient."""
    result = await db.execute(
        select(Patient).where(Patient.id == patient_id, Patient.is_deleted == False)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    verify_facility_access(current_user, patient.facility_id)

    consent_result = await db.execute(
        select(ConsentRecord)
        .where(ConsentRecord.patient_id == patient_id)
        .order_by(ConsentRecord.consent_date.desc())
    )
    return consent_result.scalars().all()


@router.post("/{consent_id}/withdraw", response_model=ConsentRead)
async def withdraw_consent(
    consent_id: uuid.UUID,
    data: ConsentWithdraw,
    request: Request,
    current_user: User = Depends(require_health_worker),
    db: AsyncSession = Depends(get_db),
) -> ConsentRecord:
    """Withdraw a previously granted consent record (DPDP Act compliance)."""
    result = await db.execute(
        select(ConsentRecord).where(ConsentRecord.id == consent_id)
    )
    consent = result.scalar_one_or_none()
    if not consent:
        raise HTTPException(status_code=404, detail="Consent record not found")

    patient = await db.get(Patient, consent.patient_id)
    if patient:
        verify_facility_access(current_user, patient.facility_id)

    consent.withdrawn = True
    consent.withdrawn_at = datetime.now(timezone.utc)
    consent.withdrawal_reason = data.withdrawal_reason

    await db.flush()
    await db.refresh(consent)

    await log_audit_event(
        db=db,
        event_type="consent_withdrawn",
        resource_type="consent",
        user=current_user,
        facility_id=patient.facility_id if patient else None,
        resource_id=str(consent.id),
        details={"patient_id": str(consent.patient_id), "reason": data.withdrawal_reason},
        request=request,
    )

    return consent
