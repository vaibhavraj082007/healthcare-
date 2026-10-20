"""Phase 4 Part A — case severity bands and the tracking row lifecycle.

Severity band mapping (fixed, not generated per case):

    ICDR grade 0–1        -> Low
    ICDR grade 2          -> Medium
    ICDR grade 3–4        -> High
    dual-engine "Flagged for Review"   -> High (regardless of grade)

Statuses march forward only: New -> Claimed -> Contacted -> Reviewed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .models import AIFinding, CaseTracking

# Severity bands
SEVERITY_LOW = "Low"
SEVERITY_MEDIUM = "Medium"
SEVERITY_HIGH = "High"

# Case lifecycle statuses
STATUS_NEW = "New"
STATUS_CLAIMED = "Claimed"
STATUS_CONTACTED = "Contacted"
STATUS_REVIEWED = "Reviewed"
STATUS_FLOW = [STATUS_NEW, STATUS_CLAIMED, STATUS_CONTACTED, STATUS_REVIEWED]


def severity_band_for(finding: AIFinding) -> str:
    """Map a completed finding to its clinical urgency band."""
    if (finding.consistency_status or "").lower() == "flagged for review":
        return SEVERITY_HIGH
    grade = finding.icdr_grade
    if grade is None:
        return SEVERITY_LOW
    if grade <= 1:
        return SEVERITY_LOW
    if grade == 2:
        return SEVERITY_MEDIUM
    return SEVERITY_HIGH


def ensure_case_tracking(db: Session, finding: AIFinding) -> CaseTracking | None:
    """Create the tracking row the moment a report exists; keep it current.

    Idempotent: re-running recomputes the band (a re-analysis may change the
    grade) but never rewinds a status.
    """
    if finding.icdr_grade is None or finding.analysis_status != "completed":
        return None

    row = (
        db.query(CaseTracking)
        .filter(CaseTracking.image_id == finding.image_id)
        .first()
    )
    if row is None:
        row = CaseTracking(
            image_id=finding.image_id,
            severity_band=severity_band_for(finding),
            status=STATUS_NEW,
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    band = severity_band_for(finding)
    if row.severity_band != band:
        row.severity_band = band
        db.commit()
    return row


def backfill_case_tracking(db: Session) -> int:
    """Backfill tracking rows for findings that already have reports."""
    findings = (
        db.query(AIFinding)
        .filter(AIFinding.analysis_status == "completed")
        .all()
    )
    count = 0
    for finding in findings:
        if ensure_case_tracking(db, finding) is not None:
            count += 1
    return count