"""
RetinaShield — MATLAB Bridge Service & Inference Adapters

Provides two distinct inference adapters for MATLAB execution:
  1. MATLABEngineAdapter: Direct MATLAB Engine for Python (for development when licensed MATLAB is installed).
  2. MATLABRuntimeAdapter: Standalone compiled deployment adapter executing against the free MATLAB Runtime (MCR).
  3. MATLABUnavailableAdapter: Explicit failure adapter when neither is configured, strictly preventing fake predictions.

===============================================================================
COMPILATION, RUNTIME, & REDISTRIBUTION SPECIFICATIONS:
===============================================================================
- MATLAB source files (.m) CANNOT execute inside the MATLAB Runtime or in a web browser.
- Production deployment uses components compiled with MATLAB Compiler / MATLAB Compiler SDK (e.g., mcc).
  Example compilation:
    mcc -m -v matlab/src/analyzeFundus.m -d build/bin/ -a matlab/src/
- The resulting standalone executable runs alongside the compatible, royalty-free MATLAB Runtime (MCR).
- Redistribution of MATLAB Runtime installers is royalty-free under MathWorks redistribution terms.
- The Python adapter interacts with the standalone binary via subprocess with JSON I/O,
  ensuring full process isolation, resource bounding, and zero public command evaluation.
===============================================================================
"""

from __future__ import annotations

import abc
import hashlib
import json
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.config import settings
from app.schemas.analysis_result import (
    DISCLAIMER,
    AnalysisResult,
    Enhancement,
    FieldOfView,
    Macula,
    OpticDisc,
    QualityAssessment,
    ReferralRecommendation,
    SeverityClassification,
    StructureAnalysis,
    Vasculature,
)

logger = logging.getLogger(__name__)


class MATLABUnavailableError(RuntimeError):
    """Raised when MATLAB Engine or Runtime is requested but unavailable."""
    pass


