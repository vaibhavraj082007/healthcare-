"""Phase 3 — regenerate explainable reports for every completed analysis.

Used as a batch/pre-verification pass (demo-day reliability) and chained into
the training watchdog so that once the classifier finishes, demo reports are
regenerated from the final weights. Idempotent: only stale or heatmap-less
reports are rebuilt unless --force is given.

Run:  python generate_reports.py [--force]   (from backend/)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import SessionLocal, engine
from app.ml.registry import registry
from app.ml.reports import ensure_report
from app.models import AIFinding


def _ensure_columns():
    from sqlalchemy import text

    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE ai_findings ADD COLUMN model_version VARCHAR DEFAULT NULL"))
            conn.commit()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Rebuild every report")
    args = parser.parse_args()

    _ensure_columns()
    registry.load()
    if registry.classifier is None:
        print("PANIC: classifier weights unavailable — cannot generate Grad-CAM.", file=sys.stderr)
        return 1

    db = SessionLocal()
    findings = (
        db.query(AIFinding)
        .filter(AIFinding.analysis_status == "completed", AIFinding.icdr_grade.isnot(None))
        .all()
    )
    print(f"Found {len(findings)} completed analyses.\n")

    ok = skipped = failed = 0
    for finding in findings:
        t0 = time.time()
        try:
            report = ensure_report(db, finding, force=args.force)
            if report is None:
                skipped += 1
                continue
            mode = "heatmap+report" if report.gradcam_path else "report(no heatmap)"
            print(
                f"  {finding.image_id[:12]}  grade={finding.icdr_grade}  "
                f"{mode}  {time.time() - t0:.1f}s"
            )
            ok += 1
        except Exception as exc:  # noqa: BLE001 — a bad row must not kill the batch
            failed += 1
            print(f"  {finding.image_id[:12]}  FAILED: {exc}", file=sys.stderr)

    db.close()
    print(f"\nDone: {ok} reports generated, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())