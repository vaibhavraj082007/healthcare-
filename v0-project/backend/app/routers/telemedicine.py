"""Phase 4 — telemedicine: doctor review portal, sync queue status, patient
status machine and post-sign-off summaries.

Role enforcement is always server-side:
  * ``doctor`` / ``ophthalmologist`` — review queue, sign-offs, case status
  * ``admin`` — queue visibility + the offline-simulation demo toggle
  * a patient may only ever read their OWN summaries/status/report
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..ml.summaries import LANGUAGES, create_summaries
from ..models import AIFinding, ImageUpload, Patient, PatientSummary, SignOff, SyncQueue, User
from ..schemas import (
    DoctorQueueCount,
    DoctorQueueItem,
    OfflineSimIn,
    PatientStatusOut,
    SignOffIn,
    SignOffOut,
    SummaryOut,
    SyncStatus,
)
from ..sync import set_offline_sim, offline_sim_enabled

router = APIRouter(tags=["telemedicine"])

REVIEW_ROLES = ("doctor", "ophthalmologist")
CLINICAL_ROLES = ("admin", "doctor", "health_worker", "ophthalmologist")


def _load_upload(db: Session, image_id: str) -> ImageUpload:
    upload = db.query(ImageUpload).filter(ImageUpload.image_id == image_id).first()
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    return upload


def _assert_owner_or_clinical(upload: ImageUpload, user: User, db: Session) -> None:
    if user.role in CLINICAL_ROLES:
        return
    patient = db.query(Patient).filter(Patient.id == upload.patient_id).first()
    if patient is None or patient.own_user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view this record",
        )


def _is_flagged(consistency_status: str | None) -> bool:
    return "flag" in (consistency_status or "").lower()


# --------------------------------------------------------------------------
# Doctor review portal
# --------------------------------------------------------------------------


@router.get("/doctor/queue", response_model=list[DoctorQueueItem])
def doctor_queue(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in REVIEW_ROLES:
        raise HTTPException(status_code=403, detail="Clinical review role required")

    findings = (
        db.query(AIFinding)
        .filter(AIFinding.analysis_status == "completed")
        .order_by(AIFinding.analyzed_at.desc())
        .all()
    )
    items: list[DoctorQueueItem] = []
    for f in findings:
        upload = _load_upload(db, f.image_id)
        signoff = db.query(SignOff).filter(SignOff.image_id == f.image_id).first()
        sync = db.query(SyncQueue).filter(SyncQueue.image_id == f.image_id).first()
        patient = db.query(Patient).filter(Patient.id == upload.patient_id).first()
        items.append(
            DoctorQueueItem(
                image_id=f.image_id,
                patient_id=upload.patient_id,
                patient_name=patient.full_name if patient else "Unknown patient",
                icdr_grade=f.icdr_grade,
                icdr_confidence=f.icdr_confidence,
                consistency_status=f.consistency_status or "pending",
                sync_status=sync.status if sync else "queued",
                viewed=sync.viewed_at is not None if sync else False,
                signed_off=signoff is not None,
                signed_decision=signoff.decision if signoff else None,
                analyzed_at=f.analyzed_at,
            )
        )
    items.sort(
        key=lambda i: (
            0 if (not i.signed_off) and _is_flagged(i.consistency_status) else
            1 if (not i.signed_off) else 2,
            str(i.analyzed_at or ""),
        )
    )
    return items


@router.get("/doctor/queue/count", response_model=DoctorQueueCount)
def doctor_queue_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in REVIEW_ROLES:
        raise HTTPException(status_code=403, detail="Clinical review role required")

    findings = db.query(AIFinding).filter(AIFinding.analysis_status == "completed").all()
    unseen = 0
    unseen_flagged = 0
    for f in findings:
        if db.query(SignOff).filter(SignOff.image_id == f.image_id).first():
            continue
        sync = db.query(SyncQueue).filter(SyncQueue.image_id == f.image_id).first()
        if sync is not None and sync.viewed_at is not None:
            continue
        unseen += 1
        if _is_flagged(f.consistency_status):
            unseen_flagged += 1
    return DoctorQueueCount(unseen=unseen, unseen_flagged=unseen_flagged)


@router.post("/doctor/queue/{image_id}/seen")
def mark_seen(
    image_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in REVIEW_ROLES:
        raise HTTPException(status_code=403, detail="Clinical review role required")
    sync = db.query(SyncQueue).filter(SyncQueue.image_id == image_id).first()
    if sync is None:
        raise HTTPException(status_code=404, detail="Case is not in the review queue")
    if sync.viewed_at is None:
        sync.viewed_at = datetime.utcnow()
        db.commit()
    return {"image_id": image_id, "viewed": True}


@router.post("/doctor/signoffs", response_model=SignOffOut)
def create_signoff(
    payload: SignOffIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in REVIEW_ROLES:
        raise HTTPException(status_code=403, detail="Ophthalmologist role required")

    finding = db.query(AIFinding).filter(AIFinding.image_id == payload.image_id).first()
    if finding is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if finding.analysis_status != "completed" or finding.icdr_grade is None:
        raise HTTPException(status_code=400, detail="This scan has no completed AI grade to sign off")

    existing = db.query(SignOff).filter(SignOff.image_id == payload.image_id).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="This case has already been signed off")

    if payload.decision not in ("Approved", "Revised", "Rejected"):
        raise HTTPException(status_code=400, detail="decision must be Approved, Revised or Rejected")
    if payload.decision == "Revised":
        if payload.revised_grade is None or not (0 <= payload.revised_grade <= 4):
            raise HTTPException(status_code=400, detail="Revised requires revised_grade 0-4")
    elif payload.revised_grade is not None:
        raise HTTPException(status_code=400, detail="revised_grade is only allowed when decision is Revised")
    if payload.decision == "Rejected" and not (payload.doctor_notes or "").strip():
        raise HTTPException(status_code=400, detail="Rejected cases must record a reason in doctor_notes")

    signoff = SignOff(
        image_id=payload.image_id,
        ophthalmologist_id=user.id,
        decision=payload.decision,
        doctor_notes=(payload.doctor_notes or "").strip() or None,
        revised_grade=payload.revised_grade,
        signed_at=datetime.utcnow(),
    )
    db.add(signoff)
    db.commit()
    db.refresh(signoff)

    summaries = create_summaries(db, payload.image_id, signoff, ai_grade=int(finding.icdr_grade))
    return SignOffOut(
        image_id=signoff.image_id,
        decision=signoff.decision,
        doctor_notes=signoff.doctor_notes,
        revised_grade=signoff.revised_grade,
        signed_at=signoff.signed_at,
        summary_languages=[s.language for s in summaries],
    )


# --------------------------------------------------------------------------
# Sync status + demos
# --------------------------------------------------------------------------


@router.get("/sync/status", response_model=SyncStatus)
def sync_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in REVIEW_ROLES and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not permitted")
    rows = db.query(SyncQueue).all()
    counts = {"pending": 0, "syncing": 0, "synced": 0, "failed": 0}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return SyncStatus(
        pending=counts["pending"],
        syncing=counts["syncing"],
        synced=counts["synced"],
        failed=counts["failed"],
        total=len(rows),
        offline_sim=offline_sim_enabled(),
    )


@router.post("/sync/offline-sim", response_model=SyncStatus)
def set_offline(
    payload: OfflineSimIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    set_offline_sim(payload.enabled)
    return sync_status(db, user)


# --------------------------------------------------------------------------
# Patient summaries + status machine (own-record only for patients)
# --------------------------------------------------------------------------


def build_patient_status(db: Session, image_id: str) -> PatientStatusOut:
    """Derive the patient-facing state from the pipeline fields (no duplicate
    status column): analysis lifecycle + sync_queue liveness + sign_offs."""
    finding = db.query(AIFinding).filter(AIFinding.image_id == image_id).first()
    signoff = db.query(SignOff).filter(SignOff.image_id == image_id).first()
    summaries = (
        db.query(PatientSummary).filter(PatientSummary.image_id == image_id).all()
    )
    lang_list = [s.language for s in summaries]

    if finding is None or finding.analysis_status in ("queued", "failed"):
        return PatientStatusOut(
            image_id=image_id,
            state="scan_received",
            stage_label="Scan received",
            patient_text="Your eye scan has been received and is being prepared for analysis.",
            summary_languages=lang_list,
        )
    if finding.analysis_status == "running":
        return PatientStatusOut(
            image_id=image_id,
            state="analysis_in_progress",
            stage_label="Analysis in progress",
            patient_text="The AI is analysing your scan right now. This usually takes a few minutes. Please check back shortly.",
            summary_languages=lang_list,
        )
    if signoff is None:
        return PatientStatusOut(
            image_id=image_id,
            state="awaiting_review",
            stage_label="Awaiting doctor review",
            patient_text="Your scan has been reviewed by the AI and is now with the doctor for a final check. Your results will appear here once the doctor signs off your report.",
            summary_languages=lang_list,
        )
    return PatientStatusOut(
        image_id=image_id,
        state="reviewed",
        stage_label="Reviewed",
        patient_text="A doctor has reviewed your scan. Your plain-language result and voice summary are ready below.",
        summary_languages=lang_list,
        signed_off=True,
        signed_decision=signoff.decision,
        revised_grade=signoff.revised_grade,
    )


@router.get("/reports/{image_id}/status", response_model=PatientStatusOut)
def patient_status(
    image_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    upload = _load_upload(db, image_id)
    _assert_owner_or_clinical(upload, user, db)
    return build_patient_status(db, image_id)


@router.get("/summaries/{image_id}", response_model=list[SummaryOut])
def list_summaries(
    image_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    upload = _load_upload(db, image_id)
    _assert_owner_or_clinical(upload, user, db)
    rows = (
        db.query(PatientSummary)
        .filter(PatientSummary.image_id == image_id)
        .order_by(PatientSummary.language.asc())
        .all()
    )
    return [
        SummaryOut(
            language=r.language,
            summary_text=r.summary_text,
            has_audio=bool(r.audio_path and Path(r.audio_path).exists()),
            content_version=str(r.generated_at),
        )
        for r in rows
    ]


@router.get("/summaries/{image_id}/{language}/audio")
def summary_audio(
    image_id: str,
    language: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if language not in LANGUAGES:
        raise HTTPException(status_code=404, detail="Unsupported language")
    upload = _load_upload(db, image_id)
    _assert_owner_or_clinical(upload, user, db)
    row = (
        db.query(PatientSummary)
        .filter(PatientSummary.image_id == image_id, PatientSummary.language == language)
        .first()
    )
    if row is None or not row.audio_path:
        raise HTTPException(status_code=404, detail="No audio clip for this record")
    p = Path(row.audio_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Audio file is missing")
    media_type = "audio/mpeg" if p.suffix == ".mp3" else "audio/wav"
    return FileResponse(
        p,
        media_type=media_type,
        filename=f"{image_id}_{language}{p.suffix}",
        headers={"Cache-Control": "no-store"},
    )