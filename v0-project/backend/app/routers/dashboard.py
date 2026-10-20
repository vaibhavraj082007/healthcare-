from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_roles
from ..models import AIFinding, ImageUpload, Patient, User
from ..schemas import ModelInfo, RoleStats

router = APIRouter(tags=["dashboard"])


@router.get("/stats", response_model=RoleStats)
def dashboard_stats(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "health_worker", "doctor", "ophthalmologist")),
):
    patients_q = db.query(Patient)
    uploads_q = db.query(ImageUpload)
    findings_q = db.query(AIFinding)

    if user.role == "health_worker":
        patients_q = patients_q.filter(Patient.created_by == user.id)
        created_ids = [p.id for p in patients_q.all()]
        uploads_q = uploads_q.filter(ImageUpload.patient_id.in_(created_ids)) if created_ids else uploads_q.filter(ImageUpload.patient_id < 0)

    uploads = uploads_q.all()
    image_ids = [u.image_id for u in uploads]
    if image_ids:
        findings = findings_q.filter(AIFinding.image_id.in_(image_ids)).all()
    else:
        findings = []

    grade_dist: dict[int, int] = {}
    for f in findings:
        if f.icdr_grade is not None:
            grade_dist[f.icdr_grade] = grade_dist.get(f.icdr_grade, 0) + 1

    return RoleStats(
        total_patients=patients_q.count(),
        total_scans=len(uploads),
        scans_analyzed=sum(1 for f in findings if f.analysis_status == "completed"),
        scans_pending=sum(1 for f in findings if f.analysis_status in ("queued", "running")),
        flagged_for_review=sum(1 for f in findings if f.consistency_status == "Flagged for Review"),
        grade_distribution=dict(sorted(grade_dist.items())),
    )


@router.get("/review-queue", response_model=list[dict])
def review_queue(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "doctor", "health_worker", "ophthalmologist")),
):
    """Uploads whose dual-engine check was flagged, plus completed scans for context."""
    limit = 50
    q = (
        db.query(AIFinding)
        .order_by(AIFinding.analyzed_at.desc().nullslast())
        .limit(limit)
        .all()
    )
    result = []
    for f in q:
        up = db.query(ImageUpload).filter(ImageUpload.image_id == f.image_id).first()
        if up is None:
            continue
        pat = db.get(Patient, up.patient_id)
        result.append(
            {
                "image_id": f.image_id,
                "patient_name": pat.full_name if pat else "Unknown",
                "patient_id": pat.id if pat else None,
                "icdr_grade": f.icdr_grade,
                "icdr_confidence": f.icdr_confidence,
                "lesion_count": f.lesion_count,
                "lesion_list": f.lesion_list,
                "consistency_status": f.consistency_status,
                "analysis_status": f.analysis_status,
                "analyzed_at": f.analyzed_at,
                "model_provenance": f.model_provenance,
            }
        )
    return result


@router.get("/models", response_model=list[ModelInfo])
def model_info(db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    from ..config import settings as s
    from ..ml.registry import registry

    return [
        ModelInfo(
            name="Engine B — ICDR Severity Classifier",
            family="EfficientNet-B0",
            task="Ordinal DR severity grading (0–4)",
            trained_on="APTOS 2019 Blindness Detection (train split, 85/15 stratified)",
            fine_tuned=True,
            weights=registry.classifier is not None,
            weights_path=str(s.classifier_weights),
            validation=_meta_metrics(registry.classifier._meta if registry.classifier else {}),
            note=(
                "Fine-tuned from ImageNet weights. Validation is tracked by Quadratic "
                "Weighted Kappa (QWK)."
            ),
        ),
        ModelInfo(
            name="Engine A — Lesion Detector",
            family="YOLOv8",
            task="Microaneurysm / hemorrhage / exudate detection",
            trained_on="See note",
            fine_tuned=False,
            weights=registry.detector is not None,
            weights_path=str(s.detector_weights),
            validation={},
            note=str(registry.detector.PROVENANCE["detail"]) if registry.detector else (
                "Not loaded. Place a YOLO checkpoint at " + str(s.detector_weights) + ". "
                "APTOS has no lesion annotations; either fine-tune on IDRiD "
                "(backend/train_detector.py) or load a public pretrained checkpoint."
            ),
        ),
    ]


def _meta_metrics(meta: dict) -> dict:
    out = {}
    for key in ("validation_qwk", "validation_accuracy", "epochs", "samples"):
        if key in meta:
            out[key] = meta[key]
    return out