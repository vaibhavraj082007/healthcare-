"""
RetinaShield — Screening API Routes

Screening session management, secure fundus image upload, and private streaming.
Images are never served as static public files — access is authenticated and
facility-verified.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import cv2
import numpy as np

from app.api.deps import (
    get_current_user,
    require_health_worker,
    verify_facility_access,
    log_audit_event,
)
from app.db.session import get_db
from app.models.patient import Patient
from app.models.screening import Screening, ScreeningImage
from app.models.clinical import ImageProvenance, QualityResult
from app.models.user import User, UserRole
from app.schemas.screening import ScreeningCreate, ScreeningRead, ScreeningSummary
from app.services.image_store import image_store, ImageValidationError
from app.services.matlab_bridge import matlab_bridge


router = APIRouter(prefix="/api/screenings", tags=["screenings"])


@router.post("/", response_model=ScreeningRead, status_code=status.HTTP_201_CREATED)
async def create_screening(
    data: ScreeningCreate,
    request: Request,
    current_user: User = Depends(require_health_worker),
    db: AsyncSession = Depends(get_db),
) -> Screening:
    """Create a new screening encounter for a patient."""
    result = await db.execute(
        select(Patient).where(Patient.id == data.patient_id, Patient.is_deleted == False)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    verify_facility_access(current_user, patient.facility_id)

    screening_dict = data.model_dump()
    if not screening_dict.get("facility_id"):
        screening_dict["facility_id"] = patient.facility_id or current_user.facility_id
    screening_dict["screener_id"] = current_user.id
    screening_dict["screener_name"] = current_user.full_name

    screening = Screening(**screening_dict)
    db.add(screening)
    await db.flush()
    await db.refresh(screening)

    await log_audit_event(
        db=db,
        event_type="screening_created",
        resource_type="screening",
        user=current_user,
        facility_id=screening.facility_id,
        resource_id=str(screening.id),
        details={"eye": data.eye, "patient_id": str(patient.id)},
        request=request,
    )

    return screening


@router.get("/", response_model=list[ScreeningSummary])
async def list_screenings(
    patient_id: uuid.UUID | None = Query(None),
    facility_id: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List screening sessions with role and facility filtering."""
    query = (
        select(Screening)
        .where(Screening.is_deleted == False)
        .order_by(Screening.screened_at.desc())
    )

    user_role_val = (
        current_user.role.value
        if isinstance(current_user.role, UserRole)
        else str(current_user.role)
    )

    # Health worker is restricted to their facility
    if user_role_val == UserRole.HEALTH_WORKER.value:
        if current_user.facility_id:
            query = query.where(Screening.facility_id == current_user.facility_id)
    elif facility_id:
        query = query.where(Screening.facility_id == facility_id)

    if patient_id:
        query = query.where(Screening.patient_id == patient_id)
    if status:
        query = query.where(Screening.status == status)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    screenings = result.scalars().all()

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
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Screening:
    """Get full details of a screening session."""
    result = await db.execute(
        select(Screening).where(Screening.id == screening_id, Screening.is_deleted == False)
    )
    screening = result.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    verify_facility_access(current_user, screening.facility_id)

    await log_audit_event(
        db=db,
        event_type="screening_accessed",
        resource_type="screening",
        user=current_user,
        facility_id=screening.facility_id,
        resource_id=str(screening.id),
        request=request,
    )

    return screening


