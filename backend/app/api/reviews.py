"""
RetinaShield — Ophthalmologist Review Queue & Case Review API

Provides:
  GET  /api/screenings/review-queue        — Filtered, prioritized review queue
  POST /api/screenings/{id}/review/claim   — Acquire case editing lock
  POST /api/screenings/{id}/review/release — Release case editing lock
  POST /api/screenings/{id}/review         — Submit / amend clinician review (w/ concurrency check)
  GET  /api/screenings/{id}/review         — Retrieve current review + amendment history
  GET  /api/screenings/{id}/review/history — Amendment audit history only
  POST /api/screenings/{id}/report         — Generate & sign a clinical report
  GET  /api/screenings/{id}/report         — Retrieve signed report

Design constraints:
  • AI model outputs in model_outputs / analysis_result are NEVER overwritten.
  • ClinicianReview holds the authoritative clinical judgment, strictly separate.
  • Every amendment to a final review appends a ReviewAmendment record.
  • Concurrent edits are prevented via optimistic-concurrency version check.
  • Case locks with TTL further prevent simultaneous editing.
  • Signed reports carry explicit disclaimer that individual sign-off ≠ AI clinical validation.
"""

from __future__ import annotations

import os
import tempfile
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    require_ophthalmologist,
    verify_facility_access,
    log_audit_event,
)
from app.db.session import get_db
from app.models.screening import Screening
from app.models.patient import Patient
from app.models.clinical import ClinicianReview, ReviewAmendment, Report, ModelOutput
from app.models.user import User
from app.schemas.clinical import (
    ClinicianReviewCreate,
    ClinicianReviewRead,
    ReviewAmendmentRead,
    ReviewQueueItem,
    ReviewQueueResponse,
    LockAcquireResponse,
    LockReleaseResponse,
    ReportCreate,
    ReportRead,
    ReportGenerateRequest,
    VoicePlaybackRequest,
    VoicePlaybackResponse,
)
from app.services.report_templates import generate_technical_report, generate_patient_summary
from app.services.pdf_generator import generate_technical_report_pdf, generate_patient_summary_pdf
from app.services.voice_service import synthesize_offline_audio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/screenings", tags=["clinician-reviews"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: How long a case lock is held before it can be reclaimed by another reviewer.
_LOCK_TTL_MINUTES = 20

#: Prioritization rules registry. Each key identifies a named, versioned rule.
#  Changing or re-ordering rules must go through a clinical protocol approval process.
_PRIORITY_RULES: dict[str, dict[str, str]] = {
    "clinical_urgency": {
        "display": "Clinical Urgency First",
        "version": "1.0.0",
        "description": (
            "Orders by AI-predicted referral urgency (urgent > priority > routine > none), "
            "then by disagreement/uncertainty flags, then oldest submission first."
        ),
    },
    "oldest_first": {
        "display": "Oldest Submission First",
        "version": "1.0.0",
        "description": "FIFO ordering by screening date.",
    },
    "disagreement_first": {
        "display": "Disagreement/Uncertainty First",
        "version": "1.0.0",
        "description": (
            "Surfaces cases where classifier and lesion engine disagree, or where "
            "prediction uncertainty is high, before routine cases."
        ),
    },
    "highest_grade_first": {
        "display": "Highest Predicted Severity First",
        "version": "1.0.0",
        "description": "Orders by predicted DR grade descending.",
    },
}

_URGENCY_ORDER = {"urgent": 0, "priority": 1, "routine": 2, "none": 3}

_DR_LABELS = {
    0: "No DR",
    1: "Mild NPDR",
    2: "Moderate NPDR",
    3: "Severe NPDR",
    4: "Proliferative DR",
    -1: "Ungradeable",
}

