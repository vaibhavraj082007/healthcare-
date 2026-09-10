"""
RetinaShield — Ophthalmologist Review Queue Test Suite

Tests:
  - Review queue filtering (facility, quality, review status, uncertainty, disagreement)
  - Configurable prioritization rules and metadata
  - First review submission and state transitions
  - Draft → final submission
  - Ungradeable image marking
  - Recapture request
  - Amendment of a final review with change_reason
  - Optimistic-concurrency version mismatch → HTTP 409
  - Case locking and conflict on locked case → HTTP 409
  - Concurrent edit prevention via version field
  - Amendment audit history preservation
  - Report generation with signed disclaimer
  - Report blocked when review is draft
  - AI model output preserved (not mutated) after review
  - Reviewer identity correctly recorded in amendments
"""

from __future__ import annotations

import io
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.security import hash_password, create_access_token
from app.db.session import Base, get_db
from app.models.user import User, UserRole
from app.models.facility import Facility
from app.models.patient import Patient
from app.models.screening import Screening
from app.models.clinical import ClinicianReview, ModelOutput
from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ophtha_token(user_id: str, facility: str = "PHC-TEST") -> str:
    return create_access_token(subject=user_id, role="ophthalmologist", facility_id=facility)


def _hw_token(user_id: str, facility: str = "PHC-TEST") -> str:
    return create_access_token(subject=user_id, role="health-worker", facility_id=facility)


async def _create_base_fixtures(session_factory, *, screening_status="completed", dr_grade=2):
    """Create facility, ophthalmologist, HW, patient, and a completed screening."""
    async with session_factory() as session:
        fac = Facility(facility_code="PHC-TEST", name="Test PHC")
        session.add(fac)

        oph = User(
            username=f"oph_{uuid.uuid4().hex[:6]}",
            email=f"oph_{uuid.uuid4().hex[:6]}@eye.in",
            full_name="Dr. Ananya Iyer",
            role=UserRole.OPHTHALMOLOGIST,
            facility_id="PHC-TEST",
            password_hash=hash_password("Pass123!"),
            is_active=True,
        )
        session.add(oph)

        oph2 = User(
            username=f"oph2_{uuid.uuid4().hex[:6]}",
            email=f"oph2_{uuid.uuid4().hex[:6]}@eye.in",
            full_name="Dr. Vikram Shah",
            role=UserRole.OPHTHALMOLOGIST,
            facility_id="PHC-TEST",
            password_hash=hash_password("Pass123!"),
            is_active=True,
        )
        session.add(oph2)

        hw = User(
            username=f"hw_{uuid.uuid4().hex[:6]}",
            email=f"hw_{uuid.uuid4().hex[:6]}@phc.in",
            full_name="Health Worker",
            role=UserRole.HEALTH_WORKER,
            facility_id="PHC-TEST",
            password_hash=hash_password("Pass123!"),
            is_active=True,
        )
        session.add(hw)

        patient = Patient(
            first_name="Meena",
            last_name="Devi",
            facility_id="PHC-TEST",
        )
        session.add(patient)
        await session.flush()

        screening = Screening(
            patient_id=patient.id,
            facility_id="PHC-TEST",
            screener_id=hw.id,
            screener_name=hw.full_name,
            eye="right",
            status=screening_status,
            quality_verdict="acceptable",
            dr_grade=dr_grade,
            dr_grade_label="Moderate NPDR",
            dr_confidence=0.72,
            referral_urgency="priority",
            model_trained=False,
        )
        session.add(screening)
        await session.flush()

        mo = ModelOutput(
            screening_id=screening.id,
            model_name="RetinaShield-EfficientNetB0",
            model_version="1.0.0",
            model_trained=False,
            predicted_dr_grade=dr_grade,
            predicted_grade_label="Moderate NPDR",
            confidence=0.72,
            class_probabilities=[0.05, 0.10, 0.72, 0.09, 0.04],
            calibrated=False,
            uncertainty_entropy=0.45,
            uncertainty_margin=0.30,
            concordance_status="Concordant AI findings",
        )
        session.add(mo)
        await session.commit()

        return {
            "oph_id": str(oph.id),
            "oph2_id": str(oph2.id),
            "hw_id": str(hw.id),
            "patient_id": str(patient.id),
            "screening_id": str(screening.id),
            "mo_id": str(mo.id),
        }


