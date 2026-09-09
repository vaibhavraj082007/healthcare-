"""
RetinaShield — MATLAB Bridge Service

Integrates with MATLAB for fundus image analysis. Supports three modes:
  - "engine":   Direct MATLAB Engine for Python (requires full MATLAB installation)
  - "mcr":      Compiled MATLAB Runtime (requires MCR + compiled package)
  - "fallback": Python-only preprocessing (no MATLAB required)

The fallback mode implements basic quality checks and enhancement using
OpenCV/scikit-image, but does NOT replicate the full MATLAB pipeline
(especially EfficientNet-B0 classification and Grad-CAM).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from app.config import settings
from app.schemas.analysis_result import (
    DISCLAIMER,
    AnalysisResult,
    Enhancement,
    Macula,
    OpticDisc,
    QualityAssessment,
    ReferralRecommendation,
    SeverityClassification,
    StructureAnalysis,
    Vasculature,
)

logger = logging.getLogger(__name__)


class MatlabBridge:
    """Bridge to MATLAB analysis pipeline with Python fallback."""

    def __init__(self) -> None:
        self.mode = settings.matlab_mode
        self._engine = None
        logger.info(f"MATLAB Bridge initialized in '{self.mode}' mode")

        if self.mode == "engine":
            self._init_engine()
        elif self.mode == "mcr":
            self._init_mcr()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _init_engine(self) -> None:
        """Initialize MATLAB Engine for Python."""
        try:
            import matlab.engine  # type: ignore

            logger.info("Starting MATLAB Engine...")
            self._engine = matlab.engine.start_matlab()
            # Add MATLAB source directory to path
            matlab_src = str(Path(__file__).parent.parent.parent / "matlab" / "src")
            self._engine.addpath(matlab_src, nargout=0)
            logger.info("MATLAB Engine started successfully")
        except ImportError:
            logger.error(
                "matlab.engine not installed. Install from your MATLAB installation: "
                "cd $MATLAB_ROOT/extern/engines/python && pip install ."
            )
            logger.warning("Falling back to Python-only mode")
            self.mode = "fallback"
        except Exception as e:
            logger.error(f"Failed to start MATLAB Engine: {e}")
            logger.warning("Falling back to Python-only mode")
            self.mode = "fallback"

    def _init_mcr(self) -> None:
        """Initialize compiled MATLAB Runtime package."""
        try:
            # The compiled package name would be set via config
            logger.warning(
                "MCR mode not yet configured. Set MATLAB_COMPILED_PACKAGE in .env. "
                "Falling back to Python-only mode."
            )
            self.mode = "fallback"
        except Exception as e:
            logger.error(f"Failed to initialize MCR: {e}")
            self.mode = "fallback"

    # ------------------------------------------------------------------
    # Main pipeline entry
    # ------------------------------------------------------------------

    async def run_pipeline(
        self, image_path: str, output_dir: str
    ) -> AnalysisResult:
        """
        Run the full analysis pipeline on a fundus image.

        Routes to MATLAB or Python fallback depending on configured mode.
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        if self.mode == "engine":
            return await self._run_matlab_engine(image_path, output_dir)
        elif self.mode == "mcr":
            return await self._run_matlab_mcr(image_path, output_dir)
        else:
            return await self._run_python_fallback(image_path, output_dir)

    # ------------------------------------------------------------------
    # MATLAB Engine mode
    # ------------------------------------------------------------------

    async def _run_matlab_engine(
        self, image_path: str, output_dir: str
    ) -> AnalysisResult:
        """Run pipeline via MATLAB Engine for Python."""
        if self._engine is None:
            logger.error("MATLAB Engine not available, using fallback")
            return await self._run_python_fallback(image_path, output_dir)

        try:
            # Call the MATLAB orchestrator
            result_struct = self._engine.run_pipeline(
                image_path, output_dir, nargout=1
            )

            # Convert MATLAB struct to Python dict, then to Pydantic model
            result_dict = self._matlab_struct_to_dict(result_struct)
            return AnalysisResult(**result_dict)

        except Exception as e:
            logger.error(f"MATLAB Engine pipeline failed: {e}")
            return await self._run_python_fallback(image_path, output_dir)

    def _matlab_struct_to_dict(self, struct: Any) -> dict:
        """Convert a MATLAB struct (returned via Engine) to a Python dict."""
        if hasattr(struct, "_fieldnames"):
            return {
                field: self._matlab_struct_to_dict(getattr(struct, field))
                for field in struct._fieldnames
            }
        elif isinstance(struct, (list, tuple)):
            return [self._matlab_struct_to_dict(item) for item in struct]
        else:
            return struct

    # ------------------------------------------------------------------
    # MCR mode (placeholder)
    # ------------------------------------------------------------------

    async def _run_matlab_mcr(
        self, image_path: str, output_dir: str
    ) -> AnalysisResult:
        """Run pipeline via compiled MATLAB Runtime."""
        logger.warning("MCR mode not yet implemented, using fallback")
        return await self._run_python_fallback(image_path, output_dir)

    # ------------------------------------------------------------------
    # Python Fallback
    # ------------------------------------------------------------------

    async def _run_python_fallback(
        self, image_path: str, output_dir: str
    ) -> AnalysisResult:
        """
        Python-only fallback pipeline.

        Provides basic IQA and enhancement using OpenCV/scikit-image.
        Does NOT provide EfficientNet-B0 classification or Grad-CAM
        (those require MATLAB).
        """
        logger.info(f"[Python Fallback] Processing: {image_path}")
        start_time = datetime.now(timezone.utc)

        try:
            import cv2
        except ImportError:
            logger.error("OpenCV not installed. Run: pip install opencv-python-headless")
            raise

        # Read image
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")

        output_path = Path(output_dir)
        base_name = Path(image_path).stem

        # --- Quality Assessment (Python fallback) ---
        quality = self._fallback_quality_assessment(img)

        # --- Enhancement ---
        enhancement = self._fallback_enhancement(img, output_path, base_name)

        # --- Structure Analysis ---
        structures = self._fallback_structure_analysis(img, output_path, base_name)

        # --- Classification: NOT AVAILABLE in fallback ---
        classification = SeverityClassification(
            model="EfficientNet-B0",
            model_trained=False,
            predicted_grade=-1,
            grade_label="UNAVAILABLE — Requires MATLAB (Python fallback mode active)",
            confidence=0.0,
            class_probabilities=[0.2, 0.2, 0.2, 0.2, 0.2],
        )

        # --- Referral ---
        referral = ReferralRecommendation(
            urgency="none",
            reason=(
                "Classification unavailable in Python fallback mode. "
                "MATLAB required for DR severity grading. Clinical evaluation needed."
            ),
            suggested_followup_weeks=0,
        )

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        return AnalysisResult(
            analysis_id=uuid.uuid4(),
            pipeline_version=settings.pipeline_version + "-python-fallback",
            timestamp=datetime.now(timezone.utc),
            disclaimer=DISCLAIMER,
            quality_assessment=quality,
            enhancement=enhancement,
            structure_analysis=structures,
            severity_classification=classification,
            referral_recommendation=referral,
            processing_time_seconds=elapsed,
        )

    def _fallback_quality_assessment(self, img: np.ndarray) -> QualityAssessment:
        """Basic quality assessment using OpenCV."""
        import cv2

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Sharpness via Laplacian variance
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

        # Illumination uniformity
        h, w = gray.shape
        grid = 5
        bh, bw = h // grid, w // grid
        means = []
        for r in range(grid):
            for c in range(grid):
                block = gray[r * bh : (r + 1) * bh, c * bw : (c + 1) * bw]
                means.append(float(np.mean(block)))

        if np.std(means) == 0:
            uniformity = 1.0
        else:
            cv_val = np.std(means) / np.mean(means)
            uniformity = max(0.0, 1.0 - cv_val)

        # FOV check
        _, binary = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)
        fov_ratio = np.sum(binary > 0) / binary.size
        fov_adequate = fov_ratio > 0.30

        # Artifacts
        artifacts = []
        bright_ratio = np.sum(gray > 250) / gray.size
        if bright_ratio > 0.02:
            artifacts.append("reflection")
        if laplacian_var < 50:
            artifacts.append("motion_blur")

        # Overall verdict
        if not fov_adequate:
            overall = "rejected"
        elif laplacian_var < 100 or uniformity < 0.5:
            overall = "poor"
        elif laplacian_var < 300 or uniformity < 0.7:
            overall = "acceptable"
        else:
            overall = "good"

        return QualityAssessment(
            overall_quality=overall,
            brisque_score=None,  # BRISQUE requires MATLAB
            sharpness_score=laplacian_var,
            illumination_uniformity=uniformity,
            field_of_view_adequate=fov_adequate,
            artifacts_detected=artifacts,
        )

    def _fallback_enhancement(
        self, img: np.ndarray, output_dir: Path, base_name: str
    ) -> Enhancement:
        """Basic enhancement using OpenCV CLAHE."""
        import cv2

        output_dir.mkdir(parents=True, exist_ok=True)

        # Green channel
        green = img[:, :, 1]
        green_path = str(output_dir / f"{base_name}_green.png")
        cv2.imwrite(green_path, green)

        # CLAHE on green channel
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced_green = clahe.apply(green)

        # CLAHE on L channel (LAB space)
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        lab[:, :, 0] = clahe.apply(lab[:, :, 0])
        enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

        enhanced_path = str(output_dir / f"{base_name}_enhanced.png")
        cv2.imwrite(enhanced_path, enhanced)

        return Enhancement(
            method="CLAHE_green_channel (Python fallback)",
            enhanced_image_path=enhanced_path,
            green_channel_path=green_path,
        )

    def _fallback_structure_analysis(
        self, img: np.ndarray, output_dir: Path, base_name: str
    ) -> StructureAnalysis:
        """Basic structure detection using OpenCV."""
        import cv2

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Optic disc: find brightest region
        red = img[:, :, 2]  # Red channel (OpenCV BGR)
        blurred = cv2.GaussianBlur(red, (51, 51), 0)
        _, max_val, _, max_loc = cv2.minMaxLoc(blurred)

        od = OpticDisc(
            detected=True,
            center_x=float(max_loc[0]),
            center_y=float(max_loc[1]),
            radius=float(min(h, w) * 0.08),
            confidence=0.5,  # Low confidence for fallback
        )

        # Macula: darkest region in central area
        green = img[:, :, 1]
        margin_h, margin_w = h // 5, w // 5
        search = cv2.GaussianBlur(
            green[margin_h : h - margin_h, margin_w : w - margin_w], (31, 31), 0
        )
        _, _, min_loc, _ = cv2.minMaxLoc(search)

        mac = Macula(
            detected=True,
            center_x=float(min_loc[0] + margin_w),
            center_y=float(min_loc[1] + margin_h),
            confidence=0.4,
        )

        # Vessels: simple morphological approach
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        green_eq = clahe.apply(green)
        green_inv = cv2.bitwise_not(green_eq)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        tophat = cv2.morphologyEx(green_inv, cv2.MORPH_TOPHAT, kernel)
        _, vessel_mask = cv2.threshold(tophat, 30, 255, cv2.THRESH_BINARY)

        mask_path = str(output_dir / f"{base_name}_vessels_mask.png")
        cv2.imwrite(mask_path, vessel_mask)

        vessel_density = float(np.sum(vessel_mask > 0) / vessel_mask.size)

        vasc = Vasculature(
            segmentation_mask_path=mask_path,
            vessel_density=min(vessel_density, 1.0),
            tortuosity_index=1.0,
        )

        return StructureAnalysis(optic_disc=od, macula=mac, vasculature=vasc)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Gracefully shut down MATLAB Engine if running."""
        if self._engine is not None:
            try:
                self._engine.quit()
                logger.info("MATLAB Engine shut down")
            except Exception as e:
                logger.error(f"Error shutting down MATLAB Engine: {e}")


# Singleton
matlab_bridge = MatlabBridge()
