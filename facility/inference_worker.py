"""
RetinaShield — Offline Inference Worker

Manages local MATLAB / MCR / Python-fallback inference for the facility node.

IMPORTANT:
    A cached web page alone does NOT provide offline MATLAB inference.
    This daemon must be running on the facility computer for local inference to
    work.  If it is not running, the facility operates in CAPTURE_ONLY mode and
    images are held in the encrypted queue until the daemon is available.

Inference pipeline:
    1. Decrypt image from SecureImageStore into an in-memory buffer.
    2. Write to a temporary directory (cleaned up unconditionally via finally).
    3. Call matlab_bridge.run_pipeline() or Python fallback.
    4. Store structured result back into the encrypted queue DB.

Temp-dir security:
    tempfile.TemporaryDirectory is used so the OS cleans up on process exit
    even if a crash occurs.  The directory path is never shared with the web
    server or frontend.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from facility.config import facility_config
from facility.queue import OfflineQueue, offline_queue
from facility.storage import secure_image_store

logger = logging.getLogger(__name__)


class InferenceWorker:
    """
    Local inference worker that processes items from the offline queue.

    Capability detection (in priority order):
        1. MATLAB full engine   — `matlabengine` importable and MATLAB licensed
        2. MATLAB MCR adapter   — MCR installed, bridged via subprocess
        3. Python fallback      — OpenCV/scikit-image IQA + stub classifier

    The detected capability is logged at startup and exposed via `capability`.
    """

    def __init__(self, queue: OfflineQueue | None = None) -> None:
        self._cfg = facility_config
        self._queue = queue or offline_queue
        self._semaphore = asyncio.Semaphore(
            self._cfg.max_concurrent_inference_jobs
        )
        self.capability: str = self._detect_capability()

    # ── Capability detection ──────────────────────────────────────────────────

    def _detect_capability(self) -> str:
        mode = self._cfg.matlab_mode.lower()

        if mode in ("full", "matlab"):
            try:
                import matlab.engine  # type: ignore[import]
                logger.info("InferenceWorker: MATLAB full engine available.")
                return "matlab_full"
            except ImportError:
                logger.warning(
                    "matlab_mode=%s but matlabengine not importable — "
                    "trying MCR adapter.",
                    mode,
                )

        if mode in ("full", "matlab", "mcr"):
            mcr_path = os.environ.get("MATLAB_MCR_PATH", "")
            if mcr_path and Path(mcr_path).exists():
                logger.info(
                    "InferenceWorker: MATLAB MCR detected at %s.", mcr_path
                )
                return "matlab_mcr"
            else:
                logger.warning(
                    "MCR adapter requested (MATLAB_MCR_PATH=%r) but path not found. "
                    "Falling back to Python pipeline.",
                    mcr_path,
                )

        logger.info(
            "InferenceWorker: Using Python fallback pipeline "
            "(OpenCV IQA + stub classifier). "
            "RESEARCH SCREENING ONLY — Not a validated clinical tool."
        )
        return "python_fallback"

    # ── Public interface ──────────────────────────────────────────────────────

    async def process_one(self, item: dict) -> bool:
        """
        Process a single queue item. Returns True on success, False on failure.

        The caller is responsible for marking the item 'processing' before calling
        and for handling the result (completed / failed) afterward.
        """
        async with self._semaphore:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._run_sync, item
            )

    # ── Synchronous processing (runs in executor thread) ──────────────────────

    def _run_sync(self, item: dict) -> bool:
        encounter_id = item["local_encounter_id"]
        rel_path = item.get("image_path")

        # Create a temp directory that is always cleaned up
        with tempfile.TemporaryDirectory(prefix="rs_infer_") as tmpdir:
            try:
                # --- Decrypt image to temp file ---
                if rel_path:
                    raw_bytes = secure_image_store.read_decrypt(rel_path)
                    tmp_image_path = os.path.join(tmpdir, "input.jpg")
                    with open(tmp_image_path, "wb") as f:
                        f.write(raw_bytes)
                    del raw_bytes  # remove from memory as soon as written
                else:
                    tmp_image_path = None

                output_dir = os.path.join(tmpdir, "output")
                os.makedirs(output_dir, exist_ok=True)

                # --- Run inference ---
                result = self._run_pipeline(tmp_image_path, output_dir, encounter_id)

                # --- Store result ---
                self._queue.update_status(
                    item["id"],
                    "completed",
                    analysis_result=result,
                )
                logger.info(
                    "Inference complete for %s via %s", encounter_id, self.capability
                )
                return True

            except Exception as exc:
                logger.error(
                    "Inference failed for %s: %s", encounter_id, exc
                )
                self._queue.update_status(
                    item["id"],
                    "failed",
                    error_message=str(exc),
                )
                return False
            finally:
                # tmpdir is cleaned up by context manager regardless of outcome
                pass

    def _run_pipeline(
        self, image_path: str | None, output_dir: str, encounter_id: str
    ) -> dict:
        """Dispatch to the appropriate inference backend."""
        if self.capability == "matlab_full":
            return self._run_matlab_full(image_path, output_dir)
        if self.capability == "matlab_mcr":
            return self._run_matlab_mcr(image_path, output_dir)
        return self._run_python_fallback(image_path, output_dir, encounter_id)

    def _run_matlab_full(self, image_path: str | None, output_dir: str) -> dict:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
        from app.services.matlab_bridge import matlab_bridge  # type: ignore
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                matlab_bridge.run_pipeline(image_path or "", output_dir)
            )
        finally:
            loop.close()

        return result.model_dump(mode="json") if hasattr(result, "model_dump") else result

    def _run_matlab_mcr(self, image_path: str | None, output_dir: str) -> dict:
        """Subprocess call to MCR-compiled binary."""
        import subprocess, json as _json

        mcr_bin = os.environ.get(
            "MATLAB_MCR_BINARY",
            "/opt/retinashield_mcr/run_retinashield.sh",
        )
        mcr_root = os.environ.get("MATLAB_MCR_PATH", "")

        cmd = [mcr_bin, mcr_root, image_path or "", output_dir]
        logger.info("MCR command: %s", " ".join(cmd))

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"MCR subprocess failed: {proc.stderr[:500]}")

        result_file = Path(output_dir) / "result.json"
        if not result_file.exists():
            raise FileNotFoundError("MCR did not produce result.json")

        return _json.loads(result_file.read_text())

    def _run_python_fallback(
        self, image_path: str | None, output_dir: str, encounter_id: str
    ) -> dict:
        """
        Python-only IQA + stub classifier.

        Produces real image quality metrics and an explicit stub grade so the
        result is clearly marked as an unvalidated fallback.
        """
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

        quality_result: dict = {}

        if image_path and Path(image_path).exists():
            try:
                from app.services.image_quality import assess_quality  # type: ignore
                qr = assess_quality(image_path)
                quality_result = (
                    qr.model_dump(mode="json")
                    if hasattr(qr, "model_dump")
                    else qr
                )
            except Exception as exc:
                logger.warning("IQA failed in fallback: %s", exc)
                quality_result = {"verdict": "unknown", "error": str(exc)}
        else:
            quality_result = {"verdict": "no_image", "ungradeable": True}

        return {
            "encounter_id": encounter_id,
            "pipeline_mode": "python_fallback",
            "disclaimer": (
                "PYTHON FALLBACK — MATLAB runtime not available. "
                "Grade is a placeholder stub (0). "
                "RESEARCH SCREENING ONLY — Not a validated clinical tool. "
                "Must be reviewed by a qualified ophthalmologist."
            ),
            "quality_assessment": quality_result,
            "severity_classification": {
                "predicted_dr_grade": None,
                "predicted_grade_label": "UNAVAILABLE — MATLAB required",
                "confidence": None,
                "class_probabilities": None,
                "model_trained": False,
            },
            "lesion_detection": None,
            "model_version": "python_fallback_v0",
        }


# Singleton
inference_worker = InferenceWorker()
