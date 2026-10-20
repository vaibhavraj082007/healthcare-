"""Phase 3 — access-controlled report + heatmap endpoints.

Server-side ownership enforcement is mandatory here: a patient may only fetch
reports for their own scans (never trusted solely to the frontend). Reports for
a completed finding that have not yet been generated are produced on demand.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..ml.reports import ensure_report
from ..models import AIFinding, Patient, ScreeningReport, User
from ..schemas import ReportOut

router = APIRouter(prefix="/reports", tags=["reports"])

CLINICAL_ROLES = ("admin", "doctor", "health_worker", "ophthalmologist")


def _get_accessible_upload(db: Session, user: User, image_id: str):
    from ..models import ImageUpload

    upload = db.query(ImageUpload).filter(ImageUpload.image_id == image_id).first()
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")

    if user.role not in CLINICAL_ROLES:
        patient = db.query(Patient).filter(Patient.id == upload.patient_id).first()
        if patient is None or patient.own_user_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to view this report",
            )
    return upload


@router.get("/{image_id}", response_model=ReportOut)
def get_report(
    image_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_accessible_upload(db, user, image_id)

    report = (
        db.query(ScreeningReport).filter(ScreeningReport.image_id == image_id).first()
    )
    if report is None:
        # Lazy generation: a completed finding should always produce a report.
        finding = (
            db.query(AIFinding).filter(AIFinding.image_id == image_id).first()
        )
        if finding is None or finding.analysis_status != "completed":
            raise HTTPException(status_code=404, detail="No report available yet")
        report = ensure_report(db, finding)
        if report is None:
            raise HTTPException(status_code=404, detail="Report could not be generated")

    try:
        structured = json.loads(report.structured_findings or "{}")
    except json.JSONDecodeError:
        structured = {}

    # Both images are referenced by this report's image_id only — the fundus
    # scan and its exact Grad-CAM heatmap. The heatmap URL is only advertised
    # when a heatmap actually exists on disk for this image (never a default).
    base = str(request.base_url).rstrip("/")
    fundus_image_url = f"{base}{settings.api_prefix}/uploads/{image_id}/image"
    heatmap_image_url = None
    if report.gradcam_path and Path(report.gradcam_path).exists():
        heatmap_image_url = f"{base}{settings.api_prefix}/reports/{image_id}/gradcam"

    return ReportOut(
        image_id=report.image_id,
        report_text=report.report_text,
        structured_findings=structured,
        region_notes=report.region_notes,
        gradcam_path=report.gradcam_path,
        generation_method=report.generation_method,
        model_version=report.model_version,
        generated_at=report.generated_at,
        image_urls={"fundus": fundus_image_url, "heatmap": heatmap_image_url},
        fundus_image_url=fundus_image_url,
        heatmap_image_url=heatmap_image_url,
        # Universal report header snapshot (demographics at scan time) + the
        # sectioned plain-language blocks for rendering.
        header={
            "patient_id": report.patient_id,
            "patient_name": report.patient_name,
            "patient_age": report.patient_age,
            "patient_gender": report.patient_gender,
            "referring_phc": report.referring_phc,
            "submitting_worker": report.submitting_worker,
            "scan_date": report.scan_date,
            "eye_laterality": report.eye_laterality,
            "image_quality": report.image_quality,
            "quality_score": report.quality_score,
            "report_id": f"NS-{image_id[:8].upper()}",
            "generated_at": report.generated_at,
            "scan_id": report.image_id,
        },
        observations=structured.get("observations", []),
        recommendation=structured.get("recommendation"),
        disclaimer=structured.get("disclaimer"),
    )


@router.get("/{image_id}/gradcam")
def get_gradcam(
    image_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_accessible_upload(db, user, image_id)

    report = (
        db.query(ScreeningReport).filter(ScreeningReport.image_id == image_id).first()
    )
    path = report.gradcam_path if report is not None else None
    if not path:
        raise HTTPException(status_code=404, detail="Heatmap unavailable")
    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Heatmap file is missing")
    return FileResponse(p, media_type="image/png", filename=f"{image_id}_gradcam.png")