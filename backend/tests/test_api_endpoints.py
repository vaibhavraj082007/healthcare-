"""
RetinaShield — API Endpoints & Screening Pipeline Test Suite

Tests:
- Patient creation with minimal details (no mandatory Aadhaar/ABHA).
- Informed consent recording and withdrawal.
- Image ingestion validation: magic bytes, dimensions, SHA-256 hash.
- Authenticated private image streaming with facility access control.
- Separation of AI findings and clinician review sign-off.
"""

from __future__ import annotations

import io
import tempfile
import unittest
import uuid
from pathlib import Path
from PIL import Image as PILImage

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.security import hash_password, create_access_token
from app.db.session import Base, get_db
from app.models.user import User, UserRole
from app.models.facility import Facility
from app.models.patient import Patient
from app.models.screening import Screening
from app.main import app


def generate_test_jpeg(width: int = 600, height: int = 600) -> bytes:
    """Generate a real JPEG image in memory with specified dimensions."""
    img = PILImage.new("RGB", (width, height), color=(180, 50, 40))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class TestAPIEndpoints(unittest.IsolatedAsyncioTestCase):
    """Test suite for clinical and screening endpoints."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_api.db"
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
                finally:
                    await session.close()

        app.dependency_overrides[get_db] = override_get_db

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_patient_registration_without_aadhaar_or_abha(self):
        """Verify patients can be registered with minimal details, without Aadhaar or ABHA."""
        async with self.session_factory() as session:
            fac = Facility(facility_code="PHC-MAH-01", name="Mahal PHC")
            session.add(fac)
            hw = User(
                username="hw_sita",
                email="sita@phc.in",
                full_name="Sita Patil",
                role=UserRole.HEALTH_WORKER,
                facility_id="PHC-MAH-01",
                password_hash=hash_password("Pass123456"),
                is_active=True,
            )
            session.add(hw)
            await session.commit()
            hw_id = str(hw.id)

        hw_token = create_access_token(subject=hw_id, role="health-worker", facility_id="PHC-MAH-01")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Register patient with zero Aadhaar or ABHA info
            resp = await client.post(
                "/api/patients/",
                json={
                    "first_name": "Ramesh",
                    "last_name": "Kumar",
                    "date_of_birth": "1965-05-12",
                    "gender": "Male",
                    "phone": "9876543210",
                    "diabetes_type": "Type 2",
                },
                headers={"Authorization": f"Bearer {hw_token}"},
            )
            self.assertEqual(resp.status_code, 201)
            patient_data = resp.json()
            self.assertEqual(patient_data["first_name"], "Ramesh")
            self.assertIsNone(patient_data["aadhaar_last4"])
            self.assertEqual(patient_data["facility_id"], "PHC-MAH-01")

    async def test_consent_recording_and_withdrawal(self):
        """Verify consent recording and subsequent withdrawal under DPDP."""
        async with self.session_factory() as session:
            fac = Facility(facility_code="PHC-01", name="PHC 1")
            session.add(fac)
            patient = Patient(first_name="Anita", last_name="Sharma", facility_id="PHC-01")
            session.add(patient)
            hw = User(
                username="hw_worker",
                email="worker@phc.in",
                full_name="Worker A",
                role=UserRole.HEALTH_WORKER,
                facility_id="PHC-01",
                password_hash=hash_password("Pass123456"),
                is_active=True,
            )
            session.add(hw)
            await session.commit()
            patient_id = str(patient.id)
            hw_id = str(hw.id)

        hw_token = create_access_token(subject=hw_id, role="health-worker", facility_id="PHC-01")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Record consent
            consent_resp = await client.post(
                "/api/consent/",
                json={
                    "patient_id": patient_id,
                    "consent_type": "dr_screening_and_teleophthalmology",
                    "granted": True,
                },
                headers={"Authorization": f"Bearer {hw_token}"},
            )
            self.assertEqual(consent_resp.status_code, 201)
            consent_data = consent_resp.json()
            self.assertTrue(consent_data["granted"])
            self.assertFalse(consent_data["withdrawn"])
            consent_id = consent_data["id"]

            # 2. Withdraw consent
            withdraw_resp = await client.post(
                f"/api/consent/{consent_id}/withdraw",
                json={"withdrawal_reason": "Patient requested withdrawal of data processing"},
                headers={"Authorization": f"Bearer {hw_token}"},
            )
            self.assertEqual(withdraw_resp.status_code, 200)
            self.assertTrue(withdraw_resp.json()["withdrawn"])
            self.assertEqual(
                withdraw_resp.json()["withdrawal_reason"],
                "Patient requested withdrawal of data processing",
            )

    async def test_image_upload_validation_and_private_streaming(self):
        """Verify magic bytes validation, dimension limits, and private streaming access control."""
        async with self.session_factory() as session:
            fac1 = Facility(facility_code="PHC-A", name="PHC A")
            fac2 = Facility(facility_code="PHC-B", name="PHC B")
            session.add_all([fac1, fac2])

            patient = Patient(first_name="Gita", last_name="Bose", facility_id="PHC-A")
            session.add(patient)
            await session.flush()

            screening = Screening(patient_id=patient.id, facility_id="PHC-A", eye="left")
            session.add(screening)

            hw_a = User(
                username="hw_a",
                email="hwa@phc.in",
                full_name="Worker Alpha",
                role=UserRole.HEALTH_WORKER,
                facility_id="PHC-A",
                password_hash=hash_password("Pass123456"),
                is_active=True,
            )
            hw_b = User(
                username="hw_b",
                email="hwb@phc.in",
                full_name="Worker Beta",
                role=UserRole.HEALTH_WORKER,
                facility_id="PHC-B",
                password_hash=hash_password("Pass123456"),
                is_active=True,
            )
            oph = User(
                username="dr_eye",
                email="eye@retina.org",
                full_name="Dr. Eye",
                role=UserRole.OPHTHALMOLOGIST,
                password_hash=hash_password("Pass123456"),
                is_active=True,
            )
            session.add_all([hw_a, hw_b, oph])
            await session.commit()

            screening_id = str(screening.id)
            hw_a_id = str(hw_a.id)
            hw_b_id = str(hw_b.id)
            oph_id = str(oph.id)

        token_hw_a = create_access_token(subject=hw_a_id, role="health-worker", facility_id="PHC-A")
        token_hw_b = create_access_token(subject=hw_b_id, role="health-worker", facility_id="PHC-B")
        token_oph = create_access_token(subject=oph_id, role="ophthalmologist")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Reject fake non-image file
            fake_file = io.BytesIO(b"Not an image at all, just plain text.")
            bad_upload = await client.post(
                f"/api/screenings/{screening_id}/images?eye=left",
                files={"file": ("fake.jpg", fake_file, "image/jpeg")},
                headers={"Authorization": f"Bearer {token_hw_a}"},
            )
            self.assertEqual(bad_upload.status_code, 400)
            self.assertIn("Invalid image header", bad_upload.json()["detail"])

            # 2. Reject image that is too small (<512px)
            small_jpeg = generate_test_jpeg(width=200, height=200)
            small_upload = await client.post(
                f"/api/screenings/{screening_id}/images?eye=left",
                files={"file": ("small.jpg", io.BytesIO(small_jpeg), "image/jpeg")},
                headers={"Authorization": f"Bearer {token_hw_a}"},
            )
            self.assertEqual(small_upload.status_code, 400)
            self.assertIn("below minimum required resolution", small_upload.json()["detail"])

            # 3. Accept valid 600x600 fundus JPEG
            valid_jpeg = generate_test_jpeg(width=600, height=600)
            good_upload = await client.post(
                f"/api/screenings/{screening_id}/images?eye=left",
                files={"file": ("fundus_left.jpg", io.BytesIO(valid_jpeg), "image/jpeg")},
                headers={"Authorization": f"Bearer {token_hw_a}"},
            )
            self.assertEqual(good_upload.status_code, 201)
            img_info = good_upload.json()
            self.assertEqual(img_info["width"], 600)
            self.assertEqual(img_info["height"], 600)
            self.assertIn("sha256_hash", img_info)
            image_id = img_info["image_id"]

            # 4. Stream image — Unauthenticated -> 401
            unauth_resp = await client.get(
                f"/api/screenings/{screening_id}/images/{image_id}/view"
            )
            self.assertEqual(unauth_resp.status_code, 401)

            # 5. Stream image — Cross-facility Health Worker B -> 403
            forbidden_resp = await client.get(
                f"/api/screenings/{screening_id}/images/{image_id}/view",
                headers={"Authorization": f"Bearer {token_hw_b}"},
            )
            self.assertEqual(forbidden_resp.status_code, 403)

            # 6. Stream image — Authorized Health Worker A -> 200 bytes
            stream_hw = await client.get(
                f"/api/screenings/{screening_id}/images/{image_id}/view",
                headers={"Authorization": f"Bearer {token_hw_a}"},
            )
            self.assertEqual(stream_hw.status_code, 200)
            self.assertEqual(stream_hw.headers["content-type"], "image/jpeg")
            self.assertEqual(len(stream_hw.content), len(valid_jpeg))

            # 7. Stream image — Ophthalmologist (tele-ophthalmology reviewer) -> 200 bytes
            stream_oph = await client.get(
                f"/api/screenings/{screening_id}/images/{image_id}/view",
                headers={"Authorization": f"Bearer {token_oph}"},
            )
            self.assertEqual(stream_oph.status_code, 200)
            self.assertEqual(len(stream_oph.content), len(valid_jpeg))

    async def test_separation_of_ai_findings_and_clinician_review(self):
        """Verify AI model output is strictly separated from authoritative clinician review."""
        async with self.session_factory() as session:
            fac = Facility(facility_code="PHC-C", name="PHC C")
            session.add(fac)
            patient = Patient(first_name="Sunil", last_name="Verma", facility_id="PHC-C")
            session.add(patient)
            await session.flush()

            screening = Screening(
                patient_id=patient.id,
                facility_id="PHC-C",
                eye="both",
                dr_grade=2,
                dr_grade_label="Moderate NPDR",
                dr_confidence=0.82,
                referral_urgency="routine",
                model_trained=True,
            )
            session.add(screening)

            oph = User(
                username="dr_mehta",
                email="mehta@eyehospital.org",
                full_name="Dr. Mehta, MD",
                role=UserRole.OPHTHALMOLOGIST,
                password_hash=hash_password("DocPass@2026"),
                is_active=True,
            )
            session.add(oph)
            await session.commit()

            screening_id = str(screening.id)
            oph_id = str(oph.id)

        oph_token = create_access_token(subject=oph_id, role="ophthalmologist")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Ophthalmologist enters clinical review: confirms severe NPDR (different from AI's grade 2)
            review_resp = await client.post(
                f"/api/screenings/{screening_id}/review",
                json={
                    "confirmed_dr_grade": 3,
                    "macular_edema_present": True,
                    "referral_recommendation": "priority",
                    "follow_up_months": 2,
                    "clinical_notes": "Multiple blot hemorrhages in all 4 quadrants with macular thickening.",
                    "status": "final",
                },
                headers={"Authorization": f"Bearer {oph_token}"},
            )
            self.assertEqual(review_resp.status_code, 201)
            review_data = review_resp.json()
            self.assertEqual(review_data["confirmed_dr_grade"], 3)
            self.assertEqual(review_data["referral_recommendation"], "priority")

            # Verify the underlying screening record still retains the original AI grade 2
            screening_get = await client.get(
                f"/api/screenings/{screening_id}",
                headers={"Authorization": f"Bearer {oph_token}"},
            )
            self.assertEqual(screening_get.status_code, 200)
            sc_data = screening_get.json()
            self.assertEqual(sc_data["dr_grade"], 2)  # Unaltered AI finding!
            self.assertEqual(sc_data["status"], "reviewed")

            # Generate official signed clinical report
            report_resp = await client.post(
                f"/api/screenings/{screening_id}/report",
                json={"report_type": "ophthalmology_referral"},
                headers={"Authorization": f"Bearer {oph_token}"},
            )
            self.assertEqual(report_resp.status_code, 201)
            rep_data = report_resp.json()
            summary = rep_data["summary_json"]

            # Check strict separation in report
            self.assertEqual(summary["authoritative_clinician_diagnosis"]["confirmed_dr_grade"], 3)
            self.assertEqual(
                summary["authoritative_clinician_diagnosis"]["signature_status"],
                "SIGNED_BY_OPHTHALMOLOGIST",
            )
            self.assertEqual(summary["ai_research_screening_findings"]["predicted_dr_grade"], 2)
            self.assertIn(
                "RESEARCH SCREENING RESULT ONLY",
                summary["ai_research_screening_findings"]["disclaimer"],
            )

    async def test_operational_monitoring_endpoints(self):
        """Verify GET /api/monitoring/operational, /shifts, /interop/status, and /export."""
        async with self.session_factory() as session:
            user = User(
                username=f"mon_user_{uuid.uuid4().hex[:6]}",
                email=f"mon_{uuid.uuid4().hex[:6]}@phc.in",
                full_name="Monitoring Tester",
                role=UserRole.OPHTHALMOLOGIST,
                password_hash=hash_password("Pass123!"),
                is_active=True,
            )
            session.add(user)
            await session.commit()
            user_id = str(user.id)

        token = create_access_token(subject=user_id, role="ophthalmologist")
        headers = {"Authorization": f"Bearer {token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Operational metrics
            op_resp = await client.get("/api/monitoring/operational?days=30", headers=headers)
            self.assertEqual(op_resp.status_code, 200)
            op_data = op_resp.json()
            self.assertIn("screening_volume", op_data)
            self.assertIn("ungradeable_rates", op_data)
            self.assertIn("review_backlog", op_data)
            self.assertIn("processing_failures", op_data)
            self.assertIn("synchronization_failures", op_data)
            self.assertIn("latency", op_data)
            self.assertIn("model_version_usage", op_data)
            self.assertIn("clinical_accuracy_separation_disclaimer", op_data)

            # 2. Shift monitoring
            shift_resp = await client.get("/api/monitoring/shifts?current_days=7&baseline_days=30", headers=headers)
            self.assertEqual(shift_resp.status_code, 200)
            shift_data = shift_resp.json()
            self.assertIn("quality_shift_metrics", shift_data)
            self.assertIn("prediction_dr_grade_shift", shift_data)
            self.assertIn("regulatory_safety_notice", shift_data)
            self.assertIn("AUTONOMOUS RETRAINING FROM UNVERIFIED AI OUTPUTS IS STRICTLY PROHIBITED", shift_data["regulatory_safety_notice"])

            # 3. Interoperability status
            interop_resp = await client.get("/api/monitoring/interop/status", headers=headers)
            self.assertEqual(interop_resp.status_code, 200)
            interop_data = interop_resp.json()
            self.assertEqual(interop_data["fhir_version"], "4.0.1")
            self.assertFalse(interop_data["abdm_exchange_enabled"])
            self.assertIn("safeguards", interop_data)

            # 4. Interoperability test exchange check
            test_resp = await client.post("/api/monitoring/interop/exchange/test", headers=headers)
            self.assertEqual(test_resp.status_code, 200)
            test_data = test_resp.json()
            self.assertFalse(test_data["allowed"])
            self.assertIn("prerequisite_checklist", test_data)
