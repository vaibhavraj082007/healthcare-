"""
RetinaShield — Operational Monitoring Service

Computes system performance metrics, review queue backlogs, pipeline latency,
processing and synchronization failures, model-version usage, and distribution shifts
using actual stored database records.

Enforces:
1. Privacy-preserving small-cell suppression (k < 5) to protect rural patient identities.
2. Strict architectural boundary between operational metrics and clinical model accuracy.
3. Explicit regulatory prohibition on automated retraining from unverified model outputs.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.screening import Screening
from app.models.clinical import QualityResult, ModelOutput, ClinicianReview
from app.models.job import AnalysisJob
from app.models.sync import SyncConflict, ChunkedUploadSession
from app.schemas.monitoring import (
    OperationalMetricsResponse,
    ScreeningVolumeMetrics,
    UngradeableRateMetrics,
    ReviewBacklogMetrics,
    ProcessingFailureMetrics,
    SynchronizationFailureMetrics,
    LatencyMetrics,
    ModelVersionUsage,
    AggregationCell,
    ShiftMonitoringResponse,
    QualityShiftMetric,
)


class MonitoringService:
    """Service for computing operational and data shift metrics from persisted database entities."""

    def __init__(self, suppression_threshold: int | None = None):
        self.suppression_threshold = (
            suppression_threshold
            if suppression_threshold is not None
            else settings.monitoring_small_cell_threshold
        )

    @staticmethod
    def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
        """Ensures a datetime object is timezone-aware in UTC."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _suppress_cell(self, category: str, count: int) -> AggregationCell:
        """Applies k-anonymity small-cell suppression to prevent patient re-identification."""
        if count < self.suppression_threshold:
            return AggregationCell(
                category=category,
                count=None,
                display_count=f"<{self.suppression_threshold}",
                is_suppressed=True,
            )
        return AggregationCell(
            category=category,
            count=count,
            display_count=str(count),
            is_suppressed=False,
        )

    async def get_operational_metrics(
        self,
        session: AsyncSession,
        facility_id: Optional[str] = None,
        time_window_days: int = 30,
    ) -> OperationalMetricsResponse:
        """
        Computes all operational health, backlog, latency, and throughput metrics.
        """
        now = datetime.now(timezone.utc)
        since_30d = now - timedelta(days=time_window_days)
        since_7d = now - timedelta(days=7)
        since_24h = now - timedelta(hours=24)

        # -------------------------------------------------------------------
        # 1. Screening Volume Metrics
        # -------------------------------------------------------------------
        base_query = select(Screening).where(Screening.is_deleted.is_(False))
        if facility_id:
            base_query = base_query.where(Screening.facility_id == facility_id)

        all_screenings_res = await session.execute(base_query)
        screenings = all_screenings_res.scalars().all()

        total_screenings = len(screenings)
        last_24h = sum(1 for s in screenings if s.created_at and self._to_utc(s.created_at) >= since_24h)
        last_7d = sum(1 for s in screenings if s.created_at and self._to_utc(s.created_at) >= since_7d)
        last_30d = sum(1 for s in screenings if s.created_at and self._to_utc(s.created_at) >= since_30d)

        # Daily trend for last 7 days with privacy suppression
        daily_counts: Dict[str, int] = {}
        for day_offset in range(6, -1, -1):
            date_key = (now - timedelta(days=day_offset)).strftime("%Y-%m-%d")
            daily_counts[date_key] = 0

        for s in screenings:
            if s.created_at and self._to_utc(s.created_at) >= since_7d:
                date_str = self._to_utc(s.created_at).strftime("%Y-%m-%d")
                if date_str in daily_counts:
                    daily_counts[date_str] += 1

        daily_trend = [
            self._suppress_cell(date_key, count)
            for date_key, count in sorted(daily_counts.items())
        ]

        # By facility with privacy suppression
        facility_counts: Dict[str, int] = {}
        for s in screenings:
            fac = s.facility_id or "Unknown / Unassigned"
            facility_counts[fac] = facility_counts.get(fac, 0) + 1

        by_facility = [
            self._suppress_cell(fac, count)
            for fac, count in sorted(facility_counts.items(), key=lambda x: x[1], reverse=True)
        ]

        volume_metrics = ScreeningVolumeMetrics(
            total_screenings=total_screenings,
            last_24h=last_24h,
            last_7d=last_7d,
            last_30d=last_30d,
            daily_trend=daily_trend,
            by_facility=by_facility,
        )

        # -------------------------------------------------------------------
        # 2. Ungradeable Rate Metrics
        # -------------------------------------------------------------------
        q_query = select(QualityResult)
        if facility_id:
            # Join with screening to filter by facility
            q_query = q_query.join(Screening, QualityResult.screening_id == Screening.id).where(
                Screening.facility_id == facility_id
            )
        q_res = await session.execute(q_query)
        quality_results = q_res.scalars().all()

        total_evaluated = len(quality_results)
        ai_ungradeable = sum(1 for q in quality_results if q.ungradeable)
        
        verdict_counts: Dict[str, int] = {}
        failure_reasons_counts: Dict[str, int] = {}
        for q in quality_results:
            verdict = (q.verdict or "unknown").lower()
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            if q.failure_reasons:
                for reason in q.failure_reasons:
                    cleaned_reason = str(reason).lower().replace(" ", "_")
                    failure_reasons_counts[cleaned_reason] = (
                        failure_reasons_counts.get(cleaned_reason, 0) + 1
                    )

        # Clinician reviews ungradeable
        cr_query = select(ClinicianReview)
        if facility_id:
            cr_query = cr_query.join(Screening, ClinicianReview.screening_id == Screening.id).where(
                Screening.facility_id == facility_id
            )
        cr_res = await session.execute(cr_query)
        clinician_reviews = cr_res.scalars().all()

        clinician_ungradeable = sum(
            1 for r in clinician_reviews
            if r.is_ungradeable or r.confirmed_dr_grade == -1
        )

        overall_ungradeable_count = max(ai_ungradeable, clinician_ungradeable)
        ungradeable_rate_pct = (
            round((overall_ungradeable_count / total_evaluated * 100), 2)
            if total_evaluated > 0 else 0.0
        )
        ai_ungradeable_pct = (
            round((ai_ungradeable / total_evaluated * 100), 2)
            if total_evaluated > 0 else 0.0
        )
        clinician_ungradeable_pct = (
            round((clinician_ungradeable / len(clinician_reviews) * 100), 2)
            if clinician_reviews else 0.0
        )

        ungradeable_metrics = UngradeableRateMetrics(
            total_screenings_evaluated=total_evaluated,
            total_ungradeable_count=overall_ungradeable_count,
            ungradeable_rate_pct=ungradeable_rate_pct,
            ai_ungradeable_count=ai_ungradeable,
            ai_ungradeable_pct=ai_ungradeable_pct,
            clinician_ungradeable_count=clinician_ungradeable,
            clinician_ungradeable_pct=clinician_ungradeable_pct,
            quality_verdict_breakdown=verdict_counts,
            failure_reasons_breakdown=failure_reasons_counts,
        )

        # -------------------------------------------------------------------
        # 3. Review Backlog Metrics
        # -------------------------------------------------------------------
        # Backlog = completed AI screenings that do not have a finalized clinician review
        reviewed_screening_ids = {
            r.screening_id for r in clinician_reviews if r.status != "draft"
        }
        draft_screening_ids = {
            r.screening_id for r in clinician_reviews if r.status == "draft"
        }

        backlog_screenings = [
            s for s in screenings
            if s.status == "completed" and s.id not in reviewed_screening_ids
        ]

        awaiting_count = sum(1 for s in backlog_screenings if s.id not in draft_screening_ids)
        draft_count = sum(1 for s in backlog_screenings if s.id in draft_screening_ids)
        total_backlog = len(backlog_screenings)

        age_dist = {"under_24h": 0, "between_24_72h": 0, "over_72h": 0}
        urgency_dist = {"none": 0, "routine": 0, "priority": 0, "urgent": 0}
        oldest_pending_hours: Optional[float] = None

        for s in backlog_screenings:
            created = s.created_at or now
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_hours = (now - created).total_seconds() / 3600.0

            if oldest_pending_hours is None or age_hours > oldest_pending_hours:
                oldest_pending_hours = round(age_hours, 1)

            if age_hours < 24:
                age_dist["under_24h"] += 1
            elif age_hours <= 72:
                age_dist["between_24_72h"] += 1
            else:
                age_dist["over_72h"] += 1

            urg = (s.referral_urgency or "routine").lower()
            if urg in urgency_dist:
                urgency_dist[urg] += 1
            else:
                urgency_dist["routine"] += 1

        backlog_metrics = ReviewBacklogMetrics(
            total_backlog=total_backlog,
            awaiting_review_count=awaiting_count,
            draft_review_count=draft_count,
            age_distribution=age_dist,
            urgency_distribution=urgency_dist,
            oldest_pending_hours=oldest_pending_hours,
        )

        # -------------------------------------------------------------------
        # 4. Processing Failure Metrics
        # -------------------------------------------------------------------
        job_query = select(AnalysisJob)
        if facility_id:
            job_query = job_query.where(AnalysisJob.facility_id == facility_id)
        job_res = await session.execute(job_query)
        jobs = job_res.scalars().all()

        total_jobs = len(jobs)
        completed_jobs = sum(1 for j in jobs if j.status == "completed")
        failed_jobs = sum(1 for j in jobs if j.status == "failed")
        failure_rate_pct = (
            round((failed_jobs / total_jobs * 100), 2)
            if total_jobs > 0 else 0.0
        )

        failure_categories: Dict[str, int] = {}
        recent_failures: List[Dict[str, Any]] = []

        for j in jobs:
            if j.status == "failed":
                err = (j.error_message or "Unknown failure").lower()
                category = "other"
                if "timeout" in err:
                    category = "timeout_exceeded"
                elif "memory" in err or "oom" in err:
                    category = "memory_limit"
                elif "matlab" in err or "mcr" in err:
                    category = "matlab_runtime_error"
                elif "corrupt" in err or "header" in err or "invalid image" in err:
                    category = "invalid_image_format"
                elif "permission" in err or "access" in err:
                    category = "permission_denied"

                failure_categories[category] = failure_categories.get(category, 0) + 1

                if len(recent_failures) < 5:
                    recent_failures.append({
                        "job_id": str(j.id),
                        "facility_id": j.facility_id,
                        "error_message": j.error_message[:200] if j.error_message else "No message provided",
                        "failed_at": j.completed_at.isoformat() if j.completed_at else None,
                    })

        processing_failures = ProcessingFailureMetrics(
            total_jobs=total_jobs,
            completed_jobs=completed_jobs,
            failed_jobs=failed_jobs,
            failure_rate_pct=failure_rate_pct,
            failure_categories=failure_categories,
            recent_failures=recent_failures,
        )

        # -------------------------------------------------------------------
        # 5. Synchronization Failure Metrics
        # -------------------------------------------------------------------
        total_synced = sum(1 for s in screenings if s.synced)
        pending_sync = sum(1 for s in screenings if not s.synced)

        sync_conflict_query = select(SyncConflict)
        if facility_id:
            sync_conflict_query = sync_conflict_query.where(SyncConflict.facility_id == facility_id)
        conflict_res = await session.execute(sync_conflict_query)
        conflicts = conflict_res.scalars().all()

        sync_conflicts_total = len(conflicts)
        sync_conflicts_unresolved = sum(1 for c in conflicts if c.resolved_at is None)

        conflict_breakdown: Dict[str, int] = {}
        for c in conflicts:
            ctype = c.conflict_type or "unknown"
            conflict_breakdown[ctype] = conflict_breakdown.get(ctype, 0) + 1

        chunk_session_query = select(ChunkedUploadSession).where(
            ChunkedUploadSession.completed_at.is_(None)
        )
        if facility_id:
            chunk_session_query = chunk_session_query.where(ChunkedUploadSession.facility_id == facility_id)
        chunk_res = await session.execute(chunk_session_query)
        incomplete_chunks = len(chunk_res.scalars().all())

        sync_metrics = SynchronizationFailureMetrics(
            total_synced_screenings=total_synced,
            pending_sync_screenings=pending_sync,
            sync_conflicts_total=sync_conflicts_total,
            sync_conflicts_unresolved=sync_conflicts_unresolved,
            incomplete_chunk_sessions=incomplete_chunks,
            conflict_type_breakdown=conflict_breakdown,
        )

        # -------------------------------------------------------------------
        # 6. Latency Metrics
        # -------------------------------------------------------------------
        latencies: List[float] = []
        stage_timings: Dict[str, List[float]] = {
            "fov_segmentation": [],
            "quality_assessment": [],
            "feature_extraction": [],
            "dr_inference": [],
            "lesion_detection": [],
        }

        for j in jobs:
            if j.status == "completed" and j.started_at and j.completed_at:
                dur = (j.completed_at - j.started_at).total_seconds()
                if dur > 0:
                    latencies.append(dur)

            if j.timings and isinstance(j.timings, dict):
                for stage, val in j.timings.items():
                    if isinstance(val, (int, float)) and val > 0:
                        stage_clean = stage.lower().replace(" ", "_")
                        if stage_clean not in stage_timings:
                            stage_timings[stage_clean] = []
                        stage_timings[stage_clean].append(float(val))

        total_measured = len(latencies)
        mean_sec = round(statistics.mean(latencies), 2) if latencies else None
        median_sec = round(statistics.median(latencies), 2) if latencies else None
        min_sec = round(min(latencies), 2) if latencies else None
        max_sec = round(max(latencies), 2) if latencies else None

        p95_sec: Optional[float] = None
        if total_measured >= 2:
            sorted_lat = sorted(latencies)
            idx = int(round(0.95 * (total_measured - 1)))
            p95_sec = round(sorted_lat[idx], 2)
        elif total_measured == 1:
            p95_sec = max_sec

        stage_breakdown_mean: Dict[str, float] = {}
        for st, vals in stage_timings.items():
            if vals:
                stage_breakdown_mean[st] = round(statistics.mean(vals), 2)

        latency_metrics = LatencyMetrics(
            total_measured_jobs=total_measured,
            mean_seconds=mean_sec,
            median_seconds=median_sec,
            p95_seconds=p95_sec,
            min_seconds=min_sec,
            max_seconds=max_sec,
            stage_breakdown_mean_seconds=stage_breakdown_mean,
        )

        # -------------------------------------------------------------------
        # 7. Model Version Usage Metrics
        # -------------------------------------------------------------------
        mo_query = select(ModelOutput)
        if facility_id:
            mo_query = mo_query.join(Screening, ModelOutput.screening_id == Screening.id).where(
                Screening.facility_id == facility_id
            )
        mo_res = await session.execute(mo_query)
        model_outputs = mo_res.scalars().all()

        total_model_runs = len(model_outputs)
        model_agg: Dict[tuple[str, str, bool], int] = {}
        for m in model_outputs:
            key = (m.model_name or "Unknown Model", m.model_version or "1.0.0", m.model_trained)
            model_agg[key] = model_agg.get(key, 0) + 1

        model_version_usage: List[ModelVersionUsage] = []
        for (m_name, m_ver, m_trained), count in sorted(model_agg.items(), key=lambda x: x[1], reverse=True):
            pct = round((count / total_model_runs * 100), 2) if total_model_runs > 0 else 0.0
            model_version_usage.append(
                ModelVersionUsage(
                    model_name=m_name,
                    model_version=m_ver,
                    runs_count=count,
                    percentage=pct,
                    model_trained=m_trained,
                )
            )

        return OperationalMetricsResponse(
            generated_at=now,
            facility_id_filter=facility_id,
            time_window_days=time_window_days,
            privacy_suppression_threshold=self.suppression_threshold,
            screening_volume=volume_metrics,
            ungradeable_rates=ungradeable_metrics,
            review_backlog=backlog_metrics,
            processing_failures=processing_failures,
            synchronization_failures=sync_metrics,
            latency=latency_metrics,
            model_version_usage=model_version_usage,
        )

    async def get_shift_metrics(
        self,
        session: AsyncSession,
        current_days: int = 7,
        baseline_days: int = 30,
        facility_id: Optional[str] = None,
    ) -> ShiftMonitoringResponse:
        """
        Monitors shifts in input image quality assessment distributions and
        predicted DR severity distributions across two temporal cohorts.
        """
        now = datetime.now(timezone.utc)
        current_cutoff = now - timedelta(days=current_days)
        baseline_cutoff = now - timedelta(days=baseline_days)

        # 1. Fetch Quality Results
        q_query = select(QualityResult)
        if facility_id:
            q_query = q_query.join(Screening, QualityResult.screening_id == Screening.id).where(
                Screening.facility_id == facility_id
            )
        q_res = await session.execute(q_query)
        all_qualities = q_res.scalars().all()

        baseline_q: List[QualityResult] = []
        current_q: List[QualityResult] = []

        for q in all_qualities:
            created = q.created_at or now
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)

            if created >= current_cutoff:
                current_q.append(q)
            elif created >= baseline_cutoff:
                baseline_q.append(q)

        # Compare Quality Metrics
        quality_attrs = [
            ("overall_quality_score", "Overall Quality Score"),
            ("sharpness", "Sharpness Metric"),
            ("contrast", "Contrast Metric"),
            ("illumination_uniformity", "Illumination Uniformity"),
            ("blur_score", "Blur Score (Variance of Laplacian)"),
            ("valid_retina_percentage", "Valid FOV Retina Percentage"),
        ]

        shift_metrics: List[QualityShiftMetric] = []
        for attr, label in quality_attrs:
            b_vals = [getattr(q, attr) for q in baseline_q if getattr(q, attr) is not None]
            c_vals = [getattr(q, attr) for q in current_q if getattr(q, attr) is not None]

            b_mean = round(statistics.mean(b_vals), 3) if b_vals else None
            b_std = round(statistics.stdev(b_vals), 3) if len(b_vals) >= 2 else (0.0 if b_vals else None)
            c_mean = round(statistics.mean(c_vals), 3) if c_vals else None
            c_std = round(statistics.stdev(c_vals), 3) if len(c_vals) >= 2 else (0.0 if c_vals else None)

            delta = round(c_mean - b_mean, 3) if (c_mean is not None and b_mean is not None) else None
            shift_flag = False
            if delta is not None and b_std and b_std > 0:
                shift_flag = abs(delta) > (1.5 * b_std)

            shift_metrics.append(
                QualityShiftMetric(
                    metric_name=label,
                    baseline_mean=b_mean,
                    baseline_std=b_std,
                    current_mean=c_mean,
                    current_std=c_std,
                    delta_mean=delta,
                    shift_flag=shift_flag,
                )
            )

        # Verdict distributions
        def get_verdict_dist(cohort: List[QualityResult]) -> Dict[str, float]:
            if not cohort:
                return {}
            total = len(cohort)
            counts: Dict[str, int] = {}
            for item in cohort:
                v = (item.verdict or "unknown").lower()
                counts[v] = counts.get(v, 0) + 1
            return {k: round(v / total * 100, 1) for k, v in counts.items()}

        verdict_shift = {
            "baseline": get_verdict_dist(baseline_q),
            "current": get_verdict_dist(current_q),
        }

        ungradeable_shift = {
            "baseline_pct": (
                round(sum(1 for q in baseline_q if q.ungradeable) / len(baseline_q) * 100, 2)
                if baseline_q else 0.0
            ),
            "current_pct": (
                round(sum(1 for q in current_q if q.ungradeable) / len(current_q) * 100, 2)
                if current_q else 0.0
            ),
        }

        # 2. Fetch Model Outputs
        mo_query = select(ModelOutput)
        if facility_id:
            mo_query = mo_query.join(Screening, ModelOutput.screening_id == Screening.id).where(
                Screening.facility_id == facility_id
            )
        mo_res = await session.execute(mo_query)
        all_mo = mo_res.scalars().all()

        baseline_mo: List[ModelOutput] = []
        current_mo: List[ModelOutput] = []

        for m in all_mo:
            created = m.created_at or now
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)

            if created >= current_cutoff:
                current_mo.append(m)
            elif created >= baseline_cutoff:
                baseline_mo.append(m)

        def get_grade_dist(cohort: List[ModelOutput]) -> Dict[str, float]:
            if not cohort:
                return {}
            total = len(cohort)
            grade_names = {
                0: "Grade 0 (No DR)",
                1: "Grade 1 (Mild)",
                2: "Grade 2 (Moderate)",
                3: "Grade 3 (Severe)",
                4: "Grade 4 (PDR)",
            }
            counts = {name: 0 for name in grade_names.values()}
            counts["Ungradeable / Unclassified"] = 0

            for item in cohort:
                g = item.predicted_dr_grade
                if g in grade_names:
                    counts[grade_names[g]] += 1
                else:
                    counts["Ungradeable / Unclassified"] += 1

            return {k: round(v / total * 100, 1) for k, v in counts.items()}

        grade_shift = {
            "baseline": get_grade_dist(baseline_mo),
            "current": get_grade_dist(current_mo),
        }

        b_confs = [m.confidence for m in baseline_mo if m.confidence is not None]
        c_confs = [m.confidence for m in current_mo if m.confidence is not None]
        conf_shift = {
            "baseline": round(statistics.mean(b_confs), 3) if b_confs else None,
            "current": round(statistics.mean(c_confs), 3) if c_confs else None,
        }

        b_ents = [m.uncertainty_entropy for m in baseline_mo if m.uncertainty_entropy is not None]
        c_ents = [m.uncertainty_entropy for m in current_mo if m.uncertainty_entropy is not None]
        ent_shift = {
            "baseline": round(statistics.mean(b_ents), 3) if b_ents else None,
            "current": round(statistics.mean(c_ents), 3) if c_ents else None,
        }

        return ShiftMonitoringResponse(
            generated_at=now,
            current_window_days=current_days,
            baseline_window_days=baseline_days,
            current_sample_size=len(current_q),
            baseline_sample_size=len(baseline_q),
            small_cell_suppression_applied=(
                len(current_q) < self.suppression_threshold
                or len(baseline_q) < self.suppression_threshold
            ),
            quality_shift_metrics=shift_metrics,
            quality_verdict_shift=verdict_shift,
            ungradeable_rate_shift=ungradeable_shift,
            prediction_dr_grade_shift=grade_shift,
            confidence_shift=conf_shift,
            entropy_shift=ent_shift,
        )


monitoring_service = MonitoringService()
