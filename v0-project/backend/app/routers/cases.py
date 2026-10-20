"""Phase 4 Part A — doctor portal: priority case queue, constrained NL search,
claims, status controls and the doctor/ASHA notes thread.

Role enforcement is always server-side:
    * ``doctor`` / ``ophthalmologist`` — queue, detail, claim, status, notes
    * ``admin`` — read visibility + notes
    * ``health_worker`` — notes on cases for patients they register only
Severity/status/contact data is exposed to the frontend but every mutation is
re-validated here.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..cases import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    STATUS_CLAIMED,
    STATUS_CONTACTED,
    STATUS_FLOW,
    STATUS_NEW,
    STATUS_REVIEWED,
    ensure_case_tracking,
)
from ..database import get_db
from ..deps import get_current_user
from ..models import (
    AIFinding,
    CaseNote,
    CaseTracking,
    ImageUpload,
    Patient,
    ScreeningReport,
    SignOff,
    SyncQueue,
    User,
)
from ..nl_search import parse_nl_filter
from ..schemas import (
    CaseDetailOut,
    CaseListItem,
    CaseNoteIn,
    CaseNoteOut,
    CaseStatusIn,
    CaseSummaryOut,
    NlSearchIn,
    NlSearchOut,
)

router = APIRouter(prefix="/doctor", tags=["case-tracking"])

REVIEW_ROLES = ("doctor", "ophthalmologist")
READ_ROLES = ("admin", "doctor", "ophthalmologist")

BAND_SCORE = {SEVERITY_HIGH: 2, "Medium": 1, "Low": 0}
STATUS_SCORE = {STATUS_NEW: 3, STATUS_CLAIMED: 2, STATUS_CONTACTED: 1, STATUS_REVIEWED: 0}


def _is_flagged(consistency: str | None) -> bool:
    return "flag" in (consistency or "").lower()


def _phc(patient: Patient) -> str | None:
    return patient.village or patient.district


def _signoff(db: Session, image_id: str) -> SignOff | None:
    return db.query(SignOff).filter(SignOff.image_id == image_id).first()


def _case(db: Session, image_id: str) -> CaseTracking | None:
    return db.query(CaseTracking).filter(CaseTracking.image_id == image_id).first()


def _load_finding(db: Session, image_id: str) -> AIFinding:
    finding = db.query(AIFinding).filter(AIFinding.image_id == image_id).first()
    if finding is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return finding


def _build_item(db: Session, finding: AIFinding) -> CaseListItem | None:
    upload = (
        db.query(ImageUpload)
        .filter(ImageUpload.image_id == finding.image_id)
        .first()
    )
    if upload is None:
        return None
    patient = db.get(Patient, upload.patient_id)
    if patient is None:
        return None

    report = (
        db.query(ScreeningReport)
        .filter(ScreeningReport.image_id == finding.image_id)
        .first()
    )
    signoff = _signoff(db, finding.image_id)
    case = _case(db, finding.image_id)
    sync = db.query(SyncQueue).filter(SyncQueue.image_id == finding.image_id).first()

    assigned_name = None
    worker_name = None
    if case is not None and case.assigned_doctor_id is not None:
        doc = db.get(User, case.assigned_doctor_id)
        assigned_name = doc.full_name if doc else None
    worker = db.get(User, patient.created_by)
    if worker is not None:
        worker_name = worker.full_name

    return CaseListItem(
        image_id=finding.image_id,
        patient_id=patient.id,
        patient_name=patient.full_name,
        patient_age=patient.age,
        patient_gender=patient.gender,
        village=patient.village,
        district=patient.district,
        phc=_phc(patient),
        icdr_grade=finding.icdr_grade,
        icdr_confidence=finding.icdr_confidence,
        consistency_status=finding.consistency_status or "pending",
        severity_band=case.severity_band if case else "Low",
        status=case.status if case else STATUS_NEW,
        flagged=_is_flagged(finding.consistency_status),
        assigned_doctor_id=case.assigned_doctor_id if case else None,
        assigned_doctor_name=assigned_name,
        worker_id=patient.created_by,
        worker_name=worker_name,
        has_report=report is not None,
        signed_off=signoff is not None,
        analyzed_at=finding.analyzed_at,
        uploaded_at=upload.uploaded_at,
        claimed_at=case.claimed_at if case else None,
        contacted_at=case.contacted_at if case else None,
        reviewed_at=case.reviewed_at if case else None,
        created_at=case.created_at if case else None,
    )


def _sort_key(item: CaseListItem):
    band = BAND_SCORE.get(item.severity_band, 0)
    status = STATUS_SCORE.get(item.status, 0)
    # Flagged-and-unhandled float above everything; then urgency band; then
    # how far along the workflow the case is; the newest scans first.
    group = 1 if (item.flagged and item.status != STATUS_REVIEWED) else 0
    ts = (item.analyzed_at or datetime.min).timestamp()
    return (group, band, status, ts)


def _items_for_filters(db: Session, filters: dict) -> list[CaseListItem]:
    findings = (
        db.query(AIFinding)
        .filter(AIFinding.analysis_status == "completed")
        .all()
    )
    items: list[CaseListItem] = []
    for finding in findings:
        item = _build_item(db, finding)
        if item is None:
            continue
        if filters.get("severity_band") and item.severity_band != filters["severity_band"]:
            continue
        if filters.get("status") and item.status != filters["status"]:
            continue
        if filters.get("consistency") == "flag" and not item.flagged:
            continue
        if filters.get("consistency") == "consistent" and item.flagged:
            continue
        if filters.get("phc") and filters["phc"] != (item.phc or ""):
            continue
        if filters.get("from_date") and (item.uploaded_at is None or item.uploaded_at.date().isoformat() < filters["from_date"]):
            continue
        if filters.get("to_date") and (item.uploaded_at is None or item.uploaded_at.date().isoformat() > filters["to_date"]):
            continue
        items.append(item)
    items.sort(key=_sort_key, reverse=True)
    return items


def _assert_read(db: Session, user: User):
    if user.role not in READ_ROLES:
        raise HTTPException(status_code=403, detail="Doctor role required")


def _assert_note_access(db: Session, user: User, image_id: str):
    if user.role in READ_ROLES:
        return
    if user.role == "health_worker":
        upload = db.query(ImageUpload).filter(ImageUpload.image_id == image_id).first()
        if upload is None:
            raise HTTPException(status_code=404, detail="Case not found")
        patient = db.get(Patient, upload.patient_id)
        if patient is not None and patient.created_by == user.id:
            return
    raise HTTPException(status_code=403, detail="You do not have permission to view this case")


# --------------------------------------------------------------------------
# Queue + summary
# --------------------------------------------------------------------------


@router.get("/cases", response_model=list[CaseListItem])
def case_list(
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    phc: str | None = Query(default=None),
    consistency: str | None = Query(default=None),
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _assert_read(db, user)
    filters = {
        "severity_band": severity,
        "status": status,
        "phc": phc,
        "consistency": consistency,
        "from_date": from_date,
        "to_date": to_date,
    }
    filters = {key: value for key, value in filters.items() if value}
    return _items_for_filters(db, filters)


@router.get("/cases/summary", response_model=CaseSummaryOut)
def case_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _assert_read(db, user)
    items = _items_for_filters(db, {})
    today = datetime.utcnow().date()
    awaiting = [i for i in items if i.status in (STATUS_NEW, STATUS_CLAIMED, STATUS_CONTACTED)]
    flagged_pending = [i for i in items if i.flagged and i.status != STATUS_REVIEWED]
    claimed_by_me = [
        i for i in items if i.assigned_doctor_id == user.id and i.status != STATUS_REVIEWED
    ]
    today_reported = [i for i in items if i.created_at and i.created_at.date() == today]
    today_reviewed = [i for i in items if i.reviewed_at and i.reviewed_at.date() == today]
    return CaseSummaryOut(
        total=len(items),
        high=sum(1 for i in items if i.severity_band == SEVERITY_HIGH),
        medium=sum(1 for i in items if i.severity_band == "Medium"),
        low=sum(1 for i in items if i.severity_band == "Low"),
        flagged_pending=len(flagged_pending),
        awaiting_review=len(awaiting),
        claimed_by_me=len(claimed_by_me),
        today_reported=len(today_reported),
        today_reviewed=len(today_reviewed),
    )


# --------------------------------------------------------------------------
# Case detail
# --------------------------------------------------------------------------


@router.get("/cases/detail/{image_id}", response_model=CaseDetailOut)
def case_detail(
    image_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _assert_read(db, user)
    finding = _load_finding(db, image_id)
    case = ensure_case_tracking(db, finding)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not ready yet")

    base = _build_item(db, finding)
    upload = db.query(ImageUpload).filter(ImageUpload.image_id == image_id).first()
    patient = db.get(Patient, upload.patient_id) if upload else None

    lesion_list: object = None
    try:
        lesion_list = json.loads(finding.lesion_list or "[]")
    except json.JSONDecodeError:
        lesion_list = []

    signoff = _signoff(db, image_id)
    sign_off: dict | None = None
    if signoff is not None:
        sign_off = {
            "decision": signoff.decision,
            "doctor_notes": signoff.doctor_notes,
            "revised_grade": signoff.revised_grade,
            "signed_at": signoff.signed_at.isoformat(),
            "ophthalmologist_id": signoff.ophthalmologist_id,
        }

    report = (
        db.query(ScreeningReport).filter(ScreeningReport.image_id == image_id).first()
    )
    sync = db.query(SyncQueue).filter(SyncQueue.image_id == image_id).first()
    note_rows = (
        db.query(CaseNote)
        .filter(CaseNote.image_id == image_id)
        .order_by(CaseNote.created_at.asc())
        .all()
    )
    notes = [
        CaseNoteOut(
            id=n.id,
            image_id=n.image_id,
            author_id=n.author_id,
            author_name=n.author_name,
            body=n.body,
            created_at=n.created_at,
        )
        for n in note_rows
    ]

    return CaseDetailOut(
        **base.model_dump(),
        phone=patient.phone if patient else None,
        lesion_count=finding.lesion_count,
        lesion_list=lesion_list,
        sync_status=sync.status if sync else "queued",
        report_generation_method=report.generation_method if report else None,
        sign_off=sign_off,
        notes=notes,
    )


# --------------------------------------------------------------------------
# Claim + status controls
# --------------------------------------------------------------------------


def _require_review(user: User):
    if user.role not in REVIEW_ROLES:
        raise HTTPException(status_code=403, detail="Doctor role required")


@router.post("/cases/claim/{image_id}", response_model=CaseDetailOut)
def claim_case(
    image_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_review(user)
    finding = _load_finding(db, image_id)
    case = ensure_case_tracking(db, finding)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not ready yet")

    if case.status == STATUS_REVIEWED:
        raise HTTPException(status_code=400, detail="This case has already been reviewed")
    if (
        case.assigned_doctor_id is not None
        and case.assigned_doctor_id != user.id
        and case.status != STATUS_NEW
    ):
        owner = db.get(User, case.assigned_doctor_id)
        name = owner.full_name if owner else f"user {case.assigned_doctor_id}"
        raise HTTPException(status_code=409, detail=f"Case is already claimed by {name}")

    first_claim = case.assigned_doctor_id is None
    if first_claim:
        case.assigned_doctor_id = user.id
    if case.status == STATUS_NEW:
        case.status = STATUS_CLAIMED
        case.claimed_at = datetime.utcnow()
    db.commit()

    return case_detail(image_id, db, user)


@router.post("/cases/status/{image_id}", response_model=CaseDetailOut)
def move_case(
    image_id: str,
    payload: CaseStatusIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_review(user)
    target = payload.status.strip().title()
    if target not in STATUS_FLOW:
        raise HTTPException(
            status_code=400,
            detail="status must be one of " + ", ".join(STATUS_FLOW),
        )
    finding = _load_finding(db, image_id)
    case = ensure_case_tracking(db, finding)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not ready yet")

    current_index = STATUS_FLOW.index(case.status) if case.status in STATUS_FLOW else 0
    target_index = STATUS_FLOW.index(target)
    if case.status == STATUS_REVIEWED:
        raise HTTPException(status_code=400, detail="This case has already been reviewed")
    if target_index < current_index:
        raise HTTPException(status_code=400, detail=f"Cannot move backwards from {case.status}")
    if target_index > current_index + 1:
        raise HTTPException(
            status_code=400,
            detail=f"Advance one stage at a time: {case.status} -> {STATUS_FLOW[current_index + 1]}",
        )

    if target == STATUS_CLAIMED:
        if case.assigned_doctor_id is None:
            case.assigned_doctor_id = user.id
        case.claimed_at = datetime.utcnow()
    elif target == STATUS_CONTACTED:
        if case.assigned_doctor_id is None:
            case.assigned_doctor_id = user.id
        case.contacted_at = datetime.utcnow()
    elif target == STATUS_REVIEWED:
        case.reviewed_at = datetime.utcnow()
    case.status = target
    db.commit()

    return case_detail(image_id, db, user)


# --------------------------------------------------------------------------
# Notes thread (doctor + ASHA worker)
# --------------------------------------------------------------------------


@router.get("/cases/notes/{image_id}", response_model=list[CaseNoteOut])
def list_notes(
    image_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _assert_note_access(db, user, image_id)
    rows = (
        db.query(CaseNote)
        .filter(CaseNote.image_id == image_id)
        .order_by(CaseNote.created_at.asc())
        .all()
    )
    return [
        CaseNoteOut(
            id=n.id,
            image_id=n.image_id,
            author_id=n.author_id,
            author_name=n.author_name,
            body=n.body,
            created_at=n.created_at,
        )
        for n in rows
    ]


@router.post("/cases/notes/{image_id}", response_model=CaseNoteOut)
def add_note(
    image_id: str,
    payload: CaseNoteIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if _case(db, image_id) is None:
        raise HTTPException(status_code=404, detail="Case not found")
    _assert_note_access(db, user, image_id)
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Note cannot be empty")
    if len(body) > 2000:
        raise HTTPException(status_code=400, detail="Note is too long (max 2000 characters)")

    note = CaseNote(
        image_id=image_id,
        author_id=user.id,
        author_name=user.full_name,
        body=body,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return CaseNoteOut(
        id=note.id,
        image_id=note.image_id,
        author_id=note.author_id,
        author_name=note.author_name,
        body=note.body,
        created_at=note.created_at,
    )


# --------------------------------------------------------------------------
# Constrained NL search
# --------------------------------------------------------------------------


@router.post("/cases/search", response_model=NlSearchOut)
def search_cases(
    payload: NlSearchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _assert_read(db, user)
    result = parse_nl_filter(payload.query, db)
    items = _items_for_filters(db, result.get("filter") or {}) if result["matched"] else []
    return NlSearchOut(
        query=payload.query,
        matched=result["matched"],
        filter=result.get("filter") or None,
        message=result.get("message", ""),
        items=items,
    )