"""
RetinaShield — Facility Durable Sync Client

Uploads completed offline screenings to the central server with:
    - Stable `local_encounter_id` as idempotency key (X-Idempotency-Key header)
    - SHA-256 checksum verification on both sides
    - Chunked image upload with Content-Range and partial-upload resume
    - Exponential backoff with jitter
    - Conflict detection: server HTTP 409 → mark_conflict(), never overwrite
    - Duplicate prevention: server checks idempotency table before writing

No credentials, no patient data, and no images are passed through browser
storage or any code path accessible to the web frontend.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from facility.config import facility_config
from facility.queue import OfflineQueue, offline_queue
from facility.storage import secure_image_store

logger = logging.getLogger(__name__)

_CHUNK_SIZE = facility_config.upload_chunk_size_bytes


class SyncClient:
    """
    Pushes completed facility-side screenings to the central RetinaShield server.

    Modes:
        - check_connectivity()            — quick health probe
        - sync_completed_screenings()     — main outbox drain loop
        - resume_upload(item)             — resume a partially-uploaded image
        - get_sync_status()               — dashboard statistics
    """

    def __init__(self, queue: OfflineQueue | None = None) -> None:
        self._cfg = facility_config
        self._server_url = self._cfg.sync_server_url.rstrip("/")
        self._facility_id = self._cfg.facility_id
        self._queue = queue or offline_queue

    # ── Connectivity ──────────────────────────────────────────────────────────

    async def check_connectivity(self) -> bool:
        """Probe the central server health endpoint. Returns True if reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._server_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    # ── Main sync loop ────────────────────────────────────────────────────────

    async def sync_completed_screenings(self) -> dict:
        """
        Drain the outbox: upload every completed/syncing item and every failed
        item past its next_retry_at.

        Returns a summary dict for logging.
        """
        if not await self.check_connectivity():
            logger.debug("Central server not reachable; sync deferred.")
            return {"status": "offline", "synced": 0, "conflicts": 0, "errors": 0}

        # Collect items eligible for upload
        items = self._queue.get_unsynced(limit=50)
        retry_items = self._queue.get_for_retry(limit=20)
        all_items = {i["id"]: i for i in items + retry_items}.values()

        synced = conflicts = errors = 0

        for item in all_items:
            try:
                result = await self._upload_item(item)
                if result == "synced":
                    synced += 1
                elif result == "conflict":
                    conflicts += 1
                elif result == "error":
                    errors += 1
            except Exception as exc:
                logger.error("Unexpected error syncing %s: %s", item["id"], exc)
                self._queue.record_retry_failure(item["id"], str(exc))
                errors += 1

        return {
            "status": "completed",
            "synced": synced,
            "conflicts": conflicts,
            "errors": errors,
        }

    # ── Per-item upload ───────────────────────────────────────────────────────

    async def _upload_item(self, item: dict) -> str:
        """
        Upload a single queue item. Returns 'synced', 'conflict', or 'error'.

        Steps:
        1. If there's an image, upload it via chunked transfer.
        2. POST the encounter metadata (with image checksum).
        3. Mark synced or handle 409 conflict.
        """
        encounter_id = item["local_encounter_id"]
        logger.info("Syncing encounter %s …", encounter_id)

        headers = self._auth_headers()
        headers["X-Idempotency-Key"] = encounter_id
        headers["X-Facility-ID"] = self._facility_id

        # --- Step 1: Upload image (if any) ---
        if item.get("image_path") and item.get("image_sha256"):
            ok = await self._upload_image(item, headers)
            if not ok:
                return "error"

        # --- Step 2: POST encounter metadata ---
        payload = self._build_payload(item)
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self._server_url}/api/sync/encounter",
                    json=payload,
                    headers=headers,
                )

            if resp.status_code == 200:
                server_data = resp.json()
                # Verify server echo'd matching checksum
                if item.get("image_sha256") and server_data.get("image_sha256"):
                    if server_data["image_sha256"] != item["image_sha256"]:
                        logger.error(
                            "Checksum mismatch for %s — server echoed %s, expected %s",
                            encounter_id,
                            server_data.get("image_sha256"),
                            item["image_sha256"],
                        )
                        self._queue.record_retry_failure(
                            item["id"], "Checksum mismatch after sync"
                        )
                        return "error"

                self._queue.update_status(item["id"], "synced")
                logger.info("Synced encounter %s", encounter_id)
                return "synced"

            elif resp.status_code == 409:
                conflict_data = resp.json()
                logger.warning(
                    "Conflict for encounter %s: %s", encounter_id, conflict_data
                )
                self._queue.mark_conflict(item["id"], conflict_data)
                return "conflict"

            elif resp.status_code == 422:
                # Permanent failure — don't retry infinitely
                logger.error(
                    "Validation error for %s (422): %s", encounter_id, resp.text
                )
                self._queue.record_retry_failure(item["id"], f"422 Validation: {resp.text[:200]}")
                return "error"

            else:
                logger.warning(
                    "Unexpected %d for %s — will retry", resp.status_code, encounter_id
                )
                self._queue.record_retry_failure(
                    item["id"], f"HTTP {resp.status_code}"
                )
                return "error"

        except httpx.TimeoutException:
            self._queue.record_retry_failure(item["id"], "Timeout during metadata POST")
            return "error"
        except Exception as exc:
            self._queue.record_retry_failure(item["id"], str(exc))
            return "error"

    async def _upload_image(self, item: dict, headers: dict) -> bool:
        """
        Chunked image upload with partial-upload resume.

        Checks the server for how many bytes it already has (resume offset),
        then sends remaining chunks using Content-Range.
        Returns True on success, False on failure (failure is already recorded).
        """
        encounter_id = item["local_encounter_id"]
        rel_path = item["image_path"]
        expected_sha256 = item["image_sha256"]
        already_uploaded = item.get("upload_offset_bytes", 0)

        # Read and decrypt image into memory (never writes plaintext to disk)
        try:
            raw_bytes = secure_image_store.read_decrypt(rel_path)
        except Exception as exc:
            logger.error("Cannot decrypt image for %s: %s", encounter_id, exc)
            self._queue.record_retry_failure(item["id"], f"Image decrypt failed: {exc}")
            return False

        total_bytes = len(raw_bytes)

        # Check server for existing upload session (for resume)
        server_offset = await self._query_upload_offset(encounter_id, headers)
        if server_offset > already_uploaded:
            already_uploaded = server_offset
            self._queue.update_upload_offset(item["id"], already_uploaded)

        if already_uploaded >= total_bytes:
            logger.info("Image for %s already fully uploaded.", encounter_id)
            return True

        # Upload remaining chunks
        offset = already_uploaded
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                while offset < total_bytes:
                    chunk = raw_bytes[offset : offset + _CHUNK_SIZE]
                    chunk_end = offset + len(chunk) - 1

                    chunk_headers = dict(headers)
                    chunk_headers["Content-Range"] = (
                        f"bytes {offset}-{chunk_end}/{total_bytes}"
                    )
                    chunk_headers["X-Image-SHA256"] = expected_sha256
                    chunk_headers["Content-Type"] = "application/octet-stream"

                    resp = await client.patch(
                        f"{self._server_url}/api/sync/encounter/{encounter_id}/image-chunk",
                        content=chunk,
                        headers=chunk_headers,
                    )

                    if resp.status_code in (200, 206):
                        offset += len(chunk)
                        self._queue.update_upload_offset(item["id"], offset)
                        logger.debug(
                            "Uploaded %d/%d bytes for %s", offset, total_bytes, encounter_id
                        )
                    else:
                        logger.warning(
                            "Chunk upload failed %d for %s at offset %d",
                            resp.status_code,
                            encounter_id,
                            offset,
                        )
                        self._queue.record_retry_failure(
                            item["id"],
                            f"Chunk upload failed: HTTP {resp.status_code}",
                        )
                        return False

        except httpx.TimeoutException:
            self._queue.record_retry_failure(item["id"], "Timeout during image chunk upload")
            return False
        except Exception as exc:
            self._queue.record_retry_failure(item["id"], f"Chunk upload error: {exc}")
            return False

        logger.info("Image upload complete for %s (%d bytes)", encounter_id, total_bytes)
        return True

    async def _query_upload_offset(self, encounter_id: str, headers: dict) -> int:
        """Ask server how many bytes it already has. Returns 0 if unknown."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._server_url}/api/sync/encounter/{encounter_id}/upload-status",
                    headers=headers,
                )
            if resp.status_code == 200:
                data = resp.json()
                return int(data.get("received_bytes", 0))
        except Exception:
            pass
        return 0

    # ── Payload builder ───────────────────────────────────────────────────────

    def _build_payload(self, item: dict) -> dict:
        return {
            "local_encounter_id": item["local_encounter_id"],
            "patient_id": item["patient_id"],
            "facility_id": item["facility_id"],
            "eye": item["eye"],
            "image_sha256": item.get("image_sha256"),
            "analysis_result": item.get("analysis_result"),
            "consent_recorded": bool(item.get("consent_recorded", 0)),
            "clinician_approved_locally": bool(item.get("clinician_approved_locally", 0)),
            "created_at": item["created_at"],
            "processed_at": item.get("processed_at"),
        }

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _auth_headers(self) -> dict:
        token = self._cfg.sync_auth_token
        if token:
            return {"Authorization": f"Bearer {token}"}
        return {}

    # ── Status ────────────────────────────────────────────────────────────────

    async def get_sync_status(self) -> dict:
        queue_stats = self._queue.get_stats()
        server_reachable = await self.check_connectivity()
        return {
            "facility_id": self._facility_id,
            "server_reachable": server_reachable,
            "server_url": self._server_url,
            "queue_stats": queue_stats,
            "conflict_items": len(self._queue.get_conflict_items()),
            "last_check": datetime.now(timezone.utc).isoformat(),
        }


# Singleton
sync_client = SyncClient()