_VALIDATION_DISCLAIMER = (
    "INDIVIDUAL CLINICIAN SIGN-OFF — This report has been reviewed and signed by the "
    "ophthalmologist identified above. This review reflects an individual clinician's "
    "assessment based on available images and clinical judgment.\n\n"
    "IMPORTANT: Individual sign-off on a screening encounter does NOT constitute "
    "regulatory or clinical validation of the AI model itself. The AI pipeline is a "
    "research screening tool and has not been independently validated for autonomous "
    "clinical diagnosis. Model outputs are provided solely as secondary decision support."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_review_status(screening: Screening, review: ClinicianReview | None) -> str:
    """
    Resolve one of the three required display states:
      - 'ai_generated'       : analysis complete, no human review started
      - 'awaiting_review'    : completed analysis, no review record
      - 'in_review'          : review exists in 'draft' status
      - 'clinician_reviewed' : review exists in 'final' or 'amended' status
      - 'recapture_requested': reviewer flagged the image for recapture
    """
    if not review:
        if screening.status in ("completed", "reviewed"):
            return "awaiting_review"
        return "ai_generated"
    if review.recapture_requested:
        return "recapture_requested"
    if review.status == "draft":
        return "in_review"
    return "clinician_reviewed"


def _lock_is_active(review: ClinicianReview, now: datetime) -> bool:
    """Return True if the review is currently locked and the lock has not expired."""
    if not review.locked_by_id:
        return False
    if not review.lock_expires_at:
        return False
    lock_exp = review.lock_expires_at
    if lock_exp.tzinfo is None and now.tzinfo is not None:
        lock_exp = lock_exp.replace(tzinfo=timezone.utc)
    elif lock_exp.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if lock_exp <= now:
        return False
    return True


async def _load_ai_flags(
    db: AsyncSession, screening_id: uuid.UUID
) -> tuple[bool, bool, str | None]:
    """Return (is_uncertain, has_disagreement, concordance_status) from model_outputs."""
    res = await db.execute(
        select(ModelOutput)
        .where(ModelOutput.screening_id == screening_id)
        .order_by(ModelOutput.created_at.desc())
        .limit(1)
    )
    mo = res.scalar_one_or_none()
    if not mo:
        return False, False, None
    is_uncertain = bool(
        (mo.uncertainty_entropy is not None and mo.uncertainty_entropy > 0.8)
        or (mo.uncertainty_margin is not None and mo.uncertainty_margin < 0.15)
    )
    concordance_status = mo.concordance_status
    has_disagreement = bool(
        concordance_status and concordance_status not in ("Concordant AI findings", "concordant")
    )
    return is_uncertain, has_disagreement, concordance_status


async def _build_queue_item(
    db: AsyncSession,
    screening: Screening,
    review: ClinicianReview | None,
    patient_name: str | None,
) -> ReviewQueueItem:
    is_uncertain, has_disagreement, concordance_status = await _load_ai_flags(db, screening.id)
    return ReviewQueueItem(
        screening_id=screening.id,
        patient_id=screening.patient_id,
        patient_name=patient_name,
        facility_id=screening.facility_id,
        eye=screening.eye,
        screened_at=screening.screened_at,
        quality_verdict=screening.quality_verdict,
        ai_dr_grade=screening.dr_grade,
        ai_dr_grade_label=screening.dr_grade_label,
        ai_confidence=screening.dr_confidence,
        ai_referral_urgency=screening.referral_urgency,
        ai_model_trained=screening.model_trained,
        is_uncertain=is_uncertain,
        has_disagreement=has_disagreement,
        concordance_status=concordance_status,
        review_status=_resolve_review_status(screening, review),
        confirmed_dr_grade=review.confirmed_dr_grade if review else None,
        confirmed_grade_label=_DR_LABELS.get(review.confirmed_dr_grade) if review else None,
        review_version=review.review_version if review else None,
        locked_by_id=review.locked_by_id if review else None,
        lock_expires_at=review.lock_expires_at if review else None,
    )


# ---------------------------------------------------------------------------
# Review Queue
# ---------------------------------------------------------------------------

@router.get("/review-queue", response_model=ReviewQueueResponse)
async def get_review_queue(
    # Filters
    facility_id: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    quality: str | None = Query(None, description="good|acceptable|poor|rejected|ungradeable"),
    provisional_severity: int | None = Query(None, ge=-1, le=4),
    uncertainty: bool | None = Query(None),
    disagreement: bool | None = Query(None),
    review_status: str | None = Query(
        None,
        description="ai_generated|awaiting_review|in_review|clinician_reviewed|recapture_requested",
    ),
    # Sorting / prioritization
    priority_sort: str = Query("clinical_urgency", description="|".join(_PRIORITY_RULES.keys())),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    ophthalmologist: User = Depends(require_ophthalmologist),
    db: AsyncSession = Depends(get_db),
) -> ReviewQueueResponse:
    """
    Ophthalmologist review queue with filtering and configurable prioritization.

    CLINICAL APPROVAL NOTICE: Prioritization rules are advisory only.
    The ordering of review is NOT validated for autonomous clinical triage.
    Clinicians retain full responsibility for determining review urgency.
    """
    if priority_sort not in _PRIORITY_RULES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown priority_sort '{priority_sort}'. Must be one of: {list(_PRIORITY_RULES)}",
        )

    # Base query: only completed screenings eligible for review
    q = (
        select(Screening)
        .where(
            Screening.is_deleted == False,
            Screening.status.in_(["completed", "reviewed", "failed", "recapture_requested", "in_review"]),
        )
    )

    # Facility filter (health-workers are already scoped; ophthalmologists may specify)
    if facility_id:
        q = q.where(Screening.facility_id == facility_id)

    # Date range
    if date_from:
        q = q.where(Screening.screened_at >= date_from)
    if date_to:
        q = q.where(Screening.screened_at <= date_to)

    # Quality filter
    if quality == "ungradeable":
        q = q.where(Screening.quality_verdict == "rejected")
    elif quality:
        q = q.where(Screening.quality_verdict == quality)

    # Provisional severity
    if provisional_severity is not None:
        q = q.where(Screening.dr_grade == provisional_severity)

    result = await db.execute(q)
    screenings: list[Screening] = list(result.scalars().all())

    # Build items (with associated reviews)
    items: list[ReviewQueueItem] = []
    for s in screenings:
        # Load associated review
        rev_res = await db.execute(
            select(ClinicianReview).where(ClinicianReview.screening_id == s.id)
        )
        review = rev_res.scalar_one_or_none()

        # Load patient name
        pat_res = await db.execute(
            select(Patient.first_name, Patient.last_name).where(Patient.id == s.patient_id)
        )
        pat_row = pat_res.one_or_none()
        patient_name = f"{pat_row[0]} {pat_row[1]}" if pat_row else None

        # Load AI flags
        is_uncertain, has_disagreement, concordance_status = await _load_ai_flags(db, s.id)

        # Apply uncertainty / disagreement filters (post-join, since they live in model_outputs)
        if uncertainty is True and not is_uncertain:
            continue
        if uncertainty is False and is_uncertain:
            continue
        if disagreement is True and not has_disagreement:
            continue
        if disagreement is False and has_disagreement:
            continue

        # Derive review status and apply filter
        resolved_status = _resolve_review_status(s, review)
        if review_status and resolved_status != review_status:
            continue

        item = ReviewQueueItem(
            screening_id=s.id,
            patient_id=s.patient_id,
            patient_name=patient_name,
            facility_id=s.facility_id,
            eye=s.eye,
            screened_at=s.screened_at,
            quality_verdict=s.quality_verdict,
            ai_dr_grade=s.dr_grade,
            ai_dr_grade_label=s.dr_grade_label,
            ai_confidence=s.dr_confidence,
            ai_referral_urgency=s.referral_urgency,
            ai_model_trained=s.model_trained,
            is_uncertain=is_uncertain,
            has_disagreement=has_disagreement,
            concordance_status=concordance_status,
            review_status=resolved_status,
            confirmed_dr_grade=review.confirmed_dr_grade if review else None,
            confirmed_grade_label=_DR_LABELS.get(review.confirmed_dr_grade) if review else None,
            review_version=review.review_version if review else None,
            locked_by_id=review.locked_by_id if review else None,
            lock_expires_at=review.lock_expires_at if review else None,
        )
        items.append(item)

    total = len(items)

    # Sort by the selected priority rule
    def _urgency_rank(item: ReviewQueueItem) -> int:
        return _URGENCY_ORDER.get(item.ai_referral_urgency or "none", 3)

    def _disagreement_rank(item: ReviewQueueItem) -> int:
        return 0 if (item.has_disagreement or item.is_uncertain) else 1

    def _screened_at_key(item: ReviewQueueItem) -> float:
        if not item.screened_at:
            return 0.0
        dt = item.screened_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    if priority_sort == "clinical_urgency":
        items.sort(key=lambda i: (_urgency_rank(i), _disagreement_rank(i), _screened_at_key(i)))
    elif priority_sort == "oldest_first":
        items.sort(key=_screened_at_key)
    elif priority_sort == "disagreement_first":
        items.sort(key=lambda i: (_disagreement_rank(i), _urgency_rank(i), _screened_at_key(i)))
    elif priority_sort == "highest_grade_first":
        items.sort(key=lambda i: (-(i.ai_dr_grade or -1), _screened_at_key(i)))

    rule_info = _PRIORITY_RULES[priority_sort]

    return ReviewQueueResponse(
        items=items[skip : skip + limit],
        total=total,
        skip=skip,
        limit=limit,
        priority_rule=rule_info["display"],
        priority_rule_version=rule_info["version"],
        priority_rule_requires_clinical_approval=True,
    )


