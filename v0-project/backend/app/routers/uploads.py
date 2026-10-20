import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user, require_roles
from ..ml.quality_gate import assess_quality
from ..models import AIFinding, ImageUpload, Patient, User
from ..schemas import UploadOut

router = APIRouter(prefix="/uploads", tags=["uploads"])

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB per Phase 1 spec
EYE_LATERALITY_CODES = {"od", "os", "ou", "unknown"}


@router.post("", response_model=UploadOut, status_code=201)
def upload_image(
    patient_id: int = Form(...),
    eye_laterality: str = Form("unknown"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "health_worker")),
):
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    eye_code = eye_laterality.strip().lower()
    if eye_code not in EYE_LATERALITY_CODES:
        raise HTTPException(
            status_code=422,
            detail="eye_laterality must be one of: OD, OS, OU, Unknown",
        )

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    image_bytes = file.file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large — maximum is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    # Reject corrupted/unreadable images before they reach preprocessing.
    from io import BytesIO

    from PIL import Image

    try:
        with Image.open(BytesIO(image_bytes)) as probe:
            probe.verify()
    except Exception as exc:  # noqa: BLE001 — malformed files must not crash
        raise HTTPException(
            status_code=400, detail="Image file is corrupted or unreadable"
        ) from exc

    quality = assess_quality(image_bytes)

    image_id = uuid.uuid4().hex[:16]
    upload_dir = settings.upload_dir / "scans"
    upload_dir.mkdir(parents=True, exist_ok=True)
    storage_name = f"{image_id}{ext}"
    dest = upload_dir / storage_name
    dest.write_bytes(image_bytes)

    upload = ImageUpload(
        image_id=image_id,
        patient_id=patient.id,
        uploaded_by=user.id,
        filename=file.filename or storage_name,
        file_path=str(dest),
        quality_status=quality["status"],
        quality_score=quality["blur_score"],
        eye_laterality=eye_code,
    )

    # Consecutive-retake tracking per Phase 1 spec: a failed attempt resets only
    # when an acceptable capture arrives; the lens/camera hint surfaces at >= 3.
    prev = (
        db.query(ImageUpload)
        .filter(ImageUpload.patient_id == patient.id)
        .order_by(ImageUpload.uploaded_at.desc())
        .first()
    )
    if quality["status"] == "poor":
        upload.retake_count = (
            prev.retake_count + 1 if prev is not None and prev.quality_status == "poor" else 1
        )
    else:
        upload.retake_count = 0

    db.add(upload)
    db.commit()
    db.refresh(upload)

    # queue analysis regardless of quality; poor captures are surfaced to the caller
    findings = AIFinding(image_id=image_id, analysis_status="queued")
    db.add(findings)
    db.commit()

    return UploadOut.model_validate(upload)


@router.get("/{image_id}", response_model=UploadOut)
def get_upload(
    image_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    upload = db.query(ImageUpload).filter(ImageUpload.image_id == image_id).first()
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    return UploadOut.model_validate(upload)


@router.get("/{image_id}/image")
def get_upload_image(
    image_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Stream the stored scan back to authorized clients (review/patient views)."""
    upload = db.query(ImageUpload).filter(ImageUpload.image_id == image_id).first()
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")

    path = Path(upload.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file is missing")
    return FileResponse(path, media_type="image/png", filename=upload.filename)