class BaseMATLABAdapter(abc.ABC):
    """Abstract interface for MATLAB inference workers."""

    @abc.abstractmethod
    def run_analyze_fundus(
        self, image_path: str, output_dir: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute versioned analyzeFundus entry point on a fundus image."""
        pass

    @abc.abstractmethod
    def get_metadata(self) -> dict[str, Any]:
        """Return model hashes, preprocessing version, and component status."""
        pass

    def shutdown(self) -> None:
        """Release worker resources."""
        pass


class MATLABEngineAdapter(BaseMATLABAdapter):
    """
    Adapter using MATLAB Engine for Python.
    Used for development environments when licensed MATLAB is installed.
    """

    def __init__(self, matlab_src_dir: str | None = None, model_path: str | None = None) -> None:
        self.matlab_src_dir = matlab_src_dir or str(
            Path(__file__).resolve().parent.parent.parent.parent / "matlab" / "src"
        )
        self.model_path = model_path or str(
            Path(__file__).resolve().parent.parent.parent.parent / "matlab" / "models" / "efficientnet_b0_dr.mat"
        )
        self._engine = None
        self._model_hash = self._compute_model_hash(self.model_path)
        self._is_ready = False
        self._init_engine()

    @staticmethod
    def _compute_model_hash(path: str) -> str:
        p = Path(path)
        if not p.is_file():
            return "none"
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def _init_engine(self) -> None:
        try:
            import matlab.engine  # type: ignore

            logger.info("Starting MATLAB Engine for Python...")
            self._engine = matlab.engine.start_matlab()
            if os.path.isdir(self.matlab_src_dir):
                self._engine.addpath(self.matlab_src_dir, nargout=0)
            self._is_ready = True
            logger.info("MATLAB Engine initialized successfully.")
        except ImportError:
            logger.warning(
                "matlab.engine Python package is not installed. "
                "For development, install from: $MATLAB_ROOT/extern/engines/python"
            )
            self._is_ready = False
        except Exception as e:
            logger.error(f"Failed to start MATLAB Engine: {e}")
            self._is_ready = False

    def get_metadata(self) -> dict[str, Any]:
        return {
            "adapter_type": "engine",
            "is_ready": self._is_ready,
            "entry_point_version": "1.0.0",
            "preprocessing_version": "1.0",
            "model_hashes": {
                "classifier": self._model_hash,
                "lesion_detector": "morphology_v1",
            },
            "matlab_src_dir": self.matlab_src_dir,
        }

    def run_analyze_fundus(
        self, image_path: str, output_dir: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self._is_ready or self._engine is None:
            raise MATLABUnavailableError(
                "MATLAB Engine is not available or failed to initialize. "
                "Missing dependencies must produce explicit failures, never substitute predictions."
            )

        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        os.makedirs(output_dir, exist_ok=True)
        opts = options or {}
        if "model_path" not in opts and os.path.isfile(self.model_path):
            opts["model_path"] = self.model_path

        opts_json = json.dumps(opts)

        # Call versioned analyzeFundus via engine safely without eval()
        try:
            # We pass arguments as string/char vectors into analyzeFundus
            res_struct = self._engine.analyzeFundus(
                str(image_path), str(output_dir), opts_json, nargout=1
            )
            # Try loading written JSON first for cleanest fidelity
            result_json_file = Path(output_dir) / "analysis_result.json"
            if result_json_file.is_file():
                with open(result_json_file, "r") as f:
                    return json.load(f)
            return self._matlab_struct_to_dict(res_struct)
        except Exception as e:
            logger.error(f"MATLAB Engine execution error: {e}")
            raise RuntimeError(f"MATLAB Engine execution failed: {e}") from e

    def _matlab_struct_to_dict(self, struct: Any) -> dict:
        if hasattr(struct, "_fieldnames"):
            return {
                field: self._matlab_struct_to_dict(getattr(struct, field))
                for field in struct._fieldnames
            }
        elif isinstance(struct, (list, tuple)):
            return [self._matlab_struct_to_dict(item) for item in struct]
        else:
            return struct

    def shutdown(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
                logger.info("MATLAB Engine terminated.")
            except Exception as e:
                logger.warning(f"Error terminating MATLAB Engine: {e}")
            finally:
                self._engine = None
                self._is_ready = False


class MATLABRuntimeAdapter(BaseMATLABAdapter):
    """
    Adapter executing standalone compiled MATLAB components against MATLAB Runtime (MCR).
    Used in production deployment where full MATLAB license is not installed.
    """

    def __init__(
        self,
        executable_path: str | None = None,
        mcr_root: str | None = None,
        model_path: str | None = None,
    ) -> None:
        self.executable_path = executable_path or settings.matlab_compiled_package
        self.mcr_root = mcr_root or settings.mcr_root
        self.model_path = model_path or settings.efficientnet_weights_path
        self._model_hash = MATLABEngineAdapter._compute_model_hash(self.model_path) if self.model_path else "none"

    def get_metadata(self) -> dict[str, Any]:
        has_exec = bool(self.executable_path and os.path.isfile(self.executable_path))
        return {
            "adapter_type": "runtime",
            "is_ready": has_exec,
            "entry_point_version": "1.0.0",
            "preprocessing_version": "1.0",
            "model_hashes": {
                "classifier": self._model_hash,
                "lesion_detector": "morphology_v1",
            },
            "executable_path": self.executable_path,
            "mcr_root": self.mcr_root,
        }

    def run_analyze_fundus(
        self, image_path: str, output_dir: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.executable_path or not os.path.isfile(self.executable_path):
            raise MATLABUnavailableError(
                f"Compiled MATLAB executable not found at '{self.executable_path}'. "
                "Production deployment requires compiled MATLAB component + MATLAB Runtime. "
                "Do not assume raw MATLAB source files execute in Runtime or browser."
            )

        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        os.makedirs(output_dir, exist_ok=True)
        opts_file = Path(output_dir) / "options.json"
        opts = options or {}
        with open(opts_file, "w") as f:
            json.dump(opts, f)

        # Set library paths for MATLAB Runtime
        env = os.environ.copy()
        if self.mcr_root and os.path.isdir(self.mcr_root):
            # Typical MCR library paths depending on OS
            mcr_lib = os.path.join(self.mcr_root, "runtime", "glnxa64")
            if not os.path.exists(mcr_lib):
                mcr_lib = os.path.join(self.mcr_root, "sys", "os", "glnxa64")
            cur_ld = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = f"{mcr_lib}:{cur_ld}" if cur_ld else mcr_lib
            env["DYLD_LIBRARY_PATH"] = env.get("LD_LIBRARY_PATH", "")

        # Execute standalone binary with bounded execution and parameter isolation
        cmd = [self.executable_path, str(image_path), str(output_dir), str(opts_file)]
        logger.info(f"Executing compiled MATLAB binary: {self.executable_path}")

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=300,
                env=env,
            )
            logger.debug(f"MATLAB Runtime stdout: {res.stdout}")
        except subprocess.TimeoutExpired as te:
            logger.error(f"MATLAB Runtime process timed out: {te}")
            raise TimeoutError(f"MATLAB analysis timed out after 300 seconds: {te}") from te
        except subprocess.CalledProcessError as cpe:
            logger.error(f"MATLAB Runtime failed with code {cpe.returncode}: {cpe.stderr}")
            raise RuntimeError(f"MATLAB Runtime execution failed: {cpe.stderr}") from cpe

        # Parse generated output
        result_json_path = Path(output_dir) / "analysis_result.json"
        if not result_json_path.is_file():
            raise FileNotFoundError(
                f"MATLAB Runtime completed but no analysis_result.json was found in {output_dir}."
            )

        with open(result_json_path, "r") as f:
            return json.load(f)


class MATLABUnavailableAdapter(BaseMATLABAdapter):
    """
    Explicit failure adapter when neither Engine nor Runtime is available.
    Ensures missing dependencies produce clear errors and NEVER invent predictions.
    """

    def __init__(self, reason: str = "MATLAB not configured") -> None:
        self.reason = reason

    def get_metadata(self) -> dict[str, Any]:
        return {
            "adapter_type": "unavailable",
            "is_ready": False,
            "entry_point_version": "1.0.0",
            "reason": self.reason,
        }

    def run_analyze_fundus(
        self, image_path: str, output_dir: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        raise MATLABUnavailableError(
            f"MATLAB analysis is unavailable ({self.reason}). "
            "RetinaShield requires licensed MATLAB Engine (dev) or compiled MATLAB Runtime (prod). "
            "Missing dependencies produce explicit failures; predictions are never substituted."
        )


def create_matlab_adapter(mode: str | None = None) -> BaseMATLABAdapter:
    """Factory creating appropriate adapter according to system settings."""
    active_mode = (mode or settings.matlab_mode).lower()

    if active_mode == "engine":
        adapter = MATLABEngineAdapter()
        if adapter.get_metadata()["is_ready"]:
            return adapter
        logger.warning("MATLABEngineAdapter requested but not ready; falling back to unavailable adapter.")
        return MATLABUnavailableAdapter(reason="MATLAB Engine not installed or failed to start")

    elif active_mode == "mcr":
        adapter = MATLABRuntimeAdapter()
        if adapter.get_metadata()["is_ready"]:
            return adapter
        logger.warning("MATLABRuntimeAdapter requested but executable missing; falling back to unavailable adapter.")
        return MATLABUnavailableAdapter(reason="Compiled MATLAB package executable not found")

    else:
        return MATLABUnavailableAdapter(reason="MATLAB mode is set to fallback or unconfigured")


class MatlabBridge:
    """
    Bridge orchestrating MATLAB analysis adapters with Python fallback capabilities.
    Maintains backwards compatibility with existing test suites and services.
    """

    def __init__(self) -> None:
        self.mode = settings.matlab_mode
        self.adapter = create_matlab_adapter(self.mode)
        logger.info(f"MATLAB Bridge initialized in '{self.mode}' mode with adapter: {type(self.adapter).__name__}")

    def get_metadata(self) -> dict[str, Any]:
        return self.adapter.get_metadata()

    async def run_pipeline(
        self, image_path: str, output_dir: str
    ) -> AnalysisResult:
        """Run full analysis pipeline on fundus image."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        if self.mode in ("engine", "mcr"):
            try:
                res_dict = self.adapter.run_analyze_fundus(image_path, output_dir)
                return AnalysisResult(**res_dict)
            except Exception as e:
                logger.error(f"MATLAB pipeline failed: {e}")
                if self.mode != "fallback":
                    raise
                return await self._run_python_fallback(image_path, output_dir)
        else:
            return await self._run_python_fallback(image_path, output_dir)

    async def _run_python_fallback(
        self, image_path: str, output_dir: str
    ) -> AnalysisResult:
        """Classical Python fallback for testing and development without DL inference."""
        logger.info(f"[Python Fallback] Processing: {image_path}")
        start_time = datetime.now(timezone.utc)

        try:
            import cv2
        except ImportError:
            logger.error("OpenCV not installed.")
            raise

        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")

        output_path = Path(output_dir)
        base_name = Path(image_path).stem

        quality = self._fallback_quality_assessment(img)
        enhancement = self._fallback_enhancement(img, output_path, base_name)
        structures = self._fallback_structure_analysis(img, output_path, base_name)

        classification = SeverityClassification(
            model="EfficientNet-B0",
            model_trained=False,
            predicted_grade=-1,
            grade_label="UNAVAILABLE — Requires MATLAB (Python fallback mode active)",
            confidence=0.0,
            class_probabilities=[0.2, 0.2, 0.2, 0.2, 0.2],
        )

        referral = ReferralRecommendation(
            urgency="none",
            reason="Classification unavailable in Python fallback mode. MATLAB required.",
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
        import cv2

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        h, w = gray.shape
        grid = 5
        bh, bw = h // grid, w // grid
        means = [
            float(np.mean(gray[r * bh : (r + 1) * bh, c * bw : (c + 1) * bw]))
            for r in range(grid)
            for c in range(grid)
        ]

        uniformity = 1.0 if np.std(means) == 0 else max(0.0, 1.0 - (float(np.std(means)) / float(np.mean(means))))

        _, binary = cv2.threshold(gray, 30, 255, cv2.THRESH_BINARY)
        fov_ratio = float(np.sum(binary > 0)) / float(binary.size)
        fov_adequate = fov_ratio > 0.30

        artifacts = []
        bright_ratio = float(np.sum(gray > 250)) / float(gray.size)
        if bright_ratio > 0.02:
            artifacts.append("reflection")
        if laplacian_var < 50:
            artifacts.append("motion_blur")

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
            brisque_score=None,
            sharpness_score=laplacian_var,
            illumination_uniformity=uniformity,
            field_of_view_adequate=fov_adequate,
            artifacts_detected=artifacts,
        )

    def _fallback_enhancement(
        self, img: np.ndarray, output_dir: Path, base_name: str
    ) -> Enhancement:
        import cv2

        output_dir.mkdir(parents=True, exist_ok=True)
        green = img[:, :, 1]
        green_path = str(output_dir / f"{base_name}_green.png")
        cv2.imwrite(green_path, green)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
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
        import cv2

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        red = img[:, :, 2]
        green = img[:, :, 1]
        blue = img[:, :, 0]

        # 1. FOV Segmentation
        _, fov_thresh = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY)
        kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        fov_mask = cv2.morphologyEx(fov_thresh, cv2.MORPH_CLOSE, kernel_close)

        contours, _ = cv2.findContours(fov_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        fov_binary = np.zeros((h, w), dtype=np.uint8)
        fov_center_x, fov_center_y, fov_radius = w / 2.0, h / 2.0, min(h, w) / 2.0
        fov_area = float(np.sum(fov_mask > 0))

        if contours:
            largest_c = max(contours, key=cv2.contourArea)
            cv2.drawContours(fov_binary, [largest_c], -1, 255, thickness=-1)
            (fx, fy), fr = cv2.minEnclosingCircle(largest_c)
            fov_center_x, fov_center_y, fov_radius = float(fx), float(fy), float(fr)
            fov_area = float(cv2.contourArea(largest_c))
        else:
            fov_binary = fov_mask

        fov_ratio = fov_area / (h * w)
        fov_reliable = 0.15 <= fov_ratio <= 0.98

        output_dir.mkdir(parents=True, exist_ok=True)
        fov_mask_path = str(output_dir / f"{base_name}_fov_mask.png")
        cv2.imwrite(fov_mask_path, fov_binary)

        fov_res = FieldOfView(
            mask_path=fov_mask_path,
            bounding_box=[0.0, 0.0, float(w), float(h)],
            center_x=fov_center_x,
            center_y=fov_center_y,
            radius=fov_radius,
            area_pixels=int(fov_area),
            area_ratio=min(1.0, fov_ratio),
            is_reliable=fov_reliable,
            failure_reason="" if fov_reliable else "DEGENERATE_FOV_AREA",
            algorithm_version="0.2.0-fallback",
        )

        safe_margin = max(10, int(min(h, w) * 0.04))
        safe_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (safe_margin, safe_margin))
        safe_fov = cv2.erode(fov_binary, safe_kernel)

        # 2. Vasculature
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        green_clahe = clahe.apply(green)
        green_inv = cv2.bitwise_not(green_clahe)

        tophat_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        vessel_resp = cv2.morphologyEx(green_inv, cv2.MORPH_TOPHAT, tophat_kernel)
        _, vessel_mask = cv2.threshold(vessel_resp, 28, 255, cv2.THRESH_BINARY)
        vessel_mask = cv2.bitwise_and(vessel_mask, safe_fov)

        vessel_path = str(output_dir / f"{base_name}_vessels_mask.png")
        cv2.imwrite(vessel_path, vessel_mask)

        safe_fov_px = float(np.sum(safe_fov > 0))
        vessel_px = float(np.sum(vessel_mask > 0))
        vessel_density = (vessel_px / safe_fov_px) if safe_fov_px > 0 else 0.0
        vessel_reliable = 0.02 <= vessel_density <= 0.25

        vasc_res = Vasculature(
            segmentation_mask_path=vessel_path,
            vessel_density=float(min(1.0, vessel_density)),
            tortuosity_index=1.05,
            caliber_proxy=1.2,
            confidence=0.80 if vessel_reliable else 0.35,
            is_reliable=vessel_reliable,
            failure_reason="" if vessel_reliable else "ABNORMAL_VESSEL_DENSITY",
            algorithm_version="0.2.0-fallback",
        )

        # 3. Optic Disc
        expected_od_r = min(h, w) * 0.075
        red_opened = cv2.morphologyEx(
            red, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        )
        red_blur = cv2.GaussianBlur(red_opened, (25, 25), 0).astype(np.float32)
        vessel_density_map = cv2.blur(
            (vessel_mask > 0).astype(np.float32), (int(expected_od_r), int(expected_od_r))
        )
        glare = ((red > 245) & (green > 245) & (blue > 245)).astype(np.float32)

        saliency = (0.50 * red_blur) + (0.45 * (vessel_density_map * 255)) - (0.40 * (glare * 255))
        saliency[safe_fov == 0] = 0

        _, max_sal, _, max_loc = cv2.minMaxLoc(saliency)
        od_detected = False
        od_cx, od_cy, od_r = None, None, None
        od_conf = 0.0
        od_reason = ""

        if max_sal > 40.0 and safe_fov[max_loc[1], max_loc[0]] > 0:
            od_cx, od_cy = float(max_loc[0]), float(max_loc[1])
            od_r = float(expected_od_r)
            od_detected = True
            od_conf = min(1.0, max_sal / 200.0)
        else:
            od_reason = "NO_RELIABLE_DISC_CANDIDATE_OR_OUTSIDE_FOV"

        od_mask_path = ""
        if od_detected:
            od_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.circle(od_mask, (int(od_cx), int(od_cy)), int(od_r), 255, -1)
            od_mask = cv2.bitwise_and(od_mask, fov_binary)
            od_mask_path = str(output_dir / f"{base_name}_optic_disc_mask.png")
            cv2.imwrite(od_mask_path, od_mask)

        od_res = OpticDisc(
            detected=od_detected,
            center_x=od_cx,
            center_y=od_cy,
            radius=od_r,
            mask_path=od_mask_path if od_detected else None,
            confidence=od_conf,
            is_reliable=od_detected and od_conf >= 0.50,
            failure_reason=od_reason,
            algorithm_version="0.2.0-fallback",
        )

        # 4. Fovea & Macula
        inferred_lat = "unknown"
        fovea_detected = False
        fovea_cx, fovea_cy, fovea_r = None, None, None
        fovea_conf = 0.0
        fovea_reason = ""

        disc_diam = (od_r * 2.0) if (od_detected and od_r) else (min(h, w) * 0.14)
        expected_faz_r = disc_diam * 0.25

        if od_detected and od_cx is not None:
            if od_cx < (fov_center_x - 0.04 * w):
                inferred_lat = "OD"
                direction_x = 1.0
            elif od_cx > (fov_center_x + 0.04 * w):
                inferred_lat = "OS"
                direction_x = -1.0
            else:
                inferred_lat = "unknown"
                direction_x = 1.0

            expected_dist = disc_diam * 2.6
            est_fx = od_cx + (direction_x * expected_dist)
            est_fy = od_cy + (disc_diam * 0.25)

            if (
                0 <= int(est_fy) < h
                and 0 <= int(est_fx) < w
                and safe_fov[int(est_fy), int(est_fx)] > 0
            ):
                win_r = int(disc_diam * 0.5)
                y1, y2 = max(0, int(est_fy) - win_r), min(h, int(est_fy) + win_r)
                x1, x2 = max(0, int(est_fx) - win_r), min(w, int(est_fx) + win_r)
                sub_green = green_clahe[y1:y2, x1:x2]
                _, _, min_loc, _ = cv2.minMaxLoc(sub_green)

                fovea_cx = float(x1 + min_loc[0])
                fovea_cy = float(y1 + min_loc[1])
                fovea_r = float(expected_faz_r)
                fovea_detected = True
                fovea_conf = 0.75
            else:
                fovea_reason = "FOVEA_OUTSIDE_FOV"
        else:
            mh, mw = h // 4, w // 4
            central = green_clahe[mh : h - mh, mw : w - mw]
            _, _, min_loc, _ = cv2.minMaxLoc(central)
            fovea_cx = float(mw + min_loc[0])
            fovea_cy = float(mh + min_loc[1])
            fovea_r = float(expected_faz_r)
            fovea_detected = True
            fovea_conf = 0.50
            fovea_reason = "LOCALIZED_WITHOUT_OD_REFERENCE"

        macula_res = Macula(
            detected=fovea_detected,
            center_x=fovea_cx,
            center_y=fovea_cy,
            radius=fovea_r,
            confidence=fovea_conf,
            is_reliable=fovea_detected and fovea_conf >= 0.55,
            failure_reason=fovea_reason,
            inferred_laterality=inferred_lat,
            algorithm_version="0.2.0-fallback",
        )

        return StructureAnalysis(
            is_experimental=True,
            field_of_view=fov_res,
            optic_disc=od_res,
            macula=macula_res,
            fovea=macula_res,
            vasculature=vasc_res,
        )

    def shutdown(self) -> None:
        """Gracefully release adapter resources."""
        self.adapter.shutdown()


# Global singleton instance
matlab_bridge = MatlabBridge()