# ---------------------------------------------------------------------------
# Case Lock
# ---------------------------------------------------------------------------

@router.post("/{screening_id}/review/claim", response_model=LockAcquireResponse)
async def claim_review_lock(
    screening_id: uuid.UUID,
    request: Request,
    ophthalmologist: User = Depends(require_ophthalmologist),
    db: AsyncSession = Depends(get_db),
) -> LockAcquireResponse:
    """
    Acquire an exclusive editing lock on a case.

    If another reviewer holds a non-expired lock, returns HTTP 409.
    Stale locks (past TTL) are automatically reclaimed.
    """
    s_res = await db.execute(
        select(Screening).where(Screening.id == screening_id, Screening.is_deleted == False)
    )
    screening = s_res.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    verify_facility_access(ophthalmologist, screening.facility_id)

    # Load or auto-initialise the review record
    rev_res = await db.execute(
        select(ClinicianReview).where(ClinicianReview.screening_id == screening_id)
    )
    review = rev_res.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if review and _lock_is_active(review, now):
        # Allow re-claim by the same user
        if review.locked_by_id != ophthalmologist.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Case is currently locked by another reviewer. "
                    f"Lock expires at {review.lock_expires_at.isoformat() if review.lock_expires_at else 'unknown'}."
                ),
            )

    expires_at = now + timedelta(minutes=_LOCK_TTL_MINUTES)

    if review:
        review.locked_by_id = ophthalmologist.id
        review.locked_at = now
        review.lock_expires_at = expires_at
    else:
        # Create a minimal draft placeholder so we can set the lock
        review = ClinicianReview(
            screening_id=screening_id,
            reviewer_id=ophthalmologist.id,
            confirmed_dr_grade=screening.dr_grade if screening.dr_grade is not None else -1,
            clinical_notes="",
            status="draft",
            locked_by_id=ophthalmologist.id,
            locked_at=now,
            lock_expires_at=expires_at,
        )
        db.add(review)

    await db.flush()

    await log_audit_event(
        db=db,
        event_type="review_lock_claimed",
        resource_type="clinician_review",
        user=ophthalmologist,
        facility_id=screening.facility_id,
        resource_id=str(screening_id),
        request=request,
    )

    return LockAcquireResponse(
        screening_id=screening_id,
        locked_by_id=ophthalmologist.id,
        locked_at=now,
        lock_expires_at=expires_at,
    )