@router.post("/{screening_id}/images", status_code=status.HTTP_201_CREATED)
async def upload_fundus_image(
    screening_id: uuid.UUID,
    request: Request,
    eye: str = Query(..., description="Eye laterality: 'left' or 'right'"),
    lens_type: str = Query("20D_condensing", description="Ophthalmic condensing lens specification"),
    camera_model: str | None = Query("Smartphone + 20D Condensing Lens"),
    file: UploadFile = File(...),
    current_user: User = Depends(require_health_worker),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Upload a fundus image captured using a smartphone mounted with a 20D ophthalmic
    condensing lens (validated mobile indirect ophthalmoscopy setup).
    Validates magic bytes, dimensions, and size limits, performs immediate 20D lens IQA,
    and returns actionable recapture guidance while immutably preserving recapture history.
    """
    if not eye or eye.lower() not in ("left", "right"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Eye laterality must be explicitly specified as 'left' or 'right'",
        )
    eye = eye.lower()

    result = await db.execute(
        select(Screening).where(Screening.id == screening_id, Screening.is_deleted == False)
    )
    screening = result.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    verify_facility_access(current_user, screening.facility_id)

    content = await file.read()
    try:
        store_info = await image_store.store_image(
            file_content=content,
            original_filename=file.filename or "upload.jpg",
            content_type=file.content_type or "image/jpeg",
        )
    except ImageValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to store image: {e}")

    # Create image record
    image_record = ScreeningImage(
        screening_id=screening_id,
        original_filename=file.filename or "upload.jpg",
        stored_filename=store_info["stored_filename"],
        storage_path=store_info["storage_path"],
        content_type=store_info["content_type"],
        file_size_bytes=store_info["file_size_bytes"],
        width=store_info["width"],
        height=store_info["height"],
        eye=eye,
        sha256_hash=store_info["sha256_hash"],
    )
    db.add(image_record)
    await db.flush()
    await db.refresh(image_record)

    # Create provenance record with 20D condensing lens specification
    provenance = ImageProvenance(
        image_id=image_record.id,
        camera_model=camera_model,
        lens_type=lens_type,
        sha256_hash=store_info["sha256_hash"],
        capture_timestamp=datetime.now(timezone.utc),
    )
    db.add(provenance)

    # --- Run Immediate 20D Optical Quality Assessment ---
    recapture_guidance: list[str] = []
    qa_verdict = "acceptable"
    sharpness_score = 0.0
    uniformity_score = 0.8
    fov_adequate = True
    artifacts: list[str] = []
    is_ungradeable = False

    try:
        nparr = np.frombuffer(content, np.uint8)
        cv_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if cv_img is not None:
            qa_res = matlab_bridge._fallback_quality_assessment(cv_img)
            qa_verdict = qa_res.overall_quality
            sharpness_score = float(qa_res.sharpness_score or 0.0)
            uniformity_score = float(qa_res.illumination_uniformity or 0.0)
            fov_adequate = bool(qa_res.field_of_view_adequate)
            artifacts = qa_res.artifacts_detected or []
            is_ungradeable = qa_verdict == "rejected"

            # Tailored actionable recapture feedback for Smartphone + 20D Condensing Lens
            if not fov_adequate:
                recapture_guidance.append(
                    "20D lens aperture decentered: Align the smartphone camera axis directly through the center of the 20D condensing lens and patient's pupil."
                )
            if "reflection" in artifacts:
                recapture_guidance.append(
                    "Corneal reflex/glare obscuring retina: Tilt the 20D condensing lens 5–10° off-axis or shift torch illumination to displace glare away from the macula and optic disc."
                )
            if sharpness_score < 100 or "motion_blur" in artifacts:
                recapture_guidance.append(
                    "Aerial retinal image out of focus: Maintain ~5 cm working distance between the 20D lens and cornea, and tap smartphone screen to lock focus onto retinal vessels."
                )
            if uniformity_score < 0.5:
                recapture_guidance.append(
                    "Uneven illumination: Ensure smartphone continuous torch beam passes cleanly through the condensing lens into the dilated pupil."
                )
            if not recapture_guidance and qa_verdict in ("poor", "rejected"):
                recapture_guidance.append(
                    "Image quality suboptimal: Steady both hands using the patient's forehead as a rest, and verify 20D lens cleanliness."
                )
    except Exception as exc:
        logger.warning(f"IQA on upload encountered non-fatal error: {exc}")

    # Persist QualityResult
    quality_result = QualityResult(
        image_id=image_record.id,
        screening_id=screening_id,
        verdict=qa_verdict,
        ungradeable=is_ungradeable,
        overall_quality_score=sharpness_score,
        sharpness=sharpness_score,
        illumination_uniformity=uniformity_score,
        valid_retina_percentage=0.75 if fov_adequate else 0.20,
        failure_reasons=artifacts if artifacts else None,
    )
    db.add(quality_result)
    await db.flush()

    await log_audit_event(
        db=db,
        event_type="image_uploaded",
        resource_type="image",
        user=current_user,
        facility_id=screening.facility_id,
        resource_id=str(image_record.id),
        details={
            "screening_id": str(screening_id),
            "eye": eye,
            "lens_type": lens_type,
            "width": store_info["width"],
            "height": store_info["height"],
            "sha256": store_info["sha256_hash"],
            "quality_verdict": qa_verdict,
            "ungradeable": is_ungradeable,
        },
        request=request,
    )

    return {
        "image_id": str(image_record.id),
        "original_filename": image_record.original_filename,
        "eye": eye,
        "lens_type": lens_type,
        "width": image_record.width,
        "height": image_record.height,
        "file_size_bytes": image_record.file_size_bytes,
        "sha256_hash": image_record.sha256_hash,
        "quality_assessment": {
            "overall_quality": qa_verdict,
            "is_acceptable": qa_verdict in ("good", "acceptable"),
            "sharpness_score": round(sharpness_score, 2),
            "illumination_uniformity": round(uniformity_score, 2),
            "field_of_view_adequate": fov_adequate,
            "artifacts_detected": artifacts,
            "recapture_guidance": recapture_guidance,
        },
    }



@router.get("/{screening_id}/images/{image_id}/view")
async def view_image(
    screening_id: uuid.UUID,
    image_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Stream a fundus image from private storage.
    Strictly authenticated and facility-scoped.
    """
    # Verify screening and facility access
    result = await db.execute(
        select(Screening).where(Screening.id == screening_id, Screening.is_deleted == False)
    )
    screening = result.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    verify_facility_access(current_user, screening.facility_id)

    # Find image
    img_res = await db.execute(
        select(ScreeningImage).where(
            ScreeningImage.id == image_id,
            ScreeningImage.screening_id == screening_id,
        )
    )
    image_record = img_res.scalar_one_or_none()
    if not image_record:
        raise HTTPException(status_code=404, detail="Image not found")

    try:
        image_data = await image_store.retrieve_image(image_record.stored_filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Image file not found in storage")

    await log_audit_event(
        db=db,
        event_type="image_viewed",
        resource_type="image",
        user=current_user,
        facility_id=screening.facility_id,
        resource_id=str(image_record.id),
        request=request,
    )

    return StreamingResponse(
        io.BytesIO(image_data),
        media_type=image_record.content_type,
        headers={"Content-Disposition": f"inline; filename=\"{image_record.original_filename}\""},
    )


@router.delete("/{screening_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_screening(
    screening_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_health_worker),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a screening session."""
    result = await db.execute(
        select(Screening).where(Screening.id == screening_id, Screening.is_deleted == False)
    )
    screening = result.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    verify_facility_access(current_user, screening.facility_id)

    screening.is_deleted = True
    screening.deleted_at = datetime.now(timezone.utc)

    await log_audit_event(
        db=db,
        event_type="screening_soft_deleted",
        resource_type="screening",
        user=current_user,
        facility_id=screening.facility_id,
        resource_id=str(screening.id),
        request=request,
    )
