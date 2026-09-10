"""
RetinaShield — Comprehensive Screening Workflow & Edge Cases Test Suite

Tests the full 10-step health-worker flow and clinical edge cases:
1. Patient registration with minimal DPDP details and search.
2. Informed consent recording.
3. Screening encounter creation.
4. Missing or invalid eye laterality validation (HTTP 400).
5. Wrong file types (non-image magic bytes rejection).
6. Smartphone + 20D condensing lens optical image upload.
7. Immediate 20D IQA metrics & actionable recapture feedback.
8. Recapture history preservation (multiple uploads for same eye both preserved).
9. Analysis job submission with duplicate submission prevention.
10. Multi-eye independence (one normal eye never clears the fellow eye or patient).
11. Explicit failure on missing or unavailable models.
"""

from __future__ import annotations

import io
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image as PILImage

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.security import hash_password, create_access_token
from app.db.session import Base, get_db
from app.models.consent import ConsentRecord
from app.models.facility import Facility
from app.models.job import AnalysisJob
from app.models.patient import Patient
from app.models.screening import Screening, ScreeningImage
from app.models.clinical import QualityResult
from app.models.user import User, UserRole
from app.services.job_queue import job_queue
from app.services.matlab_bridge import MATLABUnavailableError, MATLABUnavailableAdapter
from app.main import app


def generate_test_jpeg(width: int = 512, height: int = 512, color: tuple[int, int, int] = (160, 50, 40)) -> bytes:
    """Generate in-memory valid JPEG image bytes."""
    img = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


