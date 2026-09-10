"""
RetinaShield — Operational Monitoring Test Suite

Tests:
1. Operational metrics computation using actual stored entities (Screening, QualityResult, ClinicianReview, AnalysisJob, SyncConflict).
2. Small-cell privacy suppression (counts < 5 masked as '< 5' with is_suppressed=True).
3. Review backlog metrics (age distribution <24h/24-72h/>72h, urgency breakdown).
4. Processing failure tracking and categorization.
5. Synchronization failure tracking (conflicts, pending sync).
6. Execution latency calculations (mean, median, p95, stage breakdown).
7. Model version usage accounting.
8. Separation of operational metrics from clinical accuracy (explicit disclaimers).
9. Input quality & prediction distribution shift detection with regulatory prohibition on automated retraining.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db.session import Base
from app.models.user import User, UserRole
from app.models.facility import Facility
from app.models.patient import Patient
from app.models.screening import Screening
from app.models.clinical import QualityResult, ModelOutput, ClinicianReview
from app.models.job import AnalysisJob
from app.models.sync import SyncConflict, ChunkedUploadSession
from app.services.monitoring_service import MonitoringService
from app.core.security import hash_password


class TestOperationalMonitoring(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Create an isolated in-memory SQLite database
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.monitoring_service = MonitoringService(suppression_threshold=5)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_operational_metrics_with_small_cell_suppression(self):
        """Verify operational metrics compute correctly and suppress groups with count < 5."""
        now = datetime.now(timezone.utc)

        async with self.session_factory() as session:
            # Add facility
            fac1 = Facility(facility_code="PHC-RURAL-A", name="Rural PHC A")
            fac2 = Facility(facility_code="PHC-RURAL-B", name="Rural PHC B")
            session.add_all([fac1, fac2])

            # Add users
            doc = User(
                username="doc_raj",
                email="doc_raj@phc.in",
                full_name="Dr. Raj",
                role=UserRole.OPHTHALMOLOGIST,
                password_hash=hash_password("Pass123!"),
                is_active=True,
            )
            session.add(doc)
            await session.flush()

            # Create 6 patients for Facility A (count >= 5, should NOT be suppressed)
            patients_a = [
                Patient(first_name=f"PatientA_{i}", last_name="Sharma", facility_id="PHC-RURAL-A")
                for i in range(6)
            ]
            # Create 2 patients for Facility B (count < 5, MUST be suppressed)
            patients_b = [
                Patient(first_name=f"PatientB_{i}", last_name="Patel", facility_id="PHC-RURAL-B")
                for i in range(2)
            ]
            session.add_all(patients_a + patients_b)
            await session.flush()

            # Screenings for Facility A
            for i, p in enumerate(patients_a):
                s = Screening(
                    patient_id=p.id,
                    facility_id="PHC-RURAL-A",
                    eye="right",
                    status="completed",
                    dr_grade=i % 4,
                    referral_urgency="urgent" if i == 0 else "routine",
                    synced=True,
                    created_at=now - timedelta(hours=i * 5),
                )
                session.add(s)
                await session.flush()

                # Add Quality Result
                q = QualityResult(
                    image_id=uuid.uuid4(),
                    screening_id=s.id,
                    verdict="good" if i != 0 else "rejected",
                    ungradeable=(i == 0),
                    overall_quality_score=0.85 if i != 0 else 0.25,
                    sharpness=0.80,
                    contrast=0.75,
                    blur_score=150.0,
                    created_at=s.created_at,
                )
                session.add(q)

                # Add Model Output
                mo = ModelOutput(
                    screening_id=s.id,
                    model_name="RetinaShield-EfficientNetB0",
                    model_version="1.0.0",
                    model_trained=True,
                    predicted_dr_grade=i % 4,
                    confidence=0.88,
                    created_at=s.created_at,
                )
                session.add(mo)

                # Add Analysis Job with latency
                job = AnalysisJob(
                    screening_id=s.id,
                    facility_id="PHC-RURAL-A",
                    idempotency_key=f"job_key_{s.id}",
                    status="completed",
                    created_at=s.created_at,
                    started_at=s.created_at,
                    completed_at=s.created_at + timedelta(seconds=12 + i),
                    timings={"fov_segmentation": 2.5, "dr_inference": 8.0},
                )
                session.add(job)

            # Screenings for Facility B (only 2 records)
            for i, p in enumerate(patients_b):
                s = Screening(
                    patient_id=p.id,
                    facility_id="PHC-RURAL-B",
                    eye="left",
                    status="completed",
                    dr_grade=1,
                    referral_urgency="routine",
                    synced=False,
                    created_at=now - timedelta(hours=i * 2),
                )
                session.add(s)
                await session.flush()

                q = QualityResult(
                    image_id=uuid.uuid4(),
                    screening_id=s.id,
                    verdict="acceptable",
                    ungradeable=False,
                    overall_quality_score=0.70,
                    created_at=s.created_at,
                )
                session.add(q)

            # Add a processing failure job
            failed_job = AnalysisJob(
                screening_id=patients_b[0].id,
                facility_id="PHC-RURAL-B",
                idempotency_key="failed_job_key",
                status="failed",
                error_message="MatlabRuntimeError: Segmentation fault in MCR",
                created_at=now - timedelta(minutes=30),
                completed_at=now - timedelta(minutes=29),
            )
            session.add(failed_job)

            # Add a sync conflict
            conflict = SyncConflict(
                local_encounter_id="enc_001",
                facility_id="PHC-RURAL-B",
                conflict_type="grade_mismatch",
                detected_at=now,
            )
            session.add(conflict)

            await session.commit()

        # Compute Operational Metrics
        async with self.session_factory() as session:
            metrics = await self.monitoring_service.get_operational_metrics(session)

            # 1. Total volume
            self.assertEqual(metrics.screening_volume.total_screenings, 8)
            self.assertEqual(metrics.screening_volume.last_24h, 7)

            # 2. Check privacy suppression by facility
            fac_dict = {cell.category: cell for cell in metrics.screening_volume.by_facility}
            self.assertIn("PHC-RURAL-A", fac_dict)
            self.assertIn("PHC-RURAL-B", fac_dict)

            # Facility A has 6 >= 5 -> not suppressed
            self.assertFalse(fac_dict["PHC-RURAL-A"].is_suppressed)
            self.assertEqual(fac_dict["PHC-RURAL-A"].count, 6)
            self.assertEqual(fac_dict["PHC-RURAL-A"].display_count, "6")

            # Facility B has 2 < 5 -> suppressed to prevent re-identification
            self.assertTrue(fac_dict["PHC-RURAL-B"].is_suppressed)
            self.assertIsNone(fac_dict["PHC-RURAL-B"].count)
            self.assertEqual(fac_dict["PHC-RURAL-B"].display_count, "<5")

            # 3. Ungradeable rates
            self.assertEqual(metrics.ungradeable_rates.total_screenings_evaluated, 8)
            self.assertEqual(metrics.ungradeable_rates.ai_ungradeable_count, 1)
            self.assertAlmostEqual(metrics.ungradeable_rates.ungradeable_rate_pct, 12.5, places=1)

            # 4. Review Backlog (all 8 are completed and unreviewed)
            self.assertEqual(metrics.review_backlog.total_backlog, 8)
            self.assertEqual(metrics.review_backlog.awaiting_review_count, 8)
            self.assertEqual(metrics.review_backlog.draft_review_count, 0)
            self.assertGreater(metrics.review_backlog.age_distribution["under_24h"], 0)

            # 5. Processing failures
            self.assertEqual(metrics.processing_failures.failed_jobs, 1)
            self.assertIn("matlab_runtime_error", metrics.processing_failures.failure_categories)

            # 6. Sync failures
            self.assertEqual(metrics.synchronization_failures.pending_sync_screenings, 2)
            self.assertEqual(metrics.synchronization_failures.sync_conflicts_total, 1)
            self.assertEqual(metrics.synchronization_failures.sync_conflicts_unresolved, 1)

            # 7. Latency
            self.assertEqual(metrics.latency.total_measured_jobs, 6)
            self.assertIsNotNone(metrics.latency.mean_seconds)
            self.assertIn("fov_segmentation", metrics.latency.stage_breakdown_mean_seconds)

            # 8. Model version usage
            self.assertEqual(len(metrics.model_version_usage), 1)
            self.assertEqual(metrics.model_version_usage[0].model_name, "RetinaShield-EfficientNetB0")
            self.assertEqual(metrics.model_version_usage[0].model_version, "1.0.0")
            self.assertTrue(metrics.model_version_usage[0].model_trained)

            # 9. Separation from accuracy
            self.assertIn("ARCHITECTURAL & CLINICAL SEPARATION", metrics.clinical_accuracy_separation_disclaimer)
            self.assertIn("does NOT evaluate clinical model accuracy", metrics.clinical_accuracy_separation_disclaimer)

    async def test_review_backlog_with_clinician_reviews(self):
        """Verify backlog decreases when a clinician finalizes a review."""
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            p = Patient(first_name="Ramesh", last_name="Kumar", facility_id="PHC-RURAL-A")
            doc = User(
                username="doc_eye",
                email="doc_eye@phc.in",
                full_name="Dr. Eye",
                role=UserRole.OPHTHALMOLOGIST,
                password_hash=hash_password("Pass123!"),
                is_active=True,
            )
            session.add_all([p, doc])
            await session.flush()

            # Screening 1: Completed and reviewed
            s1 = Screening(
                patient_id=p.id,
                facility_id="PHC-RURAL-A",
                eye="right",
                status="completed",
                created_at=now - timedelta(hours=10),
            )
            # Screening 2: Completed and unreviewed
            s2 = Screening(
                patient_id=p.id,
                facility_id="PHC-RURAL-A",
                eye="left",
                status="completed",
                created_at=now - timedelta(hours=5),
            )
            session.add_all([s1, s2])
            await session.flush()

            rev1 = ClinicianReview(
                screening_id=s1.id,
                reviewer_id=doc.id,
                confirmed_dr_grade=2,
                clinical_notes="Confirmed moderate NPDR",
                status="final",
            )
            session.add(rev1)
            await session.commit()

        async with self.session_factory() as session:
            metrics = await self.monitoring_service.get_operational_metrics(session)
            # Only s2 is in backlog
            self.assertEqual(metrics.review_backlog.total_backlog, 1)
            self.assertEqual(metrics.review_backlog.awaiting_review_count, 1)

    async def test_shift_monitoring_and_regulatory_safeguards(self):
        """Verify distribution shifts computation and mandatory anti-retraining disclaimer."""
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session:
            p = Patient(first_name="TestPatient", last_name="Verma", facility_id="PHC-RURAL-A")
            session.add(p)
            await session.flush()

            # Historical baseline screening (15 days ago)
            s_base = Screening(
                patient_id=p.id,
                facility_id="PHC-RURAL-A",
                eye="right",
                status="completed",
                created_at=now - timedelta(days=15),
            )
            session.add(s_base)
            await session.flush()

            q_base = QualityResult(
                image_id=uuid.uuid4(),
                screening_id=s_base.id,
                verdict="good",
                ungradeable=False,
                overall_quality_score=0.90,
                sharpness=0.85,
                blur_score=200.0,
                created_at=s_base.created_at,
            )
            mo_base = ModelOutput(
                screening_id=s_base.id,
                predicted_dr_grade=0,
                confidence=0.95,
                uncertainty_entropy=0.10,
                created_at=s_base.created_at,
            )
            session.add_all([q_base, mo_base])

            # Current screening (2 days ago)
            s_curr = Screening(
                patient_id=p.id,
                facility_id="PHC-RURAL-A",
                eye="left",
                status="completed",
                created_at=now - timedelta(days=2),
            )
            session.add(s_curr)
            await session.flush()

            q_curr = QualityResult(
                image_id=uuid.uuid4(),
                screening_id=s_curr.id,
                verdict="acceptable",
                ungradeable=False,
                overall_quality_score=0.72,
                sharpness=0.65,
                blur_score=110.0,
                created_at=s_curr.created_at,
            )
            mo_curr = ModelOutput(
                screening_id=s_curr.id,
                predicted_dr_grade=2,
                confidence=0.75,
                uncertainty_entropy=0.45,
                created_at=s_curr.created_at,
            )
            session.add_all([q_curr, mo_curr])
            await session.commit()

        async with self.session_factory() as session:
            shifts = await self.monitoring_service.get_shift_metrics(
                session=session,
                current_days=7,
                baseline_days=30,
            )

            self.assertEqual(shifts.current_sample_size, 1)
            self.assertEqual(shifts.baseline_sample_size, 1)

            # Check regulatory safety notice
            self.assertIn("REGULATORY & CLINICAL SAFETY NOTICE", shifts.regulatory_safety_notice)
            self.assertIn("DO NOT prove clinical performance drift", shifts.regulatory_safety_notice)
            self.assertIn("AUTONOMOUS RETRAINING FROM UNVERIFIED AI OUTPUTS IS STRICTLY PROHIBITED", shifts.regulatory_safety_notice)
            self.assertIn("controlled offline evaluation protocol", shifts.regulatory_safety_notice)


if __name__ == "__main__":
    unittest.main()
