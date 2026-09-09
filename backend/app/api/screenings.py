"""
RetinaShield — Screening API Routes

Screening session management and image upload.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.patient import Patient
from app.models.screening import Screening, ScreeningImage
from app.schemas.screening import ScreeningCreate, ScreeningRead, ScreeningSummary
from app.services.image_store import image_store

router = APIRouter(prefix="/api/screenings", tags=["screenings"])


@router.post("/", response_model=ScreeningRead, status_code=201)
async def create_screening(
    data: ScreeningCreate,
    db: AsyncSession = Depends(get_db),
) -> Screening:
    """Create a new screening session for a patient."""
    # Verify patient exists
    result = await db.execute(
        select(Patient).where(Patient.id == data.patient_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Patient not found")

    screening = Screening(**data.model_dump())
    db.add(screening)
    await db.flush()
    await db.refresh(screening)
    return screening


@router.get("/", response_model=list[ScreeningSummary])
async def list_screenings(
    patient_id: uuid.UUID | None = Query(None),
    facility_id: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List screenings with optional filters."""
    query = select(Screening).order_by(Screening.screened_at.desc())

    if patient_id:
        query = query.where(Screening.patient_id == patient_id)
    if facility_id:
        query = query.where(Screening.facility_id == facility_id)
    if status:
        query = query.where(Screening.status == status)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    screenings = result.scalars().all()

    # Build summaries with patient names
    summaries = []
    for s in screenings:
        patient_result = await db.execute(
            select(Patient.first_name, Patient.last_name).where(Patient.id == s.patient_id)
        )
        patient_row = patient_result.one_or_none()
        patient_name = f"{patient_row[0]} {patient_row[1]}" if patient_row else None

        summaries.append({
            "id": s.id,
            "patient_id": s.patient_id,
            "patient_name": patient_name,
            "eye": s.eye,
            "status": s.status,
            "dr_grade": s.dr_grade,
            "dr_grade_label": s.dr_grade_label,
            "referral_urgency": s.referral_urgency,
            "model_trained": s.model_trained,
            "screened_at": s.screened_at,
        })

    return summaries


@router.get("/{screening_id}", response_model=ScreeningRead)
async def get_screening(
    screening_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Screening:
    """Get a screening session with full analysis results."""
    result = await db.execute(
        select(Screening).where(Screening.id == screening_id)
    )
    screening = result.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")
    return screening


@router.post("/{screening_id}/images", status_code=201)
async def upload_fundus_image(
    screening_id: uuid.UUID,
    eye: str = Query(..., regex="^(left|right)$"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Upload a fundus image for a screening session.

    Images are stored in private storage — never directly accessible via URL.
    """
    # Verify screening exists
    result = await db.execute(
        select(Screening).where(Screening.id == screening_id)
    )
    screening = result.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    # Validate content type
    if file.content_type not in ("image/jpeg", "image/png", "image/tiff"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type: {file.content_type}. Use JPEG, PNG, or TIFF."
        )

    # Read and store image
    content = await file.read()
    try:
        store_info = await image_store.store_image(
            content, file.filename or "upload.jpg", file.content_type
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Create DB record
    image_record = ScreeningImage(
        screening_id=screening_id,
        original_filename=file.filename or "upload.jpg",
        stored_filename=store_info["stored_filename"],
        storage_path=store_info["storage_path"],
        content_type=file.content_type,
        file_size_bytes=store_info["file_size_bytes"],
        width=store_info["width"],
        height=store_info["height"],
        eye=eye,
    )
    db.add(image_record)
    await db.flush()
    await db.refresh(image_record)

    return {
        "image_id": str(image_record.id),
        "original_filename": image_record.original_filename,
        "eye": eye,
        "width": image_record.width,
        "height": image_record.height,
        "file_size_bytes": image_record.file_size_bytes,
    }


@router.get("/{screening_id}/images/{image_id}/view")
async def view_image(
    screening_id: uuid.UUID,
    image_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream a fundus image from private storage (authenticated access only)."""
    result = await db.execute(
        select(ScreeningImage).where(
            ScreeningImage.id == image_id,
            ScreeningImage.screening_id == screening_id,
        )
    )
    image_record = result.scalar_one_or_none()
    if not image_record:
        raise HTTPException(status_code=404, detail="Image not found")

    try:
        image_data = await image_store.retrieve_image(image_record.stored_filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Image file not found in storage")

    from io import BytesIO
    return StreamingResponse(
        BytesIO(image_data),
        media_type=image_record.content_type,
        headers={"Content-Disposition": f"inline; filename=\"{image_record.original_filename}\""},
    )
