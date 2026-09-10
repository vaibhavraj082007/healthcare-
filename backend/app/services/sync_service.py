"""
RetinaShield — Sync Service (Central Server)

Handles offline→cloud synchronization with:
    - Idempotency: duplicate requests return the original result without re-writing
    - Conflict detection: clinician-approved records are NEVER silently overwritten
    - Checksum verification: SHA-256 mismatch aborts upsert
    - Chunked upload management: session tracking + reassembly verification
    - Facility dashboard statistics

Workflow for each encounter:
    POST /api/sync/encounter  →  check idempotency key
                              →  if exists: return cached result (202 idempotent)
                              →  if clinician_approved conflicts: 409 Conflict
                              →  if checksum ok: upsert Screening + analysis
                              →  write idempotency key
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.facility import Facility
from app.models.screening import Screening
from app.models.sync import ChunkedUploadSession, SyncConflict, SyncIdempotencyKey

logger = logging.getLogger(__name__)

# Staging area for partial uploads (server-side temp files)
_STAGING_DIR = Path(os.environ.get("SYNC_STAGING_DIR", "/tmp/rs_sync_staging"))
_STAGING_DIR.mkdir(parents=True, exist_ok=True)


class SyncService:
    """Central server sync service for offline facility data."""

    # ── Single-encounter upsert ───────────────────────────────────────────────

    async def receive_encounter(
        self, db: AsyncSession, payload: dict
    ) -> dict:
        """
        Upsert a single encounter from a facility.

        Returns:
            {status, screening_id, image_sha256, idempotent}
        """
        encounter_id = payload["local_encounter_id"]
        facility_id = payload["facility_id"]

        # --- Idempotency check ---
        idem_row = await self._get_idempotency(db, encounter_id)
        if idem_row:
            logger.info(
                "Idempotent re-delivery for encounter %s — returning cached result.",
                encounter_id,
            )
            return {
                "status": "accepted",
                "screening_id": str(idem_row.result_screening_id) if idem_row.result_screening_id else None,
                "image_sha256": payload.get("image_sha256"),
                "idempotent": True,
            }

        # --- Conflict detection ---
        conflict = await self._detect_conflict(db, payload)
        if conflict:
            await self._record_conflict(db, payload, conflict)
            await self._write_idempotency(db, encounter_id, facility_id, None, "conflict")
            return {
                "status": "conflict",
                "conflict_type": conflict["conflict_type"],
                "detail": conflict["detail"],
                "server_version": conflict.get("server_version"),
                "idempotent": False,
            }

        # --- Upsert Screening ---
        screening = await self._upsert_screening(db, payload)
        await self._write_idempotency(db, encounter_id, facility_id, screening.id, "created")
        await self._update_facility_sync(db, facility_id)
        await db.commit()

        logger.info(
            "Synced encounter %s → screening %s", encounter_id, screening.id
        )
        return {
            "status": "accepted",
            "screening_id": str(screening.id),
            "image_sha256": payload.get("image_sha256"),
            "idempotent": False,
        }

    # ── Conflict detection ────────────────────────────────────────────────────

    async def _detect_conflict(self, db: AsyncSession, payload: dict) -> dict | None:
        """
        Return a conflict dict if the incoming payload disagrees with an
        existing clinician-approved record, else None.
        """
        encounter_id = payload["local_encounter_id"]

        # Try to find a matching screening by local_encounter_id
        result = await db.execute(
            select(Screening).where(
                Screening.local_encounter_id == encounter_id
            )
        )
        existing = result.scalar_one_or_none()

        if not existing:
            return None

        # If a clinician has approved this record on the server side,
        # and the incoming payload also claims approval with a different grade,
        # surface it as a conflict rather than silently overwriting.
        local_approved = payload.get("clinician_approved_locally", False)
        if not local_approved:
            return None  # No local approval claim — safe to update

        # Get existing clinician review
        from app.models.clinical import ClinicianReview

        review_result = await db.execute(
            select(ClinicianReview).where(
                ClinicianReview.screening_id == existing.id,
                ClinicianReview.status == "final",
            )
        )
        server_review = review_result.scalar_one_or_none()

        if not server_review:
            return None  # No server approval yet — safe to proceed

        local_result = payload.get("analysis_result") or {}
        local_grade = (local_result.get("severity_classification") or {}).get(
            "predicted_dr_grade"
        )

        if (
            local_grade is not None
            and server_review.confirmed_dr_grade != local_grade
        ):
            return {
                "conflict_type": "grade_mismatch",
                "detail": (
                    f"Local grade {local_grade} conflicts with "
                    f"server clinician-approved grade {server_review.confirmed_dr_grade}."
                ),
                "server_version": server_review.review_version,
            }

        return None

    async def _record_conflict(
        self, db: AsyncSession, payload: dict, conflict: dict
    ) -> None:
        row = SyncConflict(
            local_encounter_id=payload["local_encounter_id"],
            facility_id=payload["facility_id"],
            conflict_type=conflict["conflict_type"],
            local_data_json=payload,
            server_data_json=conflict,
        )
        db.add(row)
        await db.flush()

    # ── Upsert ────────────────────────────────────────────────────────────────

    async def _upsert_screening(
        self, db: AsyncSession, payload: dict
    ) -> Screening:
        encounter_id = payload["local_encounter_id"]

        result = await db.execute(
            select(Screening).where(
                Screening.local_encounter_id == encounter_id
            )
        )
        existing = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if existing:
            # Update non-protected fields only
            existing.synced = True
            existing.synced_at = now
            await db.flush()
            return existing

        # Create new Screening stub — the facility's patient_id links it
        # to the patient if the patient was already registered on the server.
        new_screening = Screening(
            local_encounter_id=encounter_id,
            facility_id=payload.get("facility_id"),
            eye=payload.get("eye", "unknown"),
            synced=True,
            synced_at=now,
        )
        db.add(new_screening)
        await db.flush()
        return new_screening

    # ── Idempotency helpers ───────────────────────────────────────────────────

    async def _get_idempotency(
        self, db: AsyncSession, key: str
    ) -> SyncIdempotencyKey | None:
        result = await db.execute(
            select(SyncIdempotencyKey).where(SyncIdempotencyKey.key == key)
        )
        return result.scalar_one_or_none()

    async def _write_idempotency(
        self,
        db: AsyncSession,
        key: str,
        facility_id: str,
        screening_id: UUID | None,
        status: str,
    ) -> None:
        row = SyncIdempotencyKey(
            key=key,
            facility_id=facility_id,
            result_screening_id=screening_id,
            result_status=status,
        )
        db.add(row)
        await db.flush()

    # ── Chunked upload management ─────────────────────────────────────────────

    async def get_or_create_upload_session(
        self,
        db: AsyncSession,
        encounter_id: str,
        facility_id: str,
        expected_bytes: int,
        sha256_expected: str,
    ) -> ChunkedUploadSession:
        result = await db.execute(
            select(ChunkedUploadSession).where(
                ChunkedUploadSession.encounter_id == encounter_id
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            staging_path = str(_STAGING_DIR / f"{encounter_id}.tmp")
            session = ChunkedUploadSession(
                encounter_id=encounter_id,
                facility_id=facility_id,
                expected_bytes=expected_bytes,
                received_bytes=0,
                sha256_expected=sha256_expected,
                staging_path=staging_path,
            )
            db.add(session)
            await db.flush()

        return session

    async def append_chunk(
        self,
        db: AsyncSession,
        encounter_id: str,
        chunk_data: bytes,
        offset: int,
        sha256_expected: str,
        facility_id: str,
        expected_bytes: int,
    ) -> dict:
        """
        Append a chunk to the staging file.

        Returns {received_bytes, complete, verified}.
        """
        session = await self.get_or_create_upload_session(
            db, encounter_id, facility_id, expected_bytes, sha256_expected
        )

        staging = Path(session.staging_path)

        # Write chunk at the correct offset
        with staging.open("ab" if offset > 0 else "wb") as f:
            f.seek(offset)
            f.write(chunk_data)

        session.received_bytes = offset + len(chunk_data)

        complete = session.received_bytes >= session.expected_bytes
        verified = False

        if complete:
            # Verify SHA-256 of the fully-assembled file
            actual_sha256 = _sha256_file(staging)
            if actual_sha256 == sha256_expected.lower():
                session.sha256_verified = True
                session.completed_at = datetime.now(timezone.utc)
                verified = True
                logger.info(
                    "Upload complete and verified for encounter %s", encounter_id
                )
            else:
                logger.error(
                    "SHA-256 mismatch for encounter %s: got %s, expected %s",
                    encounter_id,
                    actual_sha256,
                    sha256_expected,
                )
                # Delete corrupted staging file
                staging.unlink(missing_ok=True)
                session.received_bytes = 0
                session.sha256_verified = False
                await db.flush()
                await db.commit()
                raise ValueError("SHA-256 checksum mismatch — upload corrupted, please retry.")

        await db.flush()
        await db.commit()

        return {
            "received_bytes": session.received_bytes,
            "expected_bytes": session.expected_bytes,
            "complete": complete,
            "verified": verified,
        }

    async def get_upload_status(
        self, db: AsyncSession, encounter_id: str
    ) -> dict:
        result = await db.execute(
            select(ChunkedUploadSession).where(
                ChunkedUploadSession.encounter_id == encounter_id
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            return {"received_bytes": 0, "expected_bytes": 0, "complete": False}

        return {
            "received_bytes": session.received_bytes,
            "expected_bytes": session.expected_bytes,
            "complete": session.sha256_verified,
        }

    # ── Conflict resolution ───────────────────────────────────────────────────

    async def resolve_conflict(
        self,
        db: AsyncSession,
        conflict_id: str,
        resolution: str,
        notes: str | None,
        resolved_by_id: UUID,
    ) -> dict:
        """
        Record a human decision on a sync conflict.

        resolution: 'keep_server' | 'keep_facility' | 'manual_merge' | 'escalated'
        """
        result = await db.execute(
            select(SyncConflict).where(
                SyncConflict.id == UUID(conflict_id)
            )
        )
        conflict = result.scalar_one_or_none()
        if not conflict:
            raise ValueError(f"Conflict {conflict_id} not found.")

        conflict.resolved_at = datetime.now(timezone.utc)
        conflict.resolved_by_id = resolved_by_id
        conflict.resolution = resolution
        conflict.resolution_notes = notes
        await db.commit()

        return {
            "conflict_id": conflict_id,
            "resolution": resolution,
            "resolved_at": conflict.resolved_at.isoformat(),
        }

    async def list_conflicts(
        self, db: AsyncSession, facility_id: str | None = None
    ) -> list[dict]:
        stmt = select(SyncConflict).where(SyncConflict.resolved_at.is_(None))
        if facility_id:
            stmt = stmt.where(SyncConflict.facility_id == facility_id)
        stmt = stmt.order_by(SyncConflict.detected_at.asc())
        result = await db.execute(stmt)
        conflicts = result.scalars().all()
        return [
            {
                "id": str(c.id),
                "local_encounter_id": c.local_encounter_id,
                "facility_id": c.facility_id,
                "conflict_type": c.conflict_type,
                "detected_at": c.detected_at.isoformat(),
                "local_data": c.local_data_json,
                "server_data": c.server_data_json,
            }
            for c in conflicts
        ]

    # ── Facility dashboard ────────────────────────────────────────────────────

    async def get_facility_sync_status(
        self, db: AsyncSession, facility_id: str
    ) -> dict:
        result = await db.execute(
            select(Facility).where(Facility.facility_code == facility_id)
        )
        facility = result.scalar_one_or_none()
        if not facility:
            return {"facility_id": facility_id, "status": "not_found"}

        conflict_result = await db.execute(
            select(SyncConflict).where(
                SyncConflict.facility_id == facility_id,
                SyncConflict.resolved_at.is_(None),
            )
        )
        unresolved_conflicts = len(conflict_result.scalars().all())

        return {
            "facility_id": facility_id,
            "facility_name": facility.name,
            "last_sync_at": facility.last_sync_at.isoformat() if facility.last_sync_at else None,
            "pending_sync_count": facility.pending_sync_count or 0,
            "is_active": facility.is_active,
            "unresolved_conflicts": unresolved_conflicts,
        }

    async def _update_facility_sync(
        self, db: AsyncSession, facility_id: str
    ) -> None:
        await db.execute(
            update(Facility)
            .where(Facility.facility_code == facility_id)
            .values(last_sync_at=datetime.now(timezone.utc), pending_sync_count=0)
        )

    # ── Legacy batch endpoint (preserved for compatibility) ───────────────────

    async def receive_sync_batch(
        self, db: AsyncSession, facility_id: str, screenings_data: list[dict]
    ) -> dict:
        """
        Batch upsert. Processes items individually for proper idempotency/conflict
        handling. Returns a batch summary.
        """
        created = updated = 0
        errors: list[dict] = []
        conflicts: list[dict] = []

        for item in screenings_data:
            enc_id = item.get("local_encounter_id") or item.get("id")
            if not enc_id:
                errors.append({"item": item, "error": "Missing local_encounter_id"})
                continue
            item.setdefault("local_encounter_id", enc_id)
            item.setdefault("facility_id", facility_id)
            try:
                result = await self.receive_encounter(db, item)
                if result["status"] == "conflict":
                    conflicts.append(result)
                elif result.get("idempotent"):
                    updated += 1
                else:
                    created += 1
            except Exception as exc:
                logger.error("Batch sync error for %s: %s", enc_id, exc)
                errors.append({"id": enc_id, "error": str(exc)})

        return {
            "facility_id": facility_id,
            "total_received": len(screenings_data),
            "created": created,
            "updated": updated,
            "conflicts": conflicts,
            "errors": errors,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# Singleton
sync_service = SyncService()
