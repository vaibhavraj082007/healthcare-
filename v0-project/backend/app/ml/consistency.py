"""Dual-engine consistency check.

Maps YOLOv8 lesion output (type + count) to a rough expected severity band,
compares it against the EfficientNet-B0 predicted ICDR grade, and reports
whether the two engines agree.
"""

from __future__ import annotations

from typing import Optional

LESION_WEIGHTS = {
    "microaneurysm": 0.5,
    "hemorrhage": 1.5,
    "hard_exudate": 1.2,
    "soft_exudate": 1.5,
}


def lesion_severity_band(lesion_counts: dict[str, int]) -> tuple[int, int]:
    """Rough expected ICDR band [low, high] derived from lesion load."""
    score = 0.0
    for label, count in lesion_counts.items():
        score += LESION_WEIGHTS.get(label, 1.0) * count

    if score <= 0:
        return 0, 0
    if score <= 2:
        return 0, 1
    if score <= 5:
        return 1, 2
    if score <= 9:
        return 2, 3
    return 3, 4


def lesion_grade_estimate(lesion_counts: dict[str, int]) -> int:
    """Single 0-4 position for the visual severity scale.

    Deliberately derived from `lesion_severity_band` — the exact mapping the
    dual-engine consistency check uses — so the scale can never drift from what
    `check_consistency` saw. The band's inclusive upper bound is used (the
    worst severity the detected lesion load alone could support).
    """
    return lesion_severity_band(lesion_counts)[1]


CONSISTENT = "Consistent"
FLAGGED = "Flagged for Review"
LOW_LESION_EVIDENCE = "Review - Low Lesion Evidence"
CLASSIFIER_ONLY = "Classifier only"


def check_consistency(
    lesion_counts: dict[str, int],
    classifier_grade: Optional[int],
) -> str:
    """Return 'Consistent', 'Flagged for Review' or 'Review - Low Lesion Evidence'."""
    if classifier_grade is None:
        return FLAGGED

    if not lesion_counts:
        # Zero lesions detected: a grade >= 2 (moderate+) is suspicious and may
        # reflect a lesion-detector miss rather than genuine disagreement.
        if classifier_grade >= 2:
            return LOW_LESION_EVIDENCE
        return CONSISTENT

    low, high = lesion_severity_band(lesion_counts)

    # No lesions but a moderate+ grading is suspicious; heavy lesion load with
    # a no-DR grading is also suspicious.
    if low <= classifier_grade <= high:
        return CONSISTENT
    return FLAGGED