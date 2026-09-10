"""
RetinaShield — Data Retention & DPDP Erasure Service

Manages data lifecycle policies:
1. Statutory retention enforcement (e.g. 7-year retention period for clinical screening records in India).
2. Soft deletion for standard operational removals.
3. DPDP Act 2023 Right-to-Erasure execution upon valid consent withdrawal.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.patient import Patient
from app.models.screening import Screening, ScreeningImage
from app.models.consent import ConsentRecord
from app.models.audit import AuditEvent
from app.services.image_store import image_store

logger = logging.getLogger(__name__)


class RetentionService:
    """Service to enforce statutory retention, soft-deletion, and DPDP erasure."""

    def __init__(self, statutory_years: int | None = None) -> None:
        self.statutory_years = statutory_years or settings.retention_statutory_years

    async def soft_delete_patient(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        reason: str = "Administrative request",
    ) -> bool:
        """Soft delete a patient record and its associated screenings."""
        p_res = await db.execute(select(Patient).where(Patient.id == patient_id))
        patient = p_res.scalar_one_or_none()
        if not patient:
            return False

        now = datetime.now(timezone.utc)
        patient.is_deleted = True
        patient.deleted_at = now
        patient.deletion_reason = reason

        # Cascade soft-delete to active screenings
        s_res = await db.execute(
            select(Screening).where(Screening.patient_id == patient_id, Screening.is_deleted == False)
        )
        screenings = s_res.scalars().all()
        for s in screenings:
            s.is_deleted = True
            s.deleted_at = now

        await db.flush()
        logger.info(f"Soft-deleted patient {patient_id} and {len(screenings)} screenings (reason: {reason})")
        return True

    async def execute_dpdp_right_to_erasure(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        requested_by_user_id: uuid.UUID,
        reason: str = "Consent withdrawal & DPDP right-to-erasure",
    ) -> dict[str, Any]:
        """
        Hard delete patient PII, images, and clinical records upon valid consent withdrawal.
        Maintains an anonymized tombstone audit entry for statutory compliance.
        """
        p_res = await db.execute(select(Patient).where(Patient.id == patient_id))
        patient = p_res.scalar_one_or_none()
        if not patient:
            raise ValueError(f"Patient {patient_id} not found")

        # Gather all image files to physically delete from storage
        s_res = await db.execute(select(Screening).where(Screening.patient_id == patient_id))
        screenings = s_res.scalars().all()
        screening_ids = [s.id for s in screenings]

        deleted_images_count = 0
        if screening_ids:
            img_res = await db.execute(
                select(ScreeningImage).where(ScreeningImage.screening_id.in_(screening_ids))
            )
            images = img_res.scalars().all()
            for img in images:
                await image_store.delete_image(img.stored_filename)
                deleted_images_count += 1

        # Delete database patient record (cascades to screenings, consents, etc.)
        await db.delete(patient)
        await db.flush()

        # Record immutable anonymized audit tombstone
        audit = AuditEvent(
            user_id=requested_by_user_id,
            facility_id=patient.facility_id,
            event_type="dpdp_erasure_executed",
            resource_type="patient",
            resource_id=str(patient_id),
            details={
                "reason": reason,
                "deleted_images_count": deleted_images_count,
                "deleted_screenings_count": len(screening_ids),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        db.add(audit)
        await db.flush()

        logger.info(
            f"DPDP Right-to-Erasure executed for patient {patient_id}: "
            f"{deleted_images_count} images purged from private storage."
        )

        return {
            "patient_id": str(patient_id),
            "status": "purged",
            "deleted_images_count": deleted_images_count,
            "deleted_screenings_count": len(screening_ids),
        }

    async def get_retention_audit_summary(self, db: AsyncSession) -> dict[str, Any]:
        """Summary of active vs soft-deleted records for retention monitoring."""
        total_patients = (await db.execute(select(Patient))).scalars().all()
        soft_deleted_patients = [p for p in total_patients if p.is_deleted]

        total_screenings = (await db.execute(select(Screening))).scalars().all()
        soft_deleted_screenings = [s for s in total_screenings if s.is_deleted]

        return {
            "statutory_retention_years": self.statutory_years,
            "total_patients": len(total_patients),
            "active_patients": len(total_patients) - len(soft_deleted_patients),
            "soft_deleted_patients": len(soft_deleted_patients),
            "total_screenings": len(total_screenings),
            "active_screenings": len(total_screenings) - len(soft_deleted_screenings),
            "soft_deleted_screenings": len(soft_deleted_screenings),
        }


# Singleton
retention_service = RetentionService()
