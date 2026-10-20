"""One-shot maintenance script for the Phase-4-A report fixes.

For every completed analysis this:
  1. enriches the stored lesion list with real detection boxes (normalized 0..1)
     for the handful of real pre-fix analyses that only kept {type,count} —
     demo-seed rows (provenance "(demo seed)" / demo_samples files) are left
     untouched so their synthetic counts are not reprocessed, and
  2. force-regenerates the universal report (header snapshot + full lesion
     breakdown + grade basis + macular-oedema note + computed region
     description) via ``ensure_report(force=True)``.

Run from the backend venv:  python -m app.refresh_reports
"""

import json
import logging
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

from .database import SessionLocal
from .ml.registry import registry
from .ml.reports import ensure_report
from .models import AIFinding, ImageUpload, ScreeningReport

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("refresh_reports")


def _entries_have_boxes(lesion_list: str) -> bool:
    try:
        raw = json.loads(lesion_list or "[]")
    except json.JSONDecodeError:
        return False
    return any(isinstance(item.get("boxes"), list) for item in raw)


def _populate_image_quality(db, report, upload) -> None:
    """Backfill the quality snapshot columns from the source upload row."""
    if report.image_quality is None:
        report.image_quality = upload.quality_status if upload is not None else None
    if report.quality_score is None:
        report.quality_score = upload.quality_score if upload is not None else None


def _is_demo(upload: ImageUpload, provenance: str) -> bool:
    demo_marker = "(demo seed)" in provenance or "demo seed" in provenance.lower()
    path_marker = bool(upload.file_path and "demo_samples" in upload.file_path.replace("\\", "/"))
    return demo_marker or path_marker


def _enrich_boxes(db, finding: AIFinding, upload: ImageUpload) -> bool:
    """Re-run the detector for a real pre-fix analysis that lacks boxes.
    Returns True when the stored lesion list was updated."""
    if _entries_have_boxes(finding.lesion_list or "[]"):
        return False
    if registry.detector is None:
        logger.warning("detector offline — cannot enrich %s", finding.image_id)
        return False

    from PIL import Image as PILImage

    path = Path(upload.file_path)
    if not path.exists():
        logger.warning("missing file for %s — skipping enrichment", finding.image_id)
        return False

    data = path.read_bytes()
    res = registry.detector.predict(data)
    with PILImage.open(path) as src:
        iw, ih = src.size

    boxes_by_type: dict[str, list[list[float]]] = defaultdict(list)
    confs_by_type: dict[str, list[float]] = defaultdict(list)
    for det in res.detections:
        x1, y1, x2, y2 = det.box
        boxes_by_type[det.label].append(
            [round(x1 / iw, 4), round(y1 / ih, 4), round(x2 / iw, 4), round(y2 / ih, 4)]
        )
        confs_by_type[det.label].append(det.confidence)
    lesion_list = [
        {
            "type": label,
            "count": len(boxes_by_type[label]),
            "boxes": boxes_by_type[label],
            "confidence": [round(c, 4) for c in confs_by_type[label]],
        }
        for label in sorted(boxes_by_type)
    ]
    finding.lesion_list = json.dumps(lesion_list)
    finding.lesion_count = sum(b["count"] for b in lesion_list)
    logger.info("enriched %s with %d detection boxes", finding.image_id[:8], finding.lesion_count)
    return True


def main() -> None:
    # Offline maintenance run: RAM-floor the Heatmap guard so every completed
    # analysis deterministically gets its Grad-CAM (demo data must never be
    # missing a heatmap just because the machine is under memory pressure).
    import os

    os.environ.setdefault("NETRASCAN_RAM_FLOOR_MB", "0")
    registry.load()
    db = SessionLocal()
    try:
        # Additive migration in case main.py never fired (paranoia only).
        for col in (
            "patient_id", "patient_name", "patient_age", "patient_gender",
            "referring_phc", "submitting_worker", "scan_date", "eye_laterality",
            "image_quality", "quality_score",
        ):
            db.execute(text(f"ALTER TABLE screening_reports ADD COLUMN {col} TEXT"))
            db.commit()
    except Exception:
        db.rollback()
        logger.info("header columns already present")
    try:
        db.execute(text("ALTER TABLE image_uploads ADD COLUMN eye_laterality VARCHAR DEFAULT 'unknown'"))
        db.commit()
    except Exception:
        db.rollback()
        logger.info("image_uploads.eye_laterality already present")

    findings = (
        db.query(AIFinding).filter(AIFinding.analysis_status == "completed").all()
    )
    logger.info("found %d completed analyses", len(findings))

    enriched = 0
    regenerated = 0
    heatmapped = 0
    for finding in findings:
        upload = db.query(ImageUpload).filter(ImageUpload.image_id == finding.image_id).first()
        provenance = finding.model_provenance or "{}"
        is_demo = upload is not None and _is_demo(upload, provenance)
        if upload is not None and not is_demo:
            if _enrich_boxes(db, finding, upload):
                enriched += 1

        report = ensure_report(db, finding, force=True)
        if report is not None:
            _populate_image_quality(db, report, upload)
            db.commit()
            regenerated += 1
            if report.gradcam_path:
                heatmapped += 1

    db.commit()
    total = db.query(ScreeningReport).count()
    logger.info(
        "done — enriched=%d regenerated=%d (with heatmap=%d) total_reports=%d",
        enriched, regenerated, heatmapped, total,
    )


if __name__ == "__main__":
    main()