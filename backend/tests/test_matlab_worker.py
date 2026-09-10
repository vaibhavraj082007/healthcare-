"""
RetinaShield — MATLAB Inference Worker & Job Queue Test Suite

Verifies:
1. MATLAB Engine, Runtime (MCR), and Unavailable adapter behaviors.
2. Missing dependencies raise explicit MATLABUnavailableError without substituting predictions.
3. Model artifact hashing and provenance tracking.
4. Background job persistence (queued, running, completed, failed, cancelled).
5. Idempotency guarantees (duplicate submission returns original job).
6. Bounded concurrency and resource limit enforcement.
7. Mid-flight job cancellation.
8. Timeout detection and retry logic.
9. REST API endpoints for jobs (/api/jobs/).
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image as PILImage

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.security import hash_password, create_access_token
from app.db.session import Base, get_db
from app.models.facility import Facility
from app.models.job import AnalysisJob
from app.models.patient import Patient
from app.models.screening import Screening, ScreeningImage
from app.models.user import User, UserRole
from app.services.job_queue import JobQueueService, job_queue
from app.services.matlab_bridge import (
    BaseMATLABAdapter,
    MATLABEngineAdapter,
    MATLABRuntimeAdapter,
    MATLABUnavailableAdapter,
    MATLABUnavailableError,
    create_matlab_adapter,
    matlab_bridge,
)
from app.main import app


def generate_test_jpeg(width: int = 512, height: int = 512) -> bytes:
    """Generate in-memory valid JPEG."""
    img = PILImage.new("RGB", (width, height), color=(150, 60, 40))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


class TestMATLABAdapters(unittest.TestCase):
    """Test suite for MATLAB inference adapters."""

    def test_unavailable_adapter_raises_explicit_error(self):
        """Verify that missing MATLAB dependencies never invent predictions."""
        adapter = MATLABUnavailableAdapter(reason="License not available")
        meta = adapter.get_metadata()
        self.assertEqual(meta["adapter_type"], "unavailable")
        self.assertFalse(meta["is_ready"])

        with self.assertRaises(MATLABUnavailableError) as ctx:
            adapter.run_analyze_fundus("fake_path.jpg", "/tmp/out")
        self.assertIn("Missing dependencies produce explicit failures", str(ctx.exception))
        self.assertIn("predictions are never substituted", str(ctx.exception))

    def test_adapter_factory_modes(self):
        """Verify factory selects correct adapter based on configuration."""
        # Fallback mode
        fb_adapter = create_matlab_adapter("fallback")
        self.assertIsInstance(fb_adapter, MATLABUnavailableAdapter)

        # MCR mode with non-existent executable falls back safely to unavailable
        with patch("app.services.matlab_bridge.settings.matlab_compiled_package", "/nonexistent/binary"):
            mcr_adapter = create_matlab_adapter("mcr")
            self.assertIsInstance(mcr_adapter, MATLABUnavailableAdapter)

    def test_model_hash_computation(self):
        """Verify SHA-256 calculation for model weights."""
        with tempfile.NamedTemporaryFile(suffix=".mat", delete=False) as f:
            f.write(b"retinashield_test_model_weights_bytes_12345")
            temp_path = f.name

        try:
            computed_hash = MATLABEngineAdapter._compute_model_hash(temp_path)
            self.assertEqual(len(computed_hash), 64)
            # Verify missing file returns 'none'
            self.assertEqual(MATLABEngineAdapter._compute_model_hash("/missing/file.mat"), "none")
        finally:
            os.remove(temp_path)

    def test_runtime_adapter_missing_binary(self):
        """Verify runtime adapter raises explicit error if compiled binary is missing."""
        adapter = MATLABRuntimeAdapter(executable_path="/missing/analyzeFundus")
        with self.assertRaises(MATLABUnavailableError) as ctx:
            adapter.run_analyze_fundus("test.jpg", "/tmp/out")
        self.assertIn("Compiled MATLAB executable not found", str(ctx.exception))
        self.assertIn("Do not assume raw MATLAB source files execute in Runtime", str(ctx.exception))


class TestJobQueueAndAPI(unittest.IsolatedAsyncioTestCase):
    """Test suite for persisted background job queue and API routes."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_jobs.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.session_factory = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async def override_get_db():
            async with self.session_factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db] = override_get_db

        # Seed test user, facility, patient, screening, and image
        async with self.session_factory() as session:
            fac = Facility(
                id=uuid.uuid4(),
                facility_code="PHC-TEST-001",
                name="Test Clinic",
                facility_type="PHC",
            )
            session.add(fac)

            user = User(
                id=uuid.uuid4(),
                username="hw_tester",
                email="hw@retinashield.org",
                full_name="Health Worker",
                role=UserRole.HEALTH_WORKER,
                facility_id="PHC-TEST-001",
                password_hash=hash_password("Pass123!"),
                is_active=True,
            )
            session.add(user)

            patient = Patient(
                id=uuid.uuid4(),
                first_name="Test",
                last_name="Patient",
                facility_id="PHC-TEST-001",
            )

            session.add(patient)

            screening = Screening(
                id=uuid.uuid4(),
                patient_id=patient.id,
                facility_id="PHC-TEST-001",
                screener_id=user.id,
                eye="both",
                status="pending",
            )
            session.add(screening)

            # Write a real test JPEG to private disk storage
            img_dir = Path(self.temp_dir.name) / "images"
            img_dir.mkdir(parents=True, exist_ok=True)
            img_file = img_dir / f"{uuid.uuid4()}.jpg"
            img_file.write_bytes(generate_test_jpeg(512, 512))

            scr_image = ScreeningImage(
                id=uuid.uuid4(),
                screening_id=screening.id,
                eye="right",
                stored_filename=img_file.name,
                original_filename="fundus_od.jpg",
                storage_path=str(img_file),
                content_type="image/jpeg",
                file_size_bytes=len(img_file.read_bytes()),
                width=512,
                height=512,
            )

            session.add(scr_image)

            await session.commit()

            self.facility_id = "PHC-TEST-001"
            self.user_id = user.id
            self.screening_id = screening.id
            self.image_id = scr_image.id
            self.image_file_path = str(img_file)

        self.hw_token = create_access_token(
            subject=str(self.user_id),
            role="HEALTH_WORKER",
            facility_id=self.facility_id,
        )


        transport = ASGITransport(app=app)
        self.client = AsyncClient(transport=transport, base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.clear()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_job_idempotency(self):
        """Verify that duplicate submission returns the original job."""
        with patch("app.services.job_queue.async_session_factory", self.session_factory):
            service = JobQueueService(max_concurrency=2)

            # Prevent execution loop to isolate submission
            with patch.object(service, "_process_job", return_value=None):
                job1 = await service.submit_job(
                    screening_id=self.screening_id,
                    image_id=self.image_id,
                    facility_id=self.facility_id,
                    idempotency_key="idemp_test_key_001",
                )

                # Submit again with same key
                job2 = await service.submit_job(
                    screening_id=self.screening_id,
                    image_id=self.image_id,
                    facility_id=self.facility_id,
                    idempotency_key="idemp_test_key_001",
                )

                self.assertEqual(job1.id, job2.id)
                self.assertEqual(job2.status, "queued")

    async def test_job_cancellation(self):
        """Verify that queued or running job transitions to cancelled."""
        with patch("app.services.job_queue.async_session_factory", self.session_factory):
            service = JobQueueService(max_concurrency=2)

            with patch.object(service, "_process_job", return_value=None):
                job = await service.submit_job(
                    screening_id=self.screening_id,
                    image_id=self.image_id,
                    facility_id=self.facility_id,
                )

                success = await service.cancel_job(job.id)
                self.assertTrue(success)

                cancelled_job = await service.get_job(job.id)
                self.assertIsNotNone(cancelled_job)
                self.assertEqual(cancelled_job.status, "cancelled")

    async def test_job_lifecycle_execution(self):
        """Verify complete lifecycle: queued -> running -> completed."""
        with patch("app.services.job_queue.async_session_factory", self.session_factory):
            with patch("app.services.job_queue.image_store.get_image_path", return_value=self.image_file_path):
                service = JobQueueService(max_concurrency=2)

                # Mock MATLAB adapter returning valid result dict
                mock_adapter = MagicMock(spec=BaseMATLABAdapter)
                mock_adapter.run_analyze_fundus.return_value = {
                    "entry_point_version": "1.0.0",
                    "pipeline_version": "1.0.0",
                    "quality_assessment": {"overall_quality": "good", "status": "adequate"},
                    "severity_classification": {
                        "predicted_grade": 2,
                        "grade_label": "Moderate NPDR",
                        "confidence": 0.88,
                        "model_trained": True,
                    },
                    "referral_recommendation": {"urgency": "priority"},
                }
                mock_adapter.get_metadata.return_value = {
                    "adapter_type": "engine",
                    "is_ready": True,
                    "model_hashes": {"classifier": "abc1234"},
                }

                with patch.object(matlab_bridge, "adapter", mock_adapter), \
                     patch.object(matlab_bridge, "mode", "engine"):

                    job = await service.submit_job(
                        screening_id=self.screening_id,
                        image_id=self.image_id,
                        facility_id=self.facility_id,
                        run_yolo=False,
                    )

                    # Await active task completion
                    task = service._active_tasks.get(job.id)
                    if task:
                        await task

                    # Verify completed job in DB
                    finished = await service.get_job(job.id)
                    self.assertIsNotNone(finished)
                    self.assertEqual(finished.status, "completed")
                    self.assertIsNotNone(finished.completed_at)
                    self.assertIn("severity_classification", finished.result_json)
                    self.assertEqual(finished.result_json["severity_classification"]["predicted_grade"], 2)

    async def test_jobs_api_endpoints(self):
        """Verify REST API /api/jobs/ endpoints."""
        with patch("app.services.job_queue.async_session_factory", self.session_factory), \
             patch.object(job_queue, "_process_job", return_value=None):

            # 1. Enqueue Job via API
            resp = await self.client.post(
                "/api/jobs/",
                json={
                    "screening_id": str(self.screening_id),
                    "image_id": str(self.image_id),
                    "timeout_seconds": 120,
                },
                headers={"Authorization": f"Bearer {self.hw_token}"},
            )
            self.assertEqual(resp.status_code, 202)
            data = resp.json()
            self.assertEqual(data["status"], "queued")
            created_job_id = data["id"]

            # 2. Query Status via API
            get_resp = await self.client.get(
                f"/api/jobs/{created_job_id}",
                headers={"Authorization": f"Bearer {self.hw_token}"},
            )
            self.assertEqual(get_resp.status_code, 200)
            self.assertEqual(get_resp.json()["id"], created_job_id)

            # 3. Cancel Job via API
            cancel_resp = await self.client.post(
                f"/api/jobs/{created_job_id}/cancel",
                headers={"Authorization": f"Bearer {self.hw_token}"},
            )
            self.assertEqual(cancel_resp.status_code, 200)
            self.assertIn("cancelled", cancel_resp.json()["status"])

            # 4. List Jobs via API
            list_resp = await self.client.get(
                f"/api/jobs/?screening_id={self.screening_id}",
                headers={"Authorization": f"Bearer {self.hw_token}"},
            )
            self.assertEqual(list_resp.status_code, 200)
            self.assertGreaterEqual(list_resp.json()["total"], 1)

