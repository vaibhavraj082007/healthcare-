import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..ml.consistency import CLASSIFIER_ONLY, check_consistency
from ..ml.preprocessing import preprocess_image
from ..ml.registry import registry
from ..ml.reports import ensure_report, model_signature
from ..models import AIFinding, ImageUpload, User
from ..schemas import FindingOut
from PIL import Image

router = APIRouter(prefix="/analyze", tags=["analyze"])


@router.post("/{image_id}", response_model=FindingOut)
def analyze_image(
    image_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    upload = db.query(ImageUpload).filter(ImageUpload.image_id == image_id).first()
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload not found")

    finding = db.query(AIFinding).filter(AIFinding.image_id == image_id).first()
    if finding is None:
        finding = AIFinding(image_id=image_id, analysis_status="queued")
        db.add(finding)

    finding.analysis_status = "running"
    db.commit()

    try:
        if registry.classifier is None:
            raise RuntimeError(
                registry.classifier_error
                or "Classifier weights not loaded — analysis unavailable"
            )

        image = Image.open(Path(upload.file_path)).convert("RGB")
        tensor = preprocess_image(image, size=380)

        # Engine B — EfficientNet-B0 severity classifier
        cls_result = registry.classifier.predict(tensor)

        # Engine A — YOLOv8 lesion detection (skipped honestly when unavailable)
        lesion_counts: dict[str, int] = {}
        lesion_list: list[dict] = []
        if registry.detector is not None:
            image_bytes = Path(upload.file_path).read_bytes()
            det_result = registry.detector.predict(image_bytes)
            lesion_counts = det_result.lesion_counts
            # Persist detection boxes (normalized 0..1 to the original image)
            # so the report can compute real lesion-to-macula / hotspot overlap
            # at generation time (Phase-4-A fixes).
            from collections import defaultdict

            detector = registry.detector
            with Image.open(Path(upload.file_path)) as src:
                iw, ih = src.size
            boxes_by_type: dict[str, list[list[float]]] = defaultdict(list)
            confs_by_type: dict[str, list[float]] = defaultdict(list)
            for det in det_result.detections:
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
                    "confidence": [
                        round(c, 4) for c in confs_by_type[label]
                    ],
                }
                for label in sorted(boxes_by_type)
            ]

        # Dual-engine consistency
        if registry.detector is not None:
            consistency = check_consistency(lesion_counts, cls_result.grade)
        else:
            consistency = CLASSIFIER_ONLY

        provenance = {
            "classifier": {
                "model": "EfficientNet-B0",
                "trained_on": registry.classifier._meta.get("trained_on", "unknown"),
                "validation_qwk": registry.classifier._meta.get("validation_qwk"),
            },
            "detector": (
                registry.detector.PROVENANCE
                if registry.detector is not None
                else "Lesion detector unavailable — analysis ran classifier-only"
            ),
        }

        finding.lesion_list = json.dumps(lesion_list)
        finding.lesion_count = sum(lesion_counts.values())
        finding.icdr_grade = cls_result.grade
        finding.icdr_confidence = round(cls_result.confidence, 4)
        finding.consistency_status = consistency
        finding.analysis_status = "completed"
        finding.model_provenance = json.dumps(provenance)
        finding.model_version = model_signature(registry.classifier)
        finding.error = None
        finding.analyzed_at = datetime.utcnow()
        db.commit()

        # Phase 3 — build the explainable report (Grad-CAM + NLG) automatically.
        # Never let a report failure fail the analysis response.
        try:
            ensure_report(db, finding)
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger("netrascan.analyze").warning(
                "Report generation failed for %s (analysis itself succeeded): %s",
                image_id,
                exc,
            )

        return FindingOut.model_validate(finding)

    except Exception as exc:  # noqa: BLE001 — surface as a failed analysis honestly
        finding.analysis_status = "failed"
        finding.error = str(exc)
        db.commit()
        raise HTTPException(status_code=503, detail=f"Analysis failed: {exc}")