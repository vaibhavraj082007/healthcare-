"""
RetinaShield — Facility Sync Client

Synchronizes locally-processed screening results with the central server
when internet connectivity is available.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx

from facility.config import facility_config
from facility.queue import offline_queue

logger = logging.getLogger(__name__)


class SyncClient:
    """Client that syncs local offline data to the central RetinaShield server."""

    def __init__(self) -> None:
        self._server_url = facility_config.sync_server_url
        self._facility_id = facility_config.facility_id

    async def check_connectivity(self) -> bool:
        """Check if the central server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._server_url}/health")
                return response.status_code == 200
        except Exception:
            return False

    async def sync_completed_screenings(self) -> dict:
        """
        Upload all completed-but-unsynced screenings to the central server.

        Returns sync summary.
        """
        # Check connectivity first
        if not await self.check_connectivity():
            logger.info("Central server not reachable. Sync deferred.")
            return {"status": "offline", "synced": 0}

        # Get unsynced items
        unsynced = offline_queue.get_unsynced(limit=50)
        if not unsynced:
            logger.info("No unsynced screenings to upload.")
            return {"status": "up_to_date", "synced": 0}

        logger.info(f"Syncing {len(unsynced)} screenings to {self._server_url}")

        # Prepare batch payload
        payload = {
            "facility_id": self._facility_id,
            "screenings": unsynced,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._server_url}/api/sync/batch",
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()

            # Mark items as synced
            for item in unsynced:
                offline_queue.update_status(item["id"], "synced")

            logger.info(
                f"Sync complete: {result.get('created', 0)} created, "
                f"{result.get('updated', 0)} updated"
            )
            return {
                "status": "synced",
                "synced": len(unsynced),
                "server_response": result,
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Sync HTTP error: {e.response.status_code} — {e.response.text}")
            return {"status": "error", "error": str(e)}
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return {"status": "error", "error": str(e)}

    async def get_sync_status(self) -> dict:
        """Get current sync status including queue stats and server status."""
        queue_stats = offline_queue.get_stats()
        server_reachable = await self.check_connectivity()

        return {
            "facility_id": self._facility_id,
            "server_reachable": server_reachable,
            "server_url": self._server_url,
            "queue_stats": queue_stats,
            "last_check": datetime.now(timezone.utc).isoformat(),
        }


# Singleton
sync_client = SyncClient()
