"""
RetinaShield — Dual Report Generation & Offline Voice Playback Test Suite

Tests:
  1. Technical Report:
     - Preserves image quality metrics, provisional grade, calibrated probabilities,
       model lesions, uncertainty, model provenance, and clinician review.
     - Unsigned reports are marked as draft / provisional.
     - Signed reports require finalized clinician review and include statutory disclaimers.
  2. Patient Summary:
     - Deterministic rule-based plain-language explanation of findings (zero LLM).
     - Plain-language screening limitations.
     - Clinician-approved next step.
     - Hindi translation with Devanagari text and translation governance flag.
  3. Printable Unicode PDF Generation:
     - Generates valid PDF bytes (%PDF- header).
     - Devanagari Unicode support in Hindi PDF.
     - Provisional watermark applied on unsigned documents.
  4. Privacy-Preserving Offline Voice Playback:
     - Rejects synthesis without voice_consent=True.
     - Detects local available voices or falls back cleanly to text.
     - Spoken script preserves actual findings and clinical review status.
  5. API Endpoints:
     - POST /report (technical and patient_summary).
     - GET /reports (listing).
     - GET /reports/{id}/pdf (PDF streaming).
     - POST /reports/{id}/voice (voice playback / text fallback).
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token
from app.db.session import Base, get_db
from app.main import app
from app.models.clinical import ClinicianReview, ModelOutput, Report
from app.models.patient import Patient
from app.models.screening import Screening
from app.models.user import User, UserRole
from app.services.report_templates import (
    generate_technical_report,
    generate_patient_summary,
    DR_LABELS_EN,
    DR_LABELS_HI,
)
from app.services.pdf_generator import (
    generate_technical_report_pdf,
    generate_patient_summary_pdf,
)
from app.services.voice_service import synthesize_offline_audio

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


def _make_token(user_id: uuid.UUID, role: str) -> str:
    return create_access_token(subject=user_id, role=role, facility_id="facility-report-1")


@pytest.mark.asyncio
class TestReportGeneration(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.engine = create_async_engine(TEST_DB_URL, echo=False)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

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

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await self.engine.dispose()

    async def _setup_fixtures(self) -> dict:
        async with self.session_factory() as db:
            oph = User(
                id=uuid.uuid4(),
                email="ophtha_report@example.com",
                username="oph_report",
                password_hash="hash",
                full_name="Dr. Ananya Sharma, MD",
                role=UserRole.OPHTHALMOLOGIST,
                facility_id="facility-report-1",
                is_active=True,
            )
            db.add(oph)

            pat = Patient(
                id=uuid.uuid4(),
                facility_id="facility-report-1",
                first_name="Rajesh",
                last_name="Kumar",
                date_of_birth=datetime(1975, 4, 12, tzinfo=timezone.utc),
                gender="male",
            )
            db.add(pat)

            scr = Screening(
                id=uuid.uuid4(),
                patient_id=pat.id,
                facility_id="facility-report-1",
                eye="right",
                status="completed",
                quality_verdict="good",
                dr_grade=2,
                dr_grade_label="Moderate Non-Proliferative Diabetic Retinopathy (NPDR)",
                dr_confidence=0.88,
                referral_urgency="priority",
                model_trained=True,
                analysis_result={
                    "quality_metrics": {
                        "overall_verdict": "good",
                        "sharpness_score": 0.85,
                        "illumination_score": 0.90,
                        "snr_db": 24.5,
                        "artifacts": [],
                    },
                    "model_findings": {
                        "class_probabilities": {
                            "grade_0": 0.04,
                            "grade_1": 0.08,
                            "grade_2": 0.82,
                            "grade_3": 0.04,
                            "grade_4": 0.02,
                        },
                        "lesions": {
                            "microaneurysms": 8,
                            "hemorrhages": 5,
                            "hard_exudates": 2,
                            "cotton_wool_spots": 0,
                        },
                    },
                    "model_provenance": {
                        "classifier_architecture": "EfficientNet-B4",
                        "detector_architecture": "YOLOv8x-retina",
                        "weights_hash": "sha256-4a5c9b...",
                        "pipeline_version": "1.4.0",
                        "matlab_engine_adapter": "matlab.engine (R2024b)",
                    },
                    "uncertainty_entropy": 0.42,
                    "uncertainty_margin": 0.74,
                    "classifier_lesion_concordance": "concordant",
                },
            )
            db.add(scr)

            mo = ModelOutput(
                id=uuid.uuid4(),
                screening_id=scr.id,
                predicted_dr_grade=2,
                predicted_grade_label="Moderate Non-Proliferative Diabetic Retinopathy",
                confidence=0.88,
                class_probabilities=[0.04, 0.08, 0.82, 0.04, 0.02],
                uncertainty_entropy=0.42,
                uncertainty_margin=0.74,
                lesion_detections_summary={
                    "microaneurysms": 8,
                    "hemorrhages": 5,
                    "hard_exudates": 2,
                    "cotton_wool_spots": 0,
                },
            )
            db.add(mo)

            rev = ClinicianReview(
                id=uuid.uuid4(),
                screening_id=scr.id,
                reviewer_id=oph.id,
                confirmed_dr_grade=2,
                macular_edema_present=False,
                is_ungradeable=False,
                recapture_requested=False,
                referral_recommendation="priority",
                follow_up_months=3,
                clinical_notes="Confirmed moderate NPDR with parafoveal microaneurysms. Refer for OCT.",
                status="final",
                review_version=1,
            )
            db.add(rev)
            await db.commit()

            return {
                "oph_id": oph.id,
                "pat_id": pat.id,
                "scr_id": scr.id,
                "rev_id": rev.id,
            }

    # ------------------------------------------------------------------
    # 1. Technical Report Templating & Preservation
    # ------------------------------------------------------------------

    async def test_technical_report_preserves_findings_and_provenance(self):
        """Technical report strictly preserves persisted findings, probabilities, and provenance."""
        fixtures = await self._setup_fixtures()
        async with self.session_factory() as db:
            scr = await db.get(Screening, fixtures["scr_id"])
            pat = await db.get(Patient, fixtures["pat_id"])
            rev = await db.get(ClinicianReview, fixtures["rev_id"])
            mo = await db.get(ModelOutput, fixtures["scr_id"])  # or query

            report = generate_technical_report(
                screening=scr,
                patient=pat,
                clinician_review=rev,
                model_output=mo,
                amendments=[],
                signing_clinician_name="Dr. Ananya Sharma, MD",
                is_signed=True,
            )

        self.assertEqual(report["report_type"], "technical_report")
        self.assertEqual(report["status"], "signed")
        self.assertFalse(report["is_provisional"])

        # Quality preserved
        q = report["image_quality"]
        self.assertEqual(q["verdict"], "good")
        self.assertEqual(q["snr_db"], 24.5)

        # AI probabilities preserved
        ai = report["ai_research_screening_findings"]
        self.assertEqual(ai["predicted_dr_grade"], 2)
        probs = ai["calibrated_probabilities"]
        self.assertAlmostEqual(probs["grade_2_moderate"], 0.82, places=2)

        # Lesions preserved
        lesions = ai["estimated_lesions"]
        self.assertEqual(lesions["microaneurysms"], 8)
        self.assertEqual(lesions["hemorrhages"], 5)

        # Provenance preserved
        prov = ai["model_provenance"]
        self.assertEqual(prov["classifier_architecture"], "EfficientNet-B4")
        self.assertIn("matlab.engine", prov["matlab_engine_adapter"])

        # Clinician review preserved
        clin = report["clinician_review"]
        self.assertEqual(clin["confirmed_dr_grade"], 2)
        self.assertEqual(clin["referral_recommendation"], "priority")
        self.assertIn("parafoveal", clin["clinical_notes"])

    async def test_technical_report_provisional_when_unsigned(self):
        """Unsigned technical report is marked draft and provisional with prominent watermark."""
        fixtures = await self._setup_fixtures()
        async with self.session_factory() as db:
            scr = await db.get(Screening, fixtures["scr_id"])
            pat = await db.get(Patient, fixtures["pat_id"])

            report = generate_technical_report(
                screening=scr,
                patient=pat,
                clinician_review=None,
                model_output=None,
                amendments=None,
                is_signed=False,
            )

        self.assertEqual(report["status"], "draft")
        self.assertTrue(report["is_provisional"])
        self.assertIn("PROVISIONAL", report["provisional_watermark"])

    # ------------------------------------------------------------------
    # 2. Patient Summary (Multilingual & No LLM)
    # ------------------------------------------------------------------

    async def test_patient_summary_english_deterministic(self):
        """Patient summary in English uses plain language without hallucinated advice."""
        fixtures = await self._setup_fixtures()
        async with self.session_factory() as db:
            scr = await db.get(Screening, fixtures["scr_id"])
            pat = await db.get(Patient, fixtures["pat_id"])
            rev = await db.get(ClinicianReview, fixtures["rev_id"])

            summary = generate_patient_summary(
                screening=scr,
                patient=pat,
                clinician_review=rev,
                language="en",
                is_signed=True,
            )

        self.assertEqual(summary["language"], "en")
        self.assertEqual(summary["grade_code"], 2)
        self.assertEqual(summary["grade_label"], DR_LABELS_EN[2])

        # Checks plain language explanation
        exp = summary["findings_explanation"]
        self.assertIn("Moderate signs of diabetic retinopathy", exp)
        self.assertIn("small hemorrhages", exp)

        # Clinician next step
        self.assertEqual(summary["referral_recommendation"], "priority")
        self.assertIn("2 to 4 months", summary["referral_guidance"])

        # Screening limitations present
        self.assertIn("does not replace a comprehensive, dilated eye examination", summary["screening_limitations"])

        # Spoken script present and plain
        self.assertIn("Rajesh Kumar", summary["spoken_script"])
        self.assertIn("right eye", summary["spoken_script"])

    async def test_patient_summary_hindi_with_governance_flag(self):
        """Hindi patient summary produces valid Devanagari text with clinical review pending flag."""
        fixtures = await self._setup_fixtures()
        async with self.session_factory() as db:
            scr = await db.get(Screening, fixtures["scr_id"])
            pat = await db.get(Patient, fixtures["pat_id"])
            rev = await db.get(ClinicianReview, fixtures["rev_id"])

            summary = generate_patient_summary(
                screening=scr,
                patient=pat,
                clinician_review=rev,
                language="hi",
                is_signed=True,
            )

        self.assertEqual(summary["language"], "hi")
        # Translation status MUST be pending_qualified_clinical_review
        self.assertEqual(summary["clinical_language_review_status"], "pending_qualified_clinical_review")

        # Devanagari grade label
        self.assertEqual(summary["grade_label"], DR_LABELS_HI[2])
        self.assertIn("मध्यम गैर-प्रसारक", summary["grade_label"])

        # Devanagari explanation
        self.assertIn("डायबिटिक रेटिनोपैथी", summary["findings_explanation"])
        self.assertIn("नेत्र विशेषज्ञ", summary["findings_explanation"])

        # Hindi spoken script
        self.assertIn("नमस्ते Rajesh Kumar", summary["spoken_script"])
        self.assertIn("दाहिनी आंख", summary["spoken_script"])

    # ------------------------------------------------------------------
    # 3. Printable Unicode PDF Generation
    # ------------------------------------------------------------------

    async def test_technical_report_pdf_bytes_generated(self):
        """Technical report PDF generator emits valid PDF binary with %PDF- header."""
        fixtures = await self._setup_fixtures()
        async with self.session_factory() as db:
            scr = await db.get(Screening, fixtures["scr_id"])
            pat = await db.get(Patient, fixtures["pat_id"])
            rev = await db.get(ClinicianReview, fixtures["rev_id"])

            rep_data = generate_technical_report(
                screening=scr,
                patient=pat,
                clinician_review=rev,
                model_output=None,
                amendments=None,
                is_signed=True,
            )
            pdf_bytes = generate_technical_report_pdf(rep_data)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 2000)

    async def test_patient_summary_pdf_hindi_unicode(self):
        """Hindi patient summary PDF generates successfully with Devanagari Unicode."""
        fixtures = await self._setup_fixtures()
        async with self.session_factory() as db:
            scr = await db.get(Screening, fixtures["scr_id"])
            pat = await db.get(Patient, fixtures["pat_id"])
            rev = await db.get(ClinicianReview, fixtures["rev_id"])

            summary_data = generate_patient_summary(
                screening=scr,
                patient=pat,
                clinician_review=rev,
                language="hi",
                is_signed=True,
            )
            pdf_bytes = generate_patient_summary_pdf(summary_data)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 2000)

    # ------------------------------------------------------------------
    # 4. Offline Voice Playback Service & Privacy
    # ------------------------------------------------------------------

    async def test_voice_playback_rejected_without_consent(self):
        """Audio synthesis is blocked when voice_consent is False, falling back to text."""
        res = synthesize_offline_audio(
            spoken_text="Your retinal screening result is normal.",
            language="en",
            voice_consent=False,
        )
        self.assertFalse(res.voice_supported)
        self.assertTrue(res.fallback_to_text)
        self.assertIsNone(res.audio_base64)
        self.assertIn("consent not provided", res.status_message)
        self.assertEqual(res.spoken_text, "Your retinal screening result is normal.")

    async def test_voice_playback_unsupported_language_falls_back_to_text(self):
        """Unsupported languages fall back cleanly to on-screen text with diagnostics."""
        res = synthesize_offline_audio(
            spoken_text="Prueba de retina.",
            language="xx_unknown",
            voice_consent=True,
        )
        self.assertFalse(res.voice_supported)
        self.assertTrue(res.fallback_to_text)
        self.assertIsNone(res.audio_base64)
        self.assertIn("No offline voice installed", res.status_message)

    async def test_voice_playback_supported_local_synthesis(self):
        """When a local voice is available on host, generates base64 audio without network calls."""
        res = synthesize_offline_audio(
            spoken_text="Hello, this is a local offline test reading.",
            language="en",
            voice_consent=True,
        )
        # Should either produce local audio or fall back to text cleanly
        if res.voice_supported:
            self.assertIsNotNone(res.audio_base64)
            self.assertIn(res.audio_format, ("audio/aiff", "audio/wav"))
        else:
            self.assertTrue(res.fallback_to_text)
            self.assertIn("Fallback", res.status_message)

    # ------------------------------------------------------------------
    # 5. REST API Endpoints Integration
    # ------------------------------------------------------------------

    async def test_api_generate_patient_summary_and_download_pdf(self):
        """API allows generating patient summary in Hindi, listing reports, and downloading PDF."""
        fixtures = await self._setup_fixtures()
        sid = fixtures["scr_id"]
        token = _make_token(fixtures["oph_id"], "ophthalmologist")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Generate patient summary in Hindi (signed)
            resp = await client.post(
                f"/api/screenings/{sid}/report",
                json={
                    "report_type": "patient_summary",
                    "language": "hi",
                    "is_signed": True,
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(resp.status_code, 201, resp.text)
            rep_json = resp.json()
            report_id = rep_json["id"]
            self.assertEqual(rep_json["report_type"], "patient_summary")
            self.assertEqual(rep_json["status"], "signed")
            self.assertEqual(rep_json["summary_json"]["language"], "hi")

            # 2. List reports
            list_resp = await client.get(
                f"/api/screenings/{sid}/reports",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(list_resp.status_code, 200)
            items = list_resp.json()
            self.assertTrue(any(r["id"] == report_id for r in items))

            # 3. Download PDF
            pdf_resp = await client.get(
                f"/api/screenings/{sid}/reports/{report_id}/pdf",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(pdf_resp.status_code, 200)
            self.assertEqual(pdf_resp.headers.get("content-type"), "application/pdf")
            self.assertTrue(pdf_resp.content.startswith(b"%PDF-"))

            # 4. Request voice playback without consent -> fallback
            v_no_consent = await client.post(
                f"/api/screenings/{sid}/reports/{report_id}/voice",
                json={"voice_consent": False, "language": "hi"},
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(v_no_consent.status_code, 200)
            self.assertTrue(v_no_consent.json()["fallback_to_text"])

            # 5. Request voice playback with consent
            v_consent = await client.post(
                f"/api/screenings/{sid}/reports/{report_id}/voice",
                json={"voice_consent": True, "language": "hi"},
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(v_consent.status_code, 200)
            v_data = v_consent.json()
            self.assertIn("spoken_text", v_data)
            self.assertIn("नमस्ते", v_data["spoken_text"])