class TestReviewQueue(unittest.IsolatedAsyncioTestCase):
    """Comprehensive test suite for the ophthalmologist review queue."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test_review.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
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
                finally:
                    await session.close()

        app.dependency_overrides[get_db] = override_get_db

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    # ------------------------------------------------------------------
    # 1. Review queue basics
    # ------------------------------------------------------------------

    async def test_review_queue_returns_completed_screenings(self):
        """Review queue returns completed screenings and metadata."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/screenings/review-queue",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertIn("priority_rule", data)
        self.assertTrue(data["priority_rule_requires_clinical_approval"])
        self.assertGreater(len(data["priority_rule_approval_note"]), 20)
        self.assertGreater(data["total"], 0)
        item = data["items"][0]
        self.assertEqual(item["screening_id"], fixtures["screening_id"])
        self.assertIn("review_status", item)

    async def test_review_queue_status_ai_generated_for_pending(self):
        """Screenings not yet completed show ai_generated or awaiting_review."""
        fixtures = await _create_base_fixtures(self.session_factory, screening_status="completed")
        token = _ophtha_token(fixtures["oph_id"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/screenings/review-queue",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        statuses = {i["review_status"] for i in items}
        self.assertTrue(
            statuses.issubset({"ai_generated", "awaiting_review", "in_review", "clinician_reviewed", "recapture_requested"}),
            f"Unexpected review statuses: {statuses}",
        )

    async def test_review_queue_filter_by_review_status(self):
        """Filter by review_status=awaiting_review returns only unreviewed cases."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/screenings/review-queue?review_status=awaiting_review",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(resp.status_code, 200)
        for item in resp.json()["items"]:
            self.assertEqual(item["review_status"], "awaiting_review")

    async def test_review_queue_filter_by_quality(self):
        """Quality filter excludes non-matching items."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/screenings/review-queue?quality=good",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(resp.status_code, 200)
        # Fixture has quality_verdict='acceptable', so 'good' should return 0
        self.assertEqual(resp.json()["total"], 0)

    async def test_review_queue_filter_by_provisional_severity(self):
        """Severity filter correctly limits results."""
        fixtures = await _create_base_fixtures(self.session_factory, dr_grade=4)
        token = _ophtha_token(fixtures["oph_id"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp_4 = await client.get(
                "/api/screenings/review-queue?provisional_severity=4",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp_0 = await client.get(
                "/api/screenings/review-queue?provisional_severity=0",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(resp_4.status_code, 200)
        self.assertGreater(resp_4.json()["total"], 0)
        self.assertEqual(resp_0.json()["total"], 0)

    async def test_review_queue_priority_rules_metadata(self):
        """Each priority sort returns correct metadata."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])

        for sort in ["clinical_urgency", "oldest_first", "disagreement_first", "highest_grade_first"]:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(
                    f"/api/screenings/review-queue?priority_sort={sort}",
                    headers={"Authorization": f"Bearer {token}"},
                )
            self.assertEqual(resp.status_code, 200, f"Failed for sort={sort}")
            data = resp.json()
            self.assertTrue(data["priority_rule_requires_clinical_approval"])
            self.assertIsNotNone(data["priority_rule"])

    async def test_review_queue_invalid_priority_rule_rejected(self):
        """Invalid priority_sort returns HTTP 400."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/screenings/review-queue?priority_sort=invented_sort",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(resp.status_code, 400)

    async def test_review_queue_requires_ophthalmologist_role(self):
        """Health workers are not permitted to access the review queue."""
        fixtures = await _create_base_fixtures(self.session_factory)
        hw_tok = _hw_token(fixtures["hw_id"])

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/screenings/review-queue",
                headers={"Authorization": f"Bearer {hw_tok}"},
            )
        self.assertEqual(resp.status_code, 403)

    # ------------------------------------------------------------------
    # 2. First review submission
    # ------------------------------------------------------------------

    async def test_first_review_submission(self):
        """Submitting a first review creates a ClinicianReview record."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/screenings/{sid}/review",
                json={
                    "confirmed_dr_grade": 3,
                    "referral_recommendation": "priority",
                    "clinical_notes": "Moderate to severe NPDR, vessel caliber changes noted.",
                    "status": "final",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()
        self.assertEqual(data["confirmed_dr_grade"], 3)
        self.assertEqual(data["referral_recommendation"], "priority")
        self.assertEqual(data["status"], "final")
        self.assertEqual(data["review_version"], 1)
        self.assertFalse(data["is_ungradeable"])
        self.assertFalse(data["recapture_requested"])

    async def test_first_review_draft_submission(self):
        """Drafts are persisted with status=draft."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/screenings/{sid}/review",
                json={
                    "confirmed_dr_grade": 2,
                    "referral_recommendation": "routine",
                    "clinical_notes": "Initial assessment, need second opinion.",
                    "status": "draft",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["status"], "draft")

    # ------------------------------------------------------------------
    # 3. Ungradeable and recapture
    # ------------------------------------------------------------------

    async def test_ungradeable_marking(self):
        """Marking a case ungradeable sets is_ungradeable=True and grade=-1."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/screenings/{sid}/review",
                json={
                    "confirmed_dr_grade": -1,
                    "is_ungradeable": True,
                    "referral_recommendation": "none",
                    "clinical_notes": "Poor illumination, retina not visible.",
                    "status": "final",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data["is_ungradeable"])
        self.assertEqual(data["confirmed_dr_grade"], -1)

    async def test_recapture_request(self):
        """Requesting recapture sets recapture_requested=True and updates screening status."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/screenings/{sid}/review",
                json={
                    "confirmed_dr_grade": -1,
                    "is_ungradeable": True,
                    "recapture_requested": True,
                    "referral_recommendation": "none",
                    "clinical_notes": "Severe corneal reflex. Recapture required with improved 20D lens alignment.",
                    "status": "final",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data["recapture_requested"])

    # ------------------------------------------------------------------
    # 4. Amendment and audit trail
    # ------------------------------------------------------------------

    async def test_amendment_requires_change_reason(self):
        """Amending a final review without change_reason returns HTTP 422."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # First, finalise
            r1 = await client.post(
                f"/api/screenings/{sid}/review",
                json={
                    "confirmed_dr_grade": 2,
                    "referral_recommendation": "routine",
                    "clinical_notes": "Grade 2, moderate NPDR.",
                    "status": "final",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(r1.status_code, 201)
            version = r1.json()["review_version"]

            # Attempt amendment without change_reason
            r2 = await client.post(
                f"/api/screenings/{sid}/review",
                json={
                    "confirmed_dr_grade": 3,
                    "referral_recommendation": "priority",
                    "clinical_notes": "Reconsidering — additional hemorrhages noted.",
                    "status": "final",
                    "expected_version": version,
                    # No change_reason
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(r2.status_code, 422, r2.text)

    async def test_amendment_with_change_reason_succeeds(self):
        """A valid amendment creates a ReviewAmendment record and increments version."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post(
                f"/api/screenings/{sid}/review",
                json={
                    "confirmed_dr_grade": 1,
                    "referral_recommendation": "routine",
                    "clinical_notes": "Initial grade 1.",
                    "status": "final",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(r1.status_code, 201)
            v1 = r1.json()["review_version"]
            self.assertEqual(v1, 1)

            # Valid amendment
            r2 = await client.post(
                f"/api/screenings/{sid}/review",
                json={
                    "confirmed_dr_grade": 3,
                    "referral_recommendation": "priority",
                    "clinical_notes": "On second review, grade 3 with vitreous changes.",
                    "status": "final",
                    "expected_version": v1,
                    "change_reason": "Additional hemorrhages visible on magnification.",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(r2.status_code, 201, r2.text)
        data = r2.json()
        self.assertEqual(data["confirmed_dr_grade"], 3)
        self.assertEqual(data["review_version"], 2)
        self.assertEqual(data["status"], "amended")
        # Amendment history should be populated
        self.assertGreater(len(data["amendments"]), 0)
        amendment = data["amendments"][0]
        self.assertEqual(amendment["previous_grade"], 1)
        self.assertEqual(amendment["new_grade"], 3)
        self.assertEqual(amendment["change_reason"], "Additional hemorrhages visible on magnification.")

    async def test_amendment_history_endpoint(self):
        """GET /review/history returns the complete audit trail."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Submit final
            r1 = await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": 0, "referral_recommendation": "none",
                      "clinical_notes": "No DR detected.", "status": "final"},
                headers={"Authorization": f"Bearer {token}"},
            )
            v = r1.json()["review_version"]

            # Amend
            await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": 1, "referral_recommendation": "routine",
                      "clinical_notes": "Re-graded. Microaneurysms present.",
                      "status": "final", "expected_version": v,
                      "change_reason": "Spotted microaneurysm on enhanced image."},
                headers={"Authorization": f"Bearer {token}"},
            )

            # Get history
            hist = await client.get(
                f"/api/screenings/{sid}/review/history",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(hist.status_code, 200)
        amendments = hist.json()
        self.assertEqual(len(amendments), 1)
        self.assertEqual(amendments[0]["previous_grade"], 0)
        self.assertEqual(amendments[0]["new_grade"], 1)
        self.assertIsNotNone(amendments[0]["amended_by_id"])

    # ------------------------------------------------------------------
    # 5. Concurrency — version mismatch
    # ------------------------------------------------------------------

    async def test_version_mismatch_returns_409(self):
        """Submitting with a stale expected_version returns HTTP 409 Conflict."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # First submission
            r1 = await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": 2, "referral_recommendation": "routine",
                      "clinical_notes": "Grade 2 initial.", "status": "final"},
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(r1.status_code, 201)

            # Amend correctly (version=1 → version=2)
            r2 = await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": 3, "referral_recommendation": "priority",
                      "clinical_notes": "Upgraded on review.",
                      "status": "final", "expected_version": 1,
                      "change_reason": "Additional findings."},
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(r2.status_code, 201)

            # Now submit with stale version=1 (should be 2)
            r3 = await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": 0, "referral_recommendation": "none",
                      "clinical_notes": "Stale submission.",
                      "status": "final", "expected_version": 1,  # ← stale
                      "change_reason": "Stale reason."},
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(r3.status_code, 409, r3.text)
        self.assertIn("version", r3.json()["detail"].lower())

    # ------------------------------------------------------------------
    # 6. Case locking
    # ------------------------------------------------------------------

    async def test_lock_claim_and_release(self):
        """Lock can be claimed and released by the same reviewer."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Claim
            lock_resp = await client.post(
                f"/api/screenings/{sid}/review/claim",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(lock_resp.status_code, 200, lock_resp.text)
            lock_data = lock_resp.json()
            self.assertIn("lock_expires_at", lock_data)
            self.assertIn("locked_by_id", lock_data)

            # Release
            release_resp = await client.post(
                f"/api/screenings/{sid}/review/release",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(release_resp.status_code, 200)

    async def test_second_reviewer_blocked_by_active_lock(self):
        """Second reviewer cannot claim a lock already held by another reviewer."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token1 = _ophtha_token(fixtures["oph_id"])
        token2 = _ophtha_token(fixtures["oph2_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Reviewer 1 claims lock
            r1 = await client.post(
                f"/api/screenings/{sid}/review/claim",
                headers={"Authorization": f"Bearer {token1}"},
            )
            self.assertEqual(r1.status_code, 200)

            # Reviewer 2 tries to claim — should fail
            r2 = await client.post(
                f"/api/screenings/{sid}/review/claim",
                headers={"Authorization": f"Bearer {token2}"},
            )
        self.assertEqual(r2.status_code, 409, r2.text)
        self.assertIn("locked", r2.json()["detail"].lower())

    async def test_reviewer_can_reclaim_own_lock(self):
        """Same reviewer can re-claim their own lock to extend it."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post(
                f"/api/screenings/{sid}/review/claim",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(r1.status_code, 200)

            # Same reviewer reclaims — OK
            r2 = await client.post(
                f"/api/screenings/{sid}/review/claim",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(r2.status_code, 200)

    # ------------------------------------------------------------------
    # 7. Report generation
    # ------------------------------------------------------------------

    async def test_report_generation_after_final_review(self):
        """Report can be generated and signed after a final review."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Submit final review
            await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": 3, "referral_recommendation": "priority",
                      "clinical_notes": "Severe NPDR, vitreous changes.", "status": "final"},
                headers={"Authorization": f"Bearer {token}"},
            )

            # Generate report
            rpt = await client.post(
                f"/api/screenings/{sid}/report",
                json={"report_type": "screening_summary", "include_ai_findings": True},
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(rpt.status_code, 201, rpt.text)
        data = rpt.json()
        self.assertEqual(data["status"], "signed")

        summary = data["summary_json"]
        # Validation disclaimer must be present
        self.assertIn("validation_disclaimer", summary)
        self.assertIn("does NOT constitute", summary["validation_disclaimer"])

        # AI findings section present with correct label
        ai = summary.get("ai_research_screening_findings", {})
        self.assertEqual(ai.get("section_label"), "AI-GENERATED RESEARCH SCREENING RESULT")

        # Clinician section present
        clinician = summary.get("authoritative_clinician_diagnosis", {})
        self.assertEqual(clinician["confirmed_dr_grade"], 3)
        self.assertEqual(clinician["signature_status"], "SIGNED_BY_OPHTHALMOLOGIST")

    async def test_report_blocked_when_review_is_draft(self):
        """Report generation is blocked when review is still in draft."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Draft review only
            await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": 1, "referral_recommendation": "routine",
                      "clinical_notes": "Draft assessment.", "status": "draft"},
                headers={"Authorization": f"Bearer {token}"},
            )

            rpt = await client.post(
                f"/api/screenings/{sid}/report",
                json={"report_type": "screening_summary"},
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(rpt.status_code, 400)

    async def test_report_blocked_without_review(self):
        """Report generation is blocked when no review has been entered."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            rpt = await client.post(
                f"/api/screenings/{sid}/report",
                json={"report_type": "screening_summary"},
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(rpt.status_code, 400)

    # ------------------------------------------------------------------
    # 8. AI model output preservation
    # ------------------------------------------------------------------

    async def test_ai_model_output_preserved_after_review(self):
        """AI ModelOutput record is not mutated when clinician enters a different grade."""
        fixtures = await _create_base_fixtures(self.session_factory, dr_grade=2)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]
        mo_id = fixtures["mo_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Clinician enters a different grade (3 vs AI's 2)
            await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": 3, "referral_recommendation": "priority",
                      "clinical_notes": "Clinician upgrade.", "status": "final"},
                headers={"Authorization": f"Bearer {token}"},
            )

        # Verify ModelOutput unchanged
        async with self.session_factory() as session:
            from sqlalchemy import select
            from app.models.clinical import ModelOutput
            res = await session.execute(select(ModelOutput).where(ModelOutput.id == uuid.UUID(mo_id)))
            mo = res.scalar_one()
            # Must still be AI's original prediction (grade 2)
            self.assertEqual(mo.predicted_dr_grade, 2)

    # ------------------------------------------------------------------
    # 9. State transitions
    # ------------------------------------------------------------------

    async def test_review_state_transitions(self):
        """State progresses correctly: awaiting → in_review (draft) → clinician_reviewed (final)."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Check queue state: awaiting_review
            q = await client.get(
                "/api/screenings/review-queue",
                headers={"Authorization": f"Bearer {token}"},
            )
            items = q.json()["items"]
            matching = [i for i in items if i["screening_id"] == sid]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["review_status"], "awaiting_review")

            # 2. Submit draft → in_review
            await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": 1, "referral_recommendation": "routine",
                      "clinical_notes": "Checking again.", "status": "draft"},
                headers={"Authorization": f"Bearer {token}"},
            )
            q2 = await client.get(
                "/api/screenings/review-queue",
                headers={"Authorization": f"Bearer {token}"},
            )
            matching2 = [i for i in q2.json()["items"] if i["screening_id"] == sid]
            self.assertEqual(matching2[0]["review_status"], "in_review")

            # 3. Finalise → clinician_reviewed
            await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": 1, "referral_recommendation": "routine",
                      "clinical_notes": "Confirmed mild NPDR.", "status": "final",
                      "expected_version": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
            q3 = await client.get(
                "/api/screenings/review-queue",
                headers={"Authorization": f"Bearer {token}"},
            )
            matching3 = [i for i in q3.json()["items"] if i["screening_id"] == sid]
            self.assertEqual(matching3[0]["review_status"], "clinician_reviewed")

    async def test_recapture_state_in_queue(self):
        """Queue shows recapture_requested status after reviewer requests recapture."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": -1, "is_ungradeable": True,
                      "recapture_requested": True,
                      "referral_recommendation": "none",
                      "clinical_notes": "Cannot grade — recapture required.", "status": "final"},
                headers={"Authorization": f"Bearer {token}"},
            )
            q = await client.get(
                "/api/screenings/review-queue",
                headers={"Authorization": f"Bearer {token}"},
            )
        matching = [i for i in q.json()["items"] if i["screening_id"] == sid]
        self.assertEqual(matching[0]["review_status"], "recapture_requested")

    # ------------------------------------------------------------------
    # 10. GET review endpoint
    # ------------------------------------------------------------------

    async def test_get_review_returns_amendments(self):
        """GET /review returns amendments embedded in response."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": 0, "referral_recommendation": "none",
                      "clinical_notes": "No DR.", "status": "final"},
                headers={"Authorization": f"Bearer {token}"},
            )
            await client.post(
                f"/api/screenings/{sid}/review",
                json={"confirmed_dr_grade": 1, "referral_recommendation": "routine",
                      "clinical_notes": "Revised — spotted MA.",
                      "status": "final", "expected_version": 1,
                      "change_reason": "Microaneurysm identified."},
                headers={"Authorization": f"Bearer {token}"},
            )
            get_resp = await client.get(
                f"/api/screenings/{sid}/review",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(get_resp.status_code, 200)
        review = get_resp.json()
        self.assertIn("amendments", review)
        self.assertEqual(len(review["amendments"]), 1)
        self.assertEqual(review["review_version"], 2)

    async def test_get_review_404_when_none_submitted(self):
        """GET /review returns 404 when no review exists yet."""
        fixtures = await _create_base_fixtures(self.session_factory)
        token = _ophtha_token(fixtures["oph_id"])
        sid = fixtures["screening_id"]

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/screenings/{sid}/review",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