@router.post("/{screening_id}/review/release", response_model=LockReleaseResponse)
async def release_review_lock(
    screening_id: uuid.UUID,
    request: Request,
    ophthalmologist: User = Depends(require_ophthalmologist),
    db: AsyncSession = Depends(get_db),
) -> LockReleaseResponse:
    """Release the editing lock on a case."""
    rev_res = await db.execute(
        select(ClinicianReview).where(ClinicianReview.screening_id == screening_id)
    )
    review = rev_res.scalar_one_or_none()

    if review:
        if review.locked_by_id and review.locked_by_id != ophthalmologist.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot release a lock held by another reviewer.",
            )
        review.locked_by_id = None
        review.locked_at = None
        review.lock_expires_at = None
        await db.flush()

    await log_audit_event(
        db=db,
        event_type="review_lock_released",
        resource_type="clinician_review",
        user=ophthalmologist,
        resource_id=str(screening_id),
        request=request,
    )
    return LockReleaseResponse(screening_id=screening_id)


# ---------------------------------------------------------------------------
# Submit / Amend Review
# ---------------------------------------------------------------------------

@router.post(
    "/{screening_id}/review",
    response_model=ClinicianReviewRead,
    status_code=status.HTTP_201_CREATED,
)
async def submit_clinician_review(
    screening_id: uuid.UUID,
    data: ClinicianReviewCreate,
    request: Request,
    ophthalmologist: User = Depends(require_ophthalmologist),
    db: AsyncSession = Depends(get_db),
) -> ClinicianReview:
    """
    Submit an authoritative ophthalmologist review decision.

    Strictly preserves AI model outputs as research findings while recording
    the human clinician's official diagnosis separately.

    Concurrency rules
    -----------------
    • On first submission: expected_version is ignored (no review exists yet).
    • On amendment: expected_version MUST match the current review_version or
      HTTP 409 is returned (lost-update prevention).
    • Amending a 'final' review requires a non-empty change_reason.
    • Every amendment appends a ReviewAmendment record.

    State badges
    ------------
    AI-generated → Awaiting review → In review (draft) → Clinician-reviewed (final/amended)
    """
    res = await db.execute(
        select(Screening).where(Screening.id == screening_id, Screening.is_deleted == False)
    )
    screening = res.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    verify_facility_access(ophthalmologist, screening.facility_id)

    existing_res = await db.execute(
        select(ClinicianReview).where(ClinicianReview.screening_id == screening_id)
    )
    existing_review = existing_res.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if existing_review:
        # ------------------------------------------------------------------
        # Amendment path — check concurrency version
        # ------------------------------------------------------------------
        if data.expected_version is not None and existing_review.review_version != data.expected_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Concurrency conflict: review has been modified since you opened it "
                    f"(server version: {existing_review.review_version}, "
                    f"your version: {data.expected_version}). "
                    "Reload the case and re-apply your changes."
                ),
            )

        # Check lock: only the lock-holder or admin may amend
        if _lock_is_active(existing_review, now):
            if existing_review.locked_by_id not in (ophthalmologist.id, None):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Case is locked by another reviewer. Acquire the lock before submitting.",
                )

        # Require change_reason when amending a final review
        if existing_review.status == "final" and not data.change_reason:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A change_reason is required when amending a previously-final review.",
            )

        # Append amendment record before mutating
        amendment = ReviewAmendment(
            review_id=existing_review.id,
            amended_by_id=ophthalmologist.id,
            previous_grade=existing_review.confirmed_dr_grade,
            new_grade=data.confirmed_dr_grade,
            previous_referral=existing_review.referral_recommendation,
            new_referral=data.referral_recommendation,
            previous_status=existing_review.status,
            new_status=data.status if existing_review.status == "final" else data.status,
            change_reason=data.change_reason,
            amendment_notes=data.clinical_notes,
        )
        db.add(amendment)

        # Mutate
        existing_review.confirmed_dr_grade = data.confirmed_dr_grade
        existing_review.macular_edema_present = data.macular_edema_present
        existing_review.is_ungradeable = data.is_ungradeable
        existing_review.recapture_requested = data.recapture_requested
        existing_review.referral_recommendation = data.referral_recommendation
        existing_review.follow_up_months = data.follow_up_months
        existing_review.clinical_notes = data.clinical_notes
        existing_review.status = "amended" if existing_review.status == "final" else data.status
        existing_review.reviewer_id = ophthalmologist.id
        existing_review.review_version = existing_review.review_version + 1
        # Release lock on final submission
        if data.status == "final":
            existing_review.locked_by_id = None
            existing_review.locked_at = None
            existing_review.lock_expires_at = None
        review = existing_review

    else:
        # ------------------------------------------------------------------
        # First submission
        # ------------------------------------------------------------------
        review = ClinicianReview(
            screening_id=screening_id,
            reviewer_id=ophthalmologist.id,
            confirmed_dr_grade=data.confirmed_dr_grade,
            macular_edema_present=data.macular_edema_present,
            is_ungradeable=data.is_ungradeable,
            recapture_requested=data.recapture_requested,
            referral_recommendation=data.referral_recommendation,
            follow_up_months=data.follow_up_months,
            clinical_notes=data.clinical_notes,
            status=data.status,
            review_version=1,
        )
        if data.status == "final":
            review.locked_by_id = None
        db.add(review)

    # Update screening status
    if data.recapture_requested:
        screening.status = "recapture_requested"
    elif data.status == "final":
        screening.status = "reviewed"

    await db.flush()

    await log_audit_event(
        db=db,
        event_type="clinician_review_submitted",
        resource_type="clinician_review",
        user=ophthalmologist,
        facility_id=screening.facility_id,
        resource_id=str(review.id),
        details={
            "screening_id": str(screening_id),
            "confirmed_grade": data.confirmed_dr_grade,
            "referral_recommendation": data.referral_recommendation,
            "is_ungradeable": data.is_ungradeable,
            "recapture_requested": data.recapture_requested,
            "review_version": review.review_version,
        },
        request=request,
    )

    # Eagerly reload with amendments to avoid lazy-load greenlet errors
    loaded_res = await db.execute(
        select(ClinicianReview)
        .where(ClinicianReview.id == review.id)
        .options(selectinload(ClinicianReview.amendments))
    )
    return loaded_res.scalar_one()


