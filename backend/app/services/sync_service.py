"""
RetinaShield — Sync Service

Handles synchronization between offline facility services and the central server.
Provides endpoints for:
  - Receiving batched screening results from facilities
  - Tracking sync status per facility
  - Conflict resolution for concurrent edits
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.screening import Screening
from app.models.facility import Facility

logger = logging.getLogger(__name__)


class SyncService:
    """Central server sync service for offline facility data."""

    async def receive_sync_batch(
        self, db: AsyncSession, facility_id: str, screenings_data: list[dict]
    ) -> dict:
        """
        Receive a batch of screening results from an offline facility.

        Each screening in the batch is upserted (insert or update).
        Returns a summary of what was processed.
        """
        created = 0
        updated = 0
        errors = []

        for item in screenings_data:
            try:
                screening_id = UUID(item["id"])

                # Check if screening already exists
                result = await db.execute(
                    select(Screening).where(Screening.id == screening_id)
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # Update existing record
                    for key, value in item.items():
                        if key != "id" and hasattr(existing, key):
                            setattr(existing, key, value)
                    existing.synced = True
                    existing.synced_at = datetime.now(timezone.utc)
                    updated += 1
                else:
                    # Insert new record
                    screening = Screening(
                        id=screening_id,
                        synced=True,
                        synced_at=datetime.now(timezone.utc),
                        **{k: v for k, v in item.items() if k != "id"},
                    )
                    db.add(screening)
                    created += 1

            except Exception as e:
                errors.append({"id": item.get("id"), "error": str(e)})
                logger.error(f"Sync error for screening {item.get('id')}: {e}")

        # Update facility sync status
        await db.execute(
            update(Facility)
            .where(Facility.facility_code == facility_id)
            .values(
                last_sync_at=datetime.now(timezone.utc),
                pending_sync_count=0,
            )
        )

        await db.commit()

        summary = {
            "facility_id": facility_id,
            "total_received": len(screenings_data),
            "created": created,
            "updated": updated,
            "errors": errors,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"Sync from {facility_id}: "
            f"{created} created, {updated} updated, {len(errors)} errors"
        )
        return summary

    async def get_facility_sync_status(
        self, db: AsyncSession, facility_id: str
    ) -> dict:
        """Get sync status for a facility."""
        result = await db.execute(
            select(Facility).where(Facility.facility_code == facility_id)
        )
        facility = result.scalar_one_or_none()

        if not facility:
            return {"facility_id": facility_id, "status": "not_found"}

        # Count unsynced screenings
        unsynced_result = await db.execute(
            select(Screening)
            .where(Screening.facility_id == facility_id)
            .where(Screening.synced == False)  # noqa: E712
        )
        unsynced_count = len(unsynced_result.scalars().all())

        return {
            "facility_id": facility_id,
            "facility_name": facility.name,
            "last_sync_at": facility.last_sync_at.isoformat() if facility.last_sync_at else None,
            "pending_sync_count": unsynced_count,
            "is_active": facility.is_active,
        }


# Singleton
sync_service = SyncService()
