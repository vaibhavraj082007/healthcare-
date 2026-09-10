"""
RetinaShield — Persisted Background Job Queue Service

Orchestrates asynchronous inference execution with:
  - Bounded concurrency (asyncio.Semaphore)
  - Persisted database state tracking (queued, running, completed, failed, cancelled)
  - Strict timeouts per job
  - Idempotency key deduplication
  - Safe retry mechanism with exponential backoff
  - Mid-flight job cancellation
  - Sanitized, isolated file path execution (zero eval / injection exposure)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import async_session_factory
from app.models.clinical import ModelOutput, QualityResult
from app.models.job import AnalysisJob
from app.models.screening import Screening, ScreeningImage
from app.services.image_store import image_store
from app.services.matlab_bridge import MATLABUnavailableError, matlab_bridge
from app.services.yolo_service import yolo_service

logger = logging.getLogger(__name__)


class JobQueueService:
    """Manages persisted background jobs for fundus analysis."""

    def __init__(self, max_concurrency: int = 2) -> None:
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._active_tasks: dict[uuid.UUID, asyncio.Task] = {}
        self._is_running = True

    def generate_idempotency_key(
        self, screening_id: uuid.UUID, image_id: uuid.UUID | None, params: dict[str, Any] | None
    ) -> str:
        """Create a deterministic hash from screening ID, image ID, and parameters."""
        raw = f"{screening_id}:{image_id or 'none'}:{json.dumps(params or {}, sort_keys=True)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def submit_job(
        self,
        screening_id: uuid.UUID,
        image_id: uuid.UUID | None = None,
        facility_id: str | None = None,
        run_matlab: bool = True,
        run_yolo: bool = True,
        timeout_seconds: int = 300,
        idempotency_key: str | None = None,
        priority: int = 0,
    ) -> AnalysisJob:
        """
        Enqueue a new analysis job or return existing matching job (idempotent).
        """
        params = {"run_matlab": run_matlab, "run_yolo": run_yolo}
        key = idempotency_key or self.generate_idempotency_key(screening_id, image_id, params)

        async with async_session_factory() as session:
            # Check for existing job with same idempotency key
            stmt = select(AnalysisJob).where(AnalysisJob.idempotency_key == key)
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if existing:
                if existing.status in ("queued", "running"):
                    logger.info(f"Job {existing.id} already active for idempotency key '{key}'. Returning existing.")
                    return existing
                elif existing.status == "completed":
                    logger.info(f"Job {existing.id} already completed for key '{key}'. Returning existing.")
                    return existing
                # If failed or cancelled, we allow re-submission by generating a fresh key or resetting
                logger.info(f"Previous job {existing.id} had status '{existing.status}'. Creating new job.")
                key = f"{key}_{int(datetime.now(timezone.utc).timestamp())}"

            job = AnalysisJob(
                id=uuid.uuid4(),
                screening_id=screening_id,
                image_id=image_id,
                facility_id=facility_id,
                idempotency_key=key,
                status="queued",
                priority=priority,
                retry_count=0,
                max_retries=2,
                timeout_seconds=timeout_seconds,
                parameters=params,
                created_at=datetime.now(timezone.utc),
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)

        # Dispatch background worker task
        task = asyncio.create_task(self._process_job(job.id))
        self._active_tasks[job.id] = task
        task.add_done_callback(lambda t: self._active_tasks.pop(job.id, None))

        return job

    async def get_job(self, job_id: uuid.UUID) -> AnalysisJob | None:
        """Fetch job record from database."""
        async with async_session_factory() as session:
            stmt = select(AnalysisJob).where(AnalysisJob.id == job_id)
            return (await session.execute(stmt)).scalar_one_or_none()

    async def cancel_job(self, job_id: uuid.UUID) -> bool:
        """Cancel a queued or running job."""
        task = self._active_tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            logger.info(f"Cancelled running task for job {job_id}")

        async with async_session_factory() as session:
            stmt = select(AnalysisJob).where(AnalysisJob.id == job_id)
            job = (await session.execute(stmt)).scalar_one_or_none()
            if not job:
                return False

            if job.status in ("queued", "running"):
                job.status = "cancelled"
                job.completed_at = datetime.now(timezone.utc)
                job.error_message = "Analysis job cancelled by user request."
                await session.commit()
                return True
            return False

    async def _process_job(self, job_id: uuid.UUID) -> None:
        """Worker execution loop for a specific job."""
        async with self._semaphore:
            # Re-fetch job to ensure it wasn't cancelled while queued
            async with async_session_factory() as session:
                stmt = select(AnalysisJob).where(AnalysisJob.id == job_id)
                job = (await session.execute(stmt)).scalar_one_or_none()
                if not job or job.status == "cancelled":
                    return

                job.status = "running"
                job.started_at = datetime.now(timezone.utc)
                job.worker_id = f"worker-{os.getpid()}"
                await session.commit()

            start_t = datetime.now(timezone.utc)
            try:
                # Enforce execution timeout
                await asyncio.wait_for(
                    self._execute_analysis_pipeline(job_id),
                    timeout=job.timeout_seconds,
                )

            except asyncio.CancelledError:
                logger.warning(f"Job {job_id} cancelled during execution.")
                async with async_session_factory() as session:
                    stmt = select(AnalysisJob).where(AnalysisJob.id == job_id)
                    cur_job = (await session.execute(stmt)).scalar_one_or_none()
                    if cur_job:
                        cur_job.status = "cancelled"
                        cur_job.completed_at = datetime.now(timezone.utc)
                        cur_job.error_message = "Job execution cancelled."
                        await session.commit()
                raise

            except asyncio.TimeoutError:
                logger.error(f"Job {job_id} timed out after {job.timeout_seconds}s.")
                await self._handle_job_failure(
                    job_id,
                    error_msg=f"Job timed out after {job.timeout_seconds} seconds.",
                    is_timeout=True,
                )

            except Exception as exc:
                logger.error(f"Job {job_id} failed with error: {exc}", exc_info=True)
                await self._handle_job_failure(
                    job_id,
                    error_msg=str(exc),
                    error_trace=traceback.format_exc(),
                    is_timeout=False,
                )

    async def _execute_analysis_pipeline(self, job_id: uuid.UUID) -> None:
        """Core analysis pipeline step."""
        async with async_session_factory() as session:
            stmt = select(AnalysisJob).where(AnalysisJob.id == job_id)
            job = (await session.execute(stmt)).scalar_one_or_none()
            if not job:
                return

            screening_id = job.screening_id
            image_id = job.image_id
            params = job.parameters or {}

            # Fetch screening and target image
            sc_stmt = select(Screening).where(Screening.id == screening_id)
            screening = (await session.execute(sc_stmt)).scalar_one_or_none()
            if not screening:
                raise ValueError(f"Screening not found: {screening_id}")

            if image_id:
                img_stmt = select(ScreeningImage).where(ScreeningImage.id == image_id)
                target_image = (await session.execute(img_stmt)).scalar_one_or_none()
            else:
                img_stmt = select(ScreeningImage).where(ScreeningImage.screening_id == screening_id)
                target_image = (await session.execute(img_stmt)).scalars().first()

            if not target_image:
                raise FileNotFoundError(f"No fundus image found for screening {screening_id}")

            # Verify image path inside private image storage
            image_path = await image_store.get_image_path(target_image.stored_filename)
            if not os.path.isfile(image_path):
                raise FileNotFoundError(f"Image file does not exist on disk: {image_path}")

            # Prepare isolated output directory
            output_dir = str(Path(settings.image_storage_path) / "analysis" / str(screening_id))
            os.makedirs(output_dir, exist_ok=True)

            t0 = datetime.now(timezone.utc)
            result_dict: dict[str, Any] = {}
            timings: dict[str, Any] = {}

            # --- Stage 1: MATLAB analysis worker ---
            if params.get("run_matlab", True):
                logger.info(f"Job {job_id}: Calling MATLAB worker for screening {screening_id}")
                t_matlab = datetime.now(timezone.utc)

                if matlab_bridge.mode in ("engine", "mcr"):
                    result_dict = matlab_bridge.adapter.run_analyze_fundus(image_path, output_dir)
                else:
                    # Python fallback when explicitly in fallback mode
                    fb_res = await matlab_bridge.run_pipeline(image_path, output_dir)
                    result_dict = fb_res.model_dump(mode="json")

                timings["matlab_ms"] = round((datetime.now(timezone.utc) - t_matlab).total_seconds() * 1000)

            # --- Stage 2: YOLOv8 Lesion Detection ---
            if params.get("run_yolo", True):
                logger.info(f"Job {job_id}: Calling YOLOv8 lesion detector")
                t_yolo = datetime.now(timezone.utc)
                lesions = await yolo_service.detect_lesions(image_path)
                result_dict["lesion_detection"] = lesions.model_dump(mode="json")
                timings["yolo_ms"] = round((datetime.now(timezone.utc) - t_yolo).total_seconds() * 1000)

            timings["total_ms"] = round((datetime.now(timezone.utc) - t0).total_seconds() * 1000)

            # Record model metadata and provenance
            adapter_meta = matlab_bridge.get_metadata()
            model_metadata = {
                "adapter": adapter_meta,
                "pipeline_version": settings.pipeline_version,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }

            # Update job record to COMPLETED
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.result_json = result_dict
            job.timings = timings
            job.model_metadata = model_metadata

            # Also update Screening record
            screening.status = "completed"
            screening.analyzed_at = datetime.now(timezone.utc)
            screening.analysis_result = result_dict

            # Extract quality verdict and predictions if present
            if "quality_assessment" in result_dict and isinstance(result_dict["quality_assessment"], dict):
                qa = result_dict["quality_assessment"]
                screening.quality_verdict = qa.get("overall_quality") or qa.get("status")

            if "severity_classification" in result_dict and isinstance(result_dict["severity_classification"], dict):
                sc = result_dict["severity_classification"]
                screening.dr_grade = sc.get("predicted_grade")
                screening.dr_grade_label = sc.get("grade_label")
                screening.dr_confidence = sc.get("confidence")
                screening.model_trained = sc.get("model_trained", False)

            if "referral_recommendation" in result_dict and isinstance(result_dict["referral_recommendation"], dict):
                rr = result_dict["referral_recommendation"]
                screening.referral_urgency = rr.get("urgency")

            await session.commit()
            logger.info(f"Job {job_id} successfully completed in {timings.get('total_ms')}ms.")

    async def _handle_job_failure(
        self,
        job_id: uuid.UUID,
        error_msg: str,
        error_trace: str | None = None,
        is_timeout: bool = False,
    ) -> None:
        """Handle retry scheduling or terminal failure state."""
        async with async_session_factory() as session:
            stmt = select(AnalysisJob).where(AnalysisJob.id == job_id)
            job = (await session.execute(stmt)).scalar_one_or_none()
            if not job:
                return

            if job.retry_count < job.max_retries and not isinstance(error_msg, MATLABUnavailableError):
                # Schedule safe retry with exponential backoff
                job.retry_count += 1
                job.status = "queued"
                job.error_message = f"Retry {job.retry_count}/{job.max_retries} due to: {error_msg}"
                await session.commit()

                delay = 2 ** job.retry_count
                logger.warning(f"Scheduling retry {job.retry_count} for job {job_id} in {delay}s.")
                await asyncio.sleep(delay)

                task = asyncio.create_task(self._process_job(job.id))
                self._active_tasks[job.id] = task
                task.add_done_callback(lambda t: self._active_tasks.pop(job.id, None))
            else:
                # Terminal failure
                job.status = "failed"
                job.completed_at = datetime.now(timezone.utc)
                job.error_message = error_msg
                job.error_trace = error_trace

                # Mark screening failed as well
                sc_stmt = select(Screening).where(Screening.id == job.screening_id)
                screening = (await session.execute(sc_stmt)).scalar_one_or_none()
                if screening:
                    screening.status = "failed"

                await session.commit()
                logger.error(f"Job {job_id} marked as failed: {error_msg}")

    async def shutdown(self) -> None:
        """Cancel and await all in-flight tasks during server shutdown."""
        self._is_running = False
        tasks = list(self._active_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("JobQueueService shutdown complete.")


# Global job queue singleton
job_queue = JobQueueService(max_concurrency=2)