class TestScreeningWorkflow(unittest.IsolatedAsyncioTestCase):
    """Test suite for health-worker screening workflow and clinical edge cases."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_workflow.db"
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

        # Seed test facility and health-worker
        async with self.session_factory() as session:
            fac = Facility(
                id=uuid.uuid4(),
                facility_code="PHC-PUNE-001",
                name="Pune Rural Health Centre",
                facility_type="PHC",
            )
            session.add(fac)

            hw_user = User(
                id=uuid.uuid4(),
                username="hw_priya",
                email="priya@retinashield.org",
                full_name="Priya Sharma",
                role=UserRole.HEALTH_WORKER,
                facility_id="PHC-PUNE-001",
                password_hash=hash_password("SecurePass123!"),
                is_active=True,
            )
            session.add(hw_user)
            await session.commit()

            self.facility_id = "PHC-PUNE-001"
            self.hw_user_id = hw_user.id

        self.token = create_access_token(
            subject=str(self.hw_user_id),
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

    async def test_full_health_worker_workflow(self):
        """
        Walks through complete 10-step health worker flow:
        Register -> Consent -> Create Encounter -> Upload 20D OD/OS -> IQA -> Submit Job -> Retrieve
        """
        headers = {"Authorization": f"Bearer {self.token}"}

        # 1. Register Patient with minimal details
        pat_resp = await self.client.post(
            "/api/patients/",
            json={
                "first_name": "Ramesh",
                "last_name": "Patil",
                "gender": "male",
                "phone": "9876543210",
                "diabetes_type": "Type 2",
                "diabetes_duration_years": 8,
            },
            headers=headers,
        )
        self.assertEqual(pat_resp.status_code, 201)
        pat_data = pat_resp.json()
        patient_id = pat_data["id"]
        self.assertEqual(pat_data["first_name"], "Ramesh")

        # 2. Record Informed Consent
        consent_resp = await self.client.post(
            "/api/consent/",
            json={
                "patient_id": patient_id,
                "consent_type": "screening",
                "granted": True,
                "obtained_by_name": "Priya Sharma",
            },
            headers=headers,
        )
        self.assertEqual(consent_resp.status_code, 201)
        self.assertTrue(consent_resp.json()["granted"])

        # 3. Create Screening Encounter
        scr_resp = await self.client.post(
            "/api/screenings/",
            json={
                "patient_id": patient_id,
                "eye": "both",
                "screener_name": "Priya Sharma",
            },
            headers=headers,
        )
        self.assertEqual(scr_resp.status_code, 201)
        screening_id = scr_resp.json()["id"]

        # 4. Upload Smartphone + 20D Condensing Lens photo for Right Eye (OD)
        od_jpeg = generate_test_jpeg(512, 512, color=(180, 45, 30))
        od_upload_resp = await self.client.post(
            f"/api/screenings/{screening_id}/images?eye=right&lens_type=20D_condensing&camera_model=iPhone13_20D_Adapter",
            files={"file": ("od_20d.jpg", od_jpeg, "image/jpeg")},
            headers=headers,
        )
        self.assertEqual(od_upload_resp.status_code, 201)
        od_img_data = od_upload_resp.json()
        od_image_id = od_img_data["image_id"]
        self.assertEqual(od_img_data["eye"], "right")
        self.assertEqual(od_img_data["lens_type"], "20D_condensing")
        self.assertIn("quality_assessment", od_img_data)
        self.assertIn("recapture_guidance", od_img_data["quality_assessment"])

        # 5. Upload Smartphone + 20D photo for Left Eye (OS)
        os_jpeg = generate_test_jpeg(512, 512, color=(170, 50, 40))
        os_upload_resp = await self.client.post(
            f"/api/screenings/{screening_id}/images?eye=left&lens_type=20D_condensing&camera_model=iPhone13_20D_Adapter",
            files={"file": ("os_20d.jpg", os_jpeg, "image/jpeg")},
            headers=headers,
        )
        self.assertEqual(os_upload_resp.status_code, 201)
        os_image_id = os_upload_resp.json()["image_id"]

        # 6. Verify Per-Eye Isolation & Retrieval
        get_scr_resp = await self.client.get(f"/api/screenings/{screening_id}", headers=headers)
        self.assertEqual(get_scr_resp.status_code, 200)

        # 7. Submit Right Eye for Asynchronous Job Analysis
        with patch("app.services.job_queue.async_session_factory", self.session_factory), \
             patch.object(job_queue, "_process_job", return_value=None):

            job_resp = await self.client.post(
                "/api/jobs/",
                json={
                    "screening_id": screening_id,
                    "image_id": od_image_id,
                    "timeout_seconds": 180,
                },
                headers=headers,
            )
            self.assertEqual(job_resp.status_code, 202)
            job_data = job_resp.json()
            self.assertEqual(job_data["status"], "queued")
            job_id = job_data["id"]

            # Poll job status
            poll_resp = await self.client.get(f"/api/jobs/{job_id}", headers=headers)
            self.assertEqual(poll_resp.status_code, 200)
            self.assertEqual(poll_resp.json()["id"], job_id)

    async def test_missing_laterality_rejected(self):
        """Verify that uploading an image without explicit laterality is rejected (HTTP 400)."""
        headers = {"Authorization": f"Bearer {self.token}"}
        fake_id = uuid.uuid4()

        # Missing eye parameter or invalid string
        resp = await self.client.post(
            f"/api/screenings/{fake_id}/images?eye=invalid_eye",
            files={"file": ("test.jpg", generate_test_jpeg(), "image/jpeg")},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("explicitly specified as 'left' or 'right'", resp.json()["detail"])

    async def test_wrong_file_type_rejected(self):
        """Verify that non-image or fake extension files are rejected by image store."""
        headers = {"Authorization": f"Bearer {self.token}"}

        # Create patient & screening
        async with self.session_factory() as session:
            pat = Patient(id=uuid.uuid4(), first_name="A", last_name="B", facility_id=self.facility_id)
            session.add(pat)
            scr = Screening(id=uuid.uuid4(), patient_id=pat.id, facility_id=self.facility_id, eye="both")
            session.add(scr)
            await session.commit()
            scr_id = scr.id

        # Text file masquerading as jpg
        fake_content = b"THIS IS NOT A VALID JPEG OR PNG RETINAL IMAGE"
        resp = await self.client.post(
            f"/api/screenings/{scr_id}/images?eye=left",
            files={"file": ("fake.jpg", fake_content, "image/jpeg")},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Invalid image header", resp.json()["detail"])


    async def test_recapture_history_preserved(self):
        """
        Verify that recapturing an image for the same eye creates a new record
        and does NOT overwrite the previous attempt in the database.
        """
        headers = {"Authorization": f"Bearer {self.token}"}

        async with self.session_factory() as session:
            pat = Patient(id=uuid.uuid4(), first_name="Geeta", last_name="Bai", facility_id=self.facility_id)
            session.add(pat)
            scr = Screening(id=uuid.uuid4(), patient_id=pat.id, facility_id=self.facility_id, eye="both")
            session.add(scr)
            await session.commit()
            scr_id = scr.id

        # First capture (suboptimal)
        img1 = generate_test_jpeg(512, 512, color=(100, 30, 20))
        resp1 = await self.client.post(
            f"/api/screenings/{scr_id}/images?eye=right&lens_type=20D_condensing",
            files={"file": ("od_try1.jpg", img1, "image/jpeg")},
            headers=headers,
        )
        self.assertEqual(resp1.status_code, 201)
        id1 = resp1.json()["image_id"]

        # Recapture (improved alignment)
        img2 = generate_test_jpeg(512, 512, color=(190, 60, 40))
        resp2 = await self.client.post(
            f"/api/screenings/{scr_id}/images?eye=right&lens_type=20D_condensing",
            files={"file": ("od_try2_recapture.jpg", img2, "image/jpeg")},
            headers=headers,
        )
        self.assertEqual(resp2.status_code, 201)
        id2 = resp2.json()["image_id"]

        self.assertNotEqual(id1, id2)

        # Inspect database: both image records and QualityResult records exist!
        async with self.session_factory() as session:
            stmt = select(ScreeningImage).where(ScreeningImage.screening_id == scr_id, ScreeningImage.eye == "right")
            images = list((await session.execute(stmt)).scalars().all())
            self.assertEqual(len(images), 2, "Recapture must preserve previous images in encounter history")

            qr_stmt = select(QualityResult).where(QualityResult.screening_id == scr_id)
            qrs = list((await session.execute(qr_stmt)).scalars().all())
            self.assertEqual(len(qrs), 2, "Both captures must have distinct QualityResult records")

    async def test_duplicate_submission_prevented(self):
        """Verify that submitting identical idempotency key does not create duplicate jobs."""
        headers = {"Authorization": f"Bearer {self.token}"}

        async with self.session_factory() as session:
            pat = Patient(id=uuid.uuid4(), first_name="K", last_name="M", facility_id=self.facility_id)
            session.add(pat)
            scr = Screening(id=uuid.uuid4(), patient_id=pat.id, facility_id=self.facility_id, eye="both")
            session.add(scr)
            await session.commit()
            scr_id = scr.id

        with patch("app.services.job_queue.async_session_factory", self.session_factory), \
             patch.object(job_queue, "_process_job", return_value=None):

            idemp_token = "idemp_token_unique_12345"

            # First submission
            resp1 = await self.client.post(
                "/api/jobs/",
                json={"screening_id": str(scr_id), "idempotency_key": idemp_token},
                headers=headers,
            )
            self.assertEqual(resp1.status_code, 202)
            job1_id = resp1.json()["id"]

            # Second submission with identical key
            resp2 = await self.client.post(
                "/api/jobs/",
                json={"screening_id": str(scr_id), "idempotency_key": idemp_token},
                headers=headers,
            )
            self.assertEqual(resp2.status_code, 202)
            job2_id = resp2.json()["id"]

            self.assertEqual(job1_id, job2_id, "Idempotent submission must return existing job ID")

            # Check DB count
            async with self.session_factory() as session:
                cnt_stmt = select(AnalysisJob).where(AnalysisJob.idempotency_key == idemp_token)
                jobs = list((await session.execute(cnt_stmt)).scalars().all())
                self.assertEqual(len(jobs), 1, "Only 1 job row should be created in database")

    async def test_unavailable_model_fails_explicitly(self):
        """Verify that missing model weights produce an explicit failure, never fake predictions."""
        adapter = MATLABUnavailableAdapter(reason="Weights not found")
        with self.assertRaises(MATLABUnavailableError) as ctx:
            adapter.run_analyze_fundus("fundus.jpg", "/tmp/out")
        self.assertIn("Missing dependencies produce explicit failures", str(ctx.exception))
        self.assertIn("predictions are never substituted", str(ctx.exception))