# ---------------------------------------------------------------------------
# Get Review
# ---------------------------------------------------------------------------

@router.get("/{screening_id}/review", response_model=ClinicianReviewRead)
async def get_clinician_review(
    screening_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClinicianReview:
    """Retrieve the ophthalmologist review decision and amendment history for a screening."""
    res = await db.execute(
        select(Screening).where(Screening.id == screening_id, Screening.is_deleted == False)
    )
    screening = res.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    verify_facility_access(current_user, screening.facility_id)

    review_res = await db.execute(
        select(ClinicianReview)
        .where(ClinicianReview.screening_id == screening_id)
        .options(selectinload(ClinicianReview.amendments))
    )
    review = review_res.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Clinician review has not been entered yet")

    return review


# ---------------------------------------------------------------------------
# Amendment History
# ---------------------------------------------------------------------------

@router.get("/{screening_id}/review/history", response_model=list[ReviewAmendmentRead])
async def get_review_amendment_history(
    screening_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ReviewAmendment]:
    """
    Retrieve the complete, immutable amendment audit trail for a screening review.
    Ordered from oldest to newest.
    """
    s_res = await db.execute(
        select(Screening).where(Screening.id == screening_id, Screening.is_deleted == False)
    )
    screening = s_res.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    verify_facility_access(current_user, screening.facility_id)

    rev_res = await db.execute(
        select(ClinicianReview).where(ClinicianReview.screening_id == screening_id)
    )
    review = rev_res.scalar_one_or_none()
    if not review:
        return []

    amend_res = await db.execute(
        select(ReviewAmendment)
        .where(ReviewAmendment.review_id == review.id)
        .order_by(ReviewAmendment.amended_at)
    )
    return list(amend_res.scalars().all())


# ---------------------------------------------------------------------------
# Reports & Summaries
# ---------------------------------------------------------------------------

_REPORTS_DIR = os.path.join(tempfile.gettempdir(), "retinashield_reports")
os.makedirs(_REPORTS_DIR, exist_ok=True)


@router.post(
    "/{screening_id}/report",
    response_model=ReportRead,
    status_code=status.HTTP_201_CREATED,
)
async def generate_screening_report(
    screening_id: uuid.UUID,
    data: ReportCreate,
    request: Request,
    ophthalmologist: User = Depends(require_ophthalmologist),
    db: AsyncSession = Depends(get_db),
) -> Report:
    """
    Generate an official clinical report or patient summary.

    Supports:
      - technical_report (image quality, provisional grade, probabilities, lesions, uncertainty, provenance)
      - patient_summary (plain-language findings, limitations, clinician next step; English & Hindi)
      - screening_summary / ophthalmology_referral (backward-compatible signed teleophthalmology report)

    Unsigned reports remain visibly marked and watermarked as PROVISIONAL.
    Signed reports require completed clinician review and include statutory disclaimers.
    """
    s_res = await db.execute(
        select(Screening).where(Screening.id == screening_id, Screening.is_deleted == False)
    )
    screening = s_res.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    verify_facility_access(ophthalmologist, screening.facility_id)

    p_res = await db.execute(select(Patient).where(Patient.id == screening.patient_id))
    patient = p_res.scalar_one_or_none()

    r_res = await db.execute(
        select(ClinicianReview).where(ClinicianReview.screening_id == screening_id)
    )
    clinician_review = r_res.scalar_one_or_none()

    # Determine if signature is required / requested
    # For legacy screening_summary without explicit is_signed flag, default to requiring signed final review
    should_sign = data.is_signed or (data.report_type in ("screening_summary", "ophthalmology_referral"))

    if should_sign:
        if not clinician_review:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot generate signed clinical report before ophthalmologist enters review",
            )
        if clinician_review.status == "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot sign a report while the review is still in draft status.",
            )

    # Load ModelOutput
    mo_res = await db.execute(
        select(ModelOutput)
        .where(ModelOutput.screening_id == screening_id)
        .order_by(ModelOutput.created_at.desc())
        .limit(1)
    )
    model_output = mo_res.scalar_one_or_none()

    # Load amendments
    amendments = []
    if clinician_review:
        amend_res = await db.execute(
            select(ReviewAmendment)
            .where(ReviewAmendment.review_id == clinician_review.id)
            .order_by(ReviewAmendment.amended_at)
        )
        amendments = list(amend_res.scalars().all())

    # Build report content & PDF bytes based on report type
    report_status = "signed" if should_sign else "draft"
    report_id = uuid.uuid4()

    if data.report_type == "patient_summary":
        summary_content = generate_patient_summary(
            screening=screening,
            patient=patient,
            clinician_review=clinician_review,
            language=data.language,
            signing_clinician_name=ophthalmologist.full_name if should_sign else None,
            is_signed=should_sign,
        )
        summary_content["report_id"] = str(report_id)
        # Ensure validation disclaimer is explicitly present
        summary_content["validation_disclaimer"] = _VALIDATION_DISCLAIMER
        pdf_bytes = generate_patient_summary_pdf(summary_content)
    else:
        # technical_report or legacy screening_summary
        summary_content = generate_technical_report(
            screening=screening,
            patient=patient,
            clinician_review=clinician_review,
            model_output=model_output,
            amendments=amendments,
            signing_clinician_name=ophthalmologist.full_name if should_sign else None,
            is_signed=should_sign,
        )
        summary_content["report_id"] = str(report_id)
        # Add legacy fields for backward compatibility
        summary_content["validation_disclaimer"] = _VALIDATION_DISCLAIMER
        summary_content["authoritative_clinician_diagnosis"] = {
            "clinician_name": ophthalmologist.full_name if should_sign else None,
            "clinician_id": str(ophthalmologist.id) if should_sign else None,
            "confirmed_dr_grade": clinician_review.confirmed_dr_grade if clinician_review else None,
            "confirmed_dr_label": _DR_LABELS.get(clinician_review.confirmed_dr_grade, "Unknown") if clinician_review else "Awaiting Review",
            "is_ungradeable": clinician_review.is_ungradeable if clinician_review else False,
            "recapture_requested": clinician_review.recapture_requested if clinician_review else False,
            "macular_edema_present": clinician_review.macular_edema_present if clinician_review else False,
            "referral_recommendation": clinician_review.referral_recommendation if clinician_review else None,
            "follow_up_months": clinician_review.follow_up_months if clinician_review else None,
            "clinical_notes": clinician_review.clinical_notes if clinician_review else "",
            "review_status": clinician_review.status if clinician_review else "pending",
            "reviewed_at": clinician_review.reviewed_at.isoformat() if clinician_review and clinician_review.reviewed_at else None,
            "review_version": clinician_review.review_version if clinician_review else 0,
            "signature_status": "SIGNED_BY_OPHTHALMOLOGIST" if should_sign else "PROVISIONAL_AWAITING_SIGNATURE",
        }
        summary_content["ai_research_screening_findings"]["section_label"] = "AI-GENERATED RESEARCH SCREENING RESULT"
        pdf_bytes = generate_technical_report_pdf(summary_content)

    # Save PDF to disk
    pdf_path = os.path.join(_REPORTS_DIR, f"{report_id}_{data.report_type}_{data.language}.pdf")
    try:
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
    except Exception as exc:
        logger.warning("Failed to save PDF to %s: %s", pdf_path, exc)
        pdf_path = None

    report = Report(
        id=report_id,
        screening_id=screening_id,
        generated_by_id=ophthalmologist.id,
        signed_by_id=ophthalmologist.id if should_sign else None,
        report_type=data.report_type,
        status=report_status,
        summary_json=summary_content,
        file_path=pdf_path,
    )
    db.add(report)
    await db.flush()
    await db.refresh(report)

    await log_audit_event(
        db=db,
        event_type="clinical_report_generated",
        resource_type="report",
        user=ophthalmologist,
        facility_id=screening.facility_id,
        resource_id=str(report.id),
        details={
            "screening_id": str(screening_id),
            "report_type": data.report_type,
            "language": data.language,
            "status": report_status,
            "review_version": clinician_review.review_version if clinician_review else 0,
        },
        request=request,
    )

    return report


