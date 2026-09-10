"""
RetinaShield — Operational Monitoring & Interoperability API Routes

Endpoints:
    GET  /api/monitoring/operational           — Operational metrics with privacy-preserving suppression
    GET  /api/monitoring/shifts                — Input-quality & prediction-distribution shifts
    GET  /api/monitoring/interop/status        — ABDM / FHIR capabilities, status & remaining requirements
    GET  /api/monitoring/interop/export/{id}   — Export screening as HL7 FHIR R4 Document Bundle JSON
    POST /api/monitoring/interop/exchange/test — Test live ABDM exchange readiness (safeguard check)
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.screening import Screening, ScreeningImage
from app.models.patient import Patient
from app.models.clinical import QualityResult, ModelOutput, ClinicianReview
from app.models.user import User
from app.api.deps import get_current_user
from app.schemas.monitoring import (
    OperationalMetricsResponse,
    ShiftMonitoringResponse,
)
from app.schemas.interop import (
    InteropStatusResponse,
    FHIRBundleExportResponse,
    ExchangeTestResponse,
)
from app.services.monitoring_service import monitoring_service
from app.services.fhir_adapter import fhir_adapter

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/operational", response_model=OperationalMetricsResponse)
async def get_operational_metrics(
    facility_id: Optional[str] = Query(None, description="Optional facility filter"),
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OperationalMetricsResponse:
    """
    Retrieve operational metrics calculated from actual stored events and results.
    Includes volume, ungradeable rates, review backlog, processing and synchronization
    failures, latency, and model-version usage.
    
    Small cell counts (< 5) are automatically suppressed to protect patient privacy.
    Maintains a strict boundary separating operational metrics from clinical model accuracy.
    """
    return await monitoring_service.get_operational_metrics(
        session=db,
        facility_id=facility_id,
        time_window_days=days,
    )


@router.get("/shifts", response_model=ShiftMonitoringResponse)
async def get_shift_metrics(
    current_days: int = Query(7, ge=1, le=90, description="Current evaluation window in days"),
    baseline_days: int = Query(30, ge=7, le=365, description="Historical baseline window in days"),
    facility_id: Optional[str] = Query(None, description="Optional facility filter"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShiftMonitoringResponse:
    """
    Monitor input-quality and prediction-distribution shifts over time.
    
    CRITICAL REGULATORY NOTICE:
    Shifts do NOT prove clinical performance drift, nor do they prove model degradation.
    Autonomous retraining from unverified AI outputs is STRICTLY PROHIBITED.
    Model updates require expert-reviewed data and controlled offline evaluation.
    """
    return await monitoring_service.get_shift_metrics(
        session=db,
        current_days=current_days,
        baseline_days=baseline_days,
        facility_id=facility_id,
    )


@router.get("/interop/status", response_model=InteropStatusResponse)
async def get_interoperability_status(
    current_user: User = Depends(get_current_user),
) -> InteropStatusResponse:
    """
    Retrieve ABDM & FHIR R4 interoperability status, supported NRCeS profile mappings,
    and remaining integration requirements.
    
    Shows that ABHA linking and live ABDM exchange are safely disabled by default.
    """
    return fhir_adapter.get_interop_status()


@router.get("/interop/export/{screening_id}", response_model=FHIRBundleExportResponse)
async def export_screening_fhir_bundle(
    screening_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FHIRBundleExportResponse:
    """
    Export a screening session as a structured HL7 FHIR R4 / ABDM NRCeS Document Bundle JSON.
    Encapsulates Composition (DiagnosticReportRecord), DiagnosticReport (DiagnosticReportImaging),
    Observations (DR stage, IQA, Macular Edema), and Media (with SHA-256 integrity hash).
    
    National ID (Aadhaar / ABHA) is NOT mandatory. Unreviewed screenings are clearly
    marked as provisional research results.
    """
    # Fetch screening with relationships
    query = (
        select(Screening)
        .options(
            selectinload(Screening.images),
            selectinload(Screening.clinician_review),
        )
        .where(Screening.id == screening_id, Screening.is_deleted.is_(False))
    )
    res = await db.execute(query)
    screening = res.scalar_one_or_none()

    if not screening:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Screening '{screening_id}' not found",
        )

    # Fetch patient
    p_res = await db.execute(select(Patient).where(Patient.id == screening.patient_id))
    patient = p_res.scalar_one_or_none()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Patient '{screening.patient_id}' not found",
        )

    # Fetch image and provenance if available
    image: Optional[ScreeningImage] = screening.images[0] if screening.images else None

    # Fetch quality result
    q_res = await db.execute(
        select(QualityResult).where(QualityResult.screening_id == screening.id)
    )
    quality = q_res.scalars().first()

    # Fetch model output
    mo_res = await db.execute(
        select(ModelOutput).where(ModelOutput.screening_id == screening.id)
    )
    model_output = mo_res.scalars().first()

    # Clinician review
    review = screening.clinician_review

    return fhir_adapter.generate_bundle(
        screening=screening,
        patient=patient,
        image=image,
        quality=quality,
        model_output=model_output,
        review=review,
    )


@router.post("/interop/exchange/test", response_model=ExchangeTestResponse)
async def test_abdm_exchange(
    current_user: User = Depends(get_current_user),
) -> ExchangeTestResponse:
    """
    Test live ABDM exchange readiness.
    Verifies prerequisite safeguards (client credentials, HIP registration, Consent Manager flows).
    Returns blocked status if live exchange is disabled or prerequisites are unfulfilled.
    """
    return fhir_adapter.test_exchange_readiness()
