"""
RetinaShield — Analysis API Routes

Triggers the MATLAB + YOLOv8 analysis pipeline on screening images.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.models.screening import Screening, ScreeningImage
from app.schemas.screening import AnalysisRequest, AnalysisResponse
from app.schemas.analysis_result import AnalysisResult
from app.services.matlab_bridge import matlab_bridge
from app.services.yolo_service import yolo_service
from app.services.image_store import image_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.post("/run", response_model=AnalysisResponse)
async def run_analysis(
    request: AnalysisRequest,
    db: AsyncSession = Depends(get_db),
) -> AnalysisResponse:
    """
    Run the full DR screening pipeline on a screening's images.

    Pipeline stages:
      1. MATLAB: Quality Assessment → Enhancement → Structure Analysis → Classification → Grad-CAM
      2. YOLOv8: Lesion Detection (Python service)

    Results are stored in the screening record and returned in the response.

    NOTE: All outputs are labelled as RESEARCH SCREENING RESULTS.
    """
    # Fetch screening
    result = await db.execute(
        select(Screening).where(Screening.id == request.screening_id)
    )
    screening = result.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    # Check if already analyzed (and not force-rerun)
    if screening.status == "completed" and not request.force_rerun:
        return AnalysisResponse(
            screening_id=screening.id,
            status="already_completed",
            message="Analysis already completed. Set force_rerun=true to re-analyze.",
            result=AnalysisResult(**screening.analysis_result) if screening.analysis_result else None,
        )

    # Get images for this screening
    img_result = await db.execute(
        select(ScreeningImage).where(ScreeningImage.screening_id == screening.id)
    )
    images = img_result.scalars().all()

    if not images:
        raise HTTPException(
            status_code=400,
            detail="No images uploaded for this screening. Upload fundus images first."
        )

    # Update status
    screening.status = "processing"
    await db.flush()

    # Process the first image (primary analysis)
    # In production, you'd process each eye separately
    primary_image = images[0]

    try:
        # Get the actual file path for pipeline processing
        image_path = await image_store.get_image_path(primary_image.stored_filename)

        # Create output directory for this analysis
        output_dir = str(
            Path(settings.image_storage_path) / "analysis" / str(screening.id)
        )

        # --- Stage 1: MATLAB Pipeline ---
        combined_result = None
        if request.run_matlab:
            logger.info(
                f"Running MATLAB pipeline (mode={matlab_bridge.mode}) "
                f"on screening {screening.id}"
            )
            combined_result = await matlab_bridge.run_pipeline(image_path, output_dir)

        # --- Stage 2: YOLOv8 Lesion Detection ---
        if request.run_yolo:
            logger.info(f"Running YOLOv8 lesion detection on screening {screening.id}")
            lesion_result = await yolo_service.detect_lesions(image_path)

            if combined_result:
                combined_result.lesion_detection = lesion_result
            else:
                combined_result = AnalysisResult(
                    lesion_detection=lesion_result,
                )

        if combined_result is None:
            raise ValueError("No analysis stages were executed")

        # Fill in identifiers
        combined_result.image_id = primary_image.id
        combined_result.patient_id = screening.patient_id
        combined_result.facility_id = screening.facility_id

        # --- Update screening record ---
        screening.analysis_result = combined_result.model_dump(mode="json")
        screening.status = "completed"
        screening.analyzed_at = datetime.now(timezone.utc)

        # Denormalized summary fields
        if combined_result.quality_assessment:
            screening.quality_verdict = combined_result.quality_assessment.overall_quality
        if combined_result.severity_classification:
            sc = combined_result.severity_classification
            screening.dr_grade = sc.predicted_grade
            screening.dr_grade_label = sc.grade_label
            screening.dr_confidence = sc.confidence
            screening.model_trained = sc.model_trained
        if combined_result.referral_recommendation:
            screening.referral_urgency = combined_result.referral_recommendation.urgency

        # Update image record with derived paths
        if combined_result.enhancement:
            primary_image.enhanced_image_path = combined_result.enhancement.enhanced_image_path
        if combined_result.severity_classification:
            primary_image.gradcam_image_path = combined_result.severity_classification.gradcam_heatmap_path
        if combined_result.structure_analysis and combined_result.structure_analysis.vasculature:
            primary_image.vessel_mask_path = combined_result.structure_analysis.vasculature.segmentation_mask_path

        await db.flush()

        logger.info(f"Analysis completed for screening {screening.id}")
        return AnalysisResponse(
            screening_id=screening.id,
            status="completed",
            message="Analysis pipeline completed. RESEARCH SCREENING RESULT — review by ophthalmologist required.",
            result=combined_result,
        )

    except Exception as e:
        logger.error(f"Analysis failed for screening {screening.id}: {e}")
        screening.status = "failed"
        await db.flush()

        return AnalysisResponse(
            screening_id=screening.id,
            status="failed",
            message=f"Analysis pipeline failed: {str(e)}",
            result=None,
        )


@router.get("/status/{screening_id}")
async def get_analysis_status(
    screening_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Check the analysis status for a screening."""
    result = await db.execute(
        select(Screening).where(Screening.id == screening_id)
    )
    screening = result.scalar_one_or_none()
    if not screening:
        raise HTTPException(status_code=404, detail="Screening not found")

    return {
        "screening_id": str(screening.id),
        "status": screening.status,
        "quality_verdict": screening.quality_verdict,
        "dr_grade": screening.dr_grade,
        "dr_grade_label": screening.dr_grade_label,
        "referral_urgency": screening.referral_urgency,
        "model_trained": screening.model_trained,
        "analyzed_at": screening.analyzed_at.isoformat() if screening.analyzed_at else None,
        "disclaimer": screening.disclaimer,
    }


@router.get("/pipeline-info")
async def get_pipeline_info() -> dict:
    """Get information about the current pipeline configuration."""
    return {
        "pipeline_version": settings.pipeline_version,
        "matlab_mode": matlab_bridge.mode,
        "matlab_available": matlab_bridge.mode != "fallback",
        "yolo_available": yolo_service.is_ready,
        "yolo_model_trained": yolo_service.is_ready,
        "efficientnet_model_trained": False,  # Will be updated when MATLAB model is loaded
        "disclaimer": "RESEARCH SCREENING TOOL — Not for autonomous clinical diagnosis.",
        "note": "All pipeline outputs require review by a qualified ophthalmologist.",
    }