@router.get("/{screening_id}/reports", response_model=list[ReportRead])
async def list_screening_reports(
    screening_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Report]:
    """Retrieve all reports (draft and signed) generated for this screening."""
    s_res = await db.execute(
        select(Screening).where(Screening.id == screening_id, Screening.is_deleted == False)
    )
    screening = s_res.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    verify_facility_access(current_user, screening.facility_id)

    rep_res = await db.execute(
        select(Report)
        .where(Report.screening_id == screening_id)
        .order_by(Report.created_at.desc())
    )
    return list(rep_res.scalars().all())


@router.get("/{screening_id}/reports/{report_id}", response_model=ReportRead)
async def get_report_by_id(
    screening_id: uuid.UUID,
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Report:
    """Retrieve a specific report by report ID."""
    rep_res = await db.execute(
        select(Report).where(Report.id == report_id, Report.screening_id == screening_id)
    )
    report = rep_res.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    return report


@router.get("/{screening_id}/reports/{report_id}/pdf")
async def download_report_pdf(
    screening_id: uuid.UUID,
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download printable PDF for the specified report."""
    rep_res = await db.execute(
        select(Report).where(Report.id == report_id, Report.screening_id == screening_id)
    )
    report = rep_res.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    pdf_bytes: bytes | None = None
    if report.file_path and os.path.isfile(report.file_path):
        try:
            with open(report.file_path, "rb") as f:
                pdf_bytes = f.read()
        except Exception:
            pdf_bytes = None

    if not pdf_bytes:
        # Re-generate dynamically if cached file is missing
        summary_content = report.summary_json
        if report.report_type == "patient_summary":
            pdf_bytes = generate_patient_summary_pdf(summary_content)
        else:
            pdf_bytes = generate_technical_report_pdf(summary_content)

    filename = f"RetinaShield_{report.report_type}_{report.id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )


@router.post(
    "/{screening_id}/reports/{report_id}/voice",
    response_model=VoicePlaybackResponse,
)
async def generate_report_voice(
    screening_id: uuid.UUID,
    report_id: uuid.UUID,
    data: VoicePlaybackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VoicePlaybackResponse:
    """
    Opt-in offline speech playback for patient summaries using local system TTS.

    Never transmits patient data to external speech APIs.
    If no local voice is found for the requested language, falls back to text.
    """
    rep_res = await db.execute(
        select(Report).where(Report.id == report_id, Report.screening_id == screening_id)
    )
    report = rep_res.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    spoken_script = report.summary_json.get("spoken_script")
    if not spoken_script:
        # Fallback to plain text explanation
        spoken_script = report.summary_json.get("findings_explanation", "No spoken summary available.")

    res = synthesize_offline_audio(
        spoken_text=spoken_script,
        language=data.language,
        voice_consent=data.voice_consent,
    )

    return VoicePlaybackResponse(
        voice_supported=res.voice_supported,
        fallback_to_text=res.fallback_to_text,
        voice_name=res.voice_name,
        language=res.language,
        audio_base64=res.audio_base64,
        audio_format=res.audio_format,
        spoken_text=res.spoken_text,
        status_message=res.status_message,
    )


@router.get("/{screening_id}/report", response_model=ReportRead)
async def get_screening_report(
    screening_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Report:
    """Retrieve the most recent signed screening report (backward compatible)."""
    s_res = await db.execute(
        select(Screening).where(Screening.id == screening_id, Screening.is_deleted == False)
    )
    screening = s_res.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    verify_facility_access(current_user, screening.facility_id)

    rep_res = await db.execute(
        select(Report)
        .where(Report.screening_id == screening_id)
        .order_by(Report.created_at.desc())
    )
    report = rep_res.scalars().first()
    if not report:
        raise HTTPException(status_code=404, detail="No signed report found for this screening")

    return report

