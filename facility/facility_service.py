"""
RetinaShield — Facility Offline Processing Service

Daemon that runs at rural health centres to:
  1. Manage the offline capture queue (CAPTURE_ONLY mode)
  2. Run local MATLAB/MCR/Python-fallback inference (OFFLINE_FULL mode)
  3. Forward to central server inference (ONLINE_REMOTE mode)
  4. Sync completed results to the central server when online

Operation modes (set via OPERATION_MODE env var):
    CAPTURE_ONLY  — Record + store encrypted images; defer inference.
    OFFLINE_FULL  — Run MATLAB / MCR / Python-fallback inference locally.
    ONLINE_REMOTE — Pass images to central server inference jobs.

NOTE: A cached web page alone does NOT provide offline MATLAB inference.
    This daemon must be running on the facility computer for mode OFFLINE_FULL
    to function.  The web UI displays a clear banner when the daemon is absent.

Usage:
    python -m facility.facility_service
    OPERATION_MODE=OFFLINE_FULL python -m facility.facility_service
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from facility.config import facility_config
from facility.queue import offline_queue
from facility.sync_client import sync_client

logging.basicConfig(
    level=getattr(logging, facility_config.log_level, logging.INFO),
    format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("facility_service")


class FacilityService:
    """
    Offline processing daemon for rural health centres.

    Three explicit operation modes are supported — the active mode is logged
    prominently at startup and must be verified by facility IT before patient
    data is captured.
    """

    def __init__(self) -> None:
        self._running = False
        self._cfg = facility_config
        self._mode = self._cfg.operation_mode
        self._sync_interval = self._cfg.sync_interval_seconds

    # ── Processing loop ───────────────────────────────────────────────────────

    async def process_queue(self) -> int:
        """
        Dispatch pending queue items according to the current operation mode.
        Returns the number of items processed.
        """
        if self._mode == "CAPTURE_ONLY":
            return 0  # Inference is intentionally deferred

        pending = offline_queue.get_pending(limit=self._cfg.max_concurrent_inference_jobs)
        if not pending:
            return 0

        if self._mode == "ONLINE_REMOTE":
            return await self._forward_to_remote(pending)

        # OFFLINE_FULL
        return await self._run_local_inference(pending)

    async def _run_local_inference(self, items: list[dict]) -> int:
        """Run MATLAB / MCR / Python-fallback inference locally."""
        from facility.inference_worker import inference_worker

        processed = 0
        for item in items:
            offline_queue.update_status(item["id"], "processing")
            logger.info(
                "Local inference: encounter=%s eye=%s capability=%s",
                item["local_encounter_id"],
                item["eye"],
                inference_worker.capability,
            )
            success = await inference_worker.process_one(item)
            if success:
                processed += 1

        return processed

    async def _forward_to_remote(self, items: list[dict]) -> int:
        """
        Forward raw captures to central server inference (ONLINE_REMOTE mode).
        The image is uploaded now; inference runs on the server.
        """
        forwarded = 0
        for item in items:
            offline_queue.update_status(item["id"], "processing")
            try:
                result = await sync_client._upload_image(item, sync_client._auth_headers())
                if result:
                    # Mark completed with a placeholder result; server will fill analysis
                    offline_queue.update_status(
                        item["id"],
                        "completed",
                        analysis_result={"mode": "remote_inference_pending"},
                    )
                    forwarded += 1
                else:
                    offline_queue.record_retry_failure(
                        item["id"], "Remote image upload failed"
                    )
            except Exception as exc:
                logger.error("Remote forward failed for %s: %s", item["id"], exc)
                offline_queue.record_retry_failure(item["id"], str(exc))

        return forwarded

    # ── Sync loop ─────────────────────────────────────────────────────────────

    async def sync_loop(self) -> None:
        """Periodically drain outbox and prune old synced records."""
        while self._running:
            try:
                result = await sync_client.sync_completed_screenings()
                if result["synced"] > 0:
                    logger.info(
                        "Sync: %d synced, %d conflicts, %d errors",
                        result["synced"],
                        result["conflicts"],
                        result["errors"],
                    )
                if result.get("conflicts", 0) > 0:
                    logger.warning(
                        "%d sync conflicts require human resolution. "
                        "Visit /sync on the dashboard to review.",
                        result["conflicts"],
                    )
                offline_queue.prune_old_synced()
            except Exception as exc:
                logger.error("Sync loop error: %s", exc)

            await asyncio.sleep(self._sync_interval)

    async def processing_loop(self) -> None:
        """Continuously monitor and process the queue."""
        while self._running:
            try:
                count = await self.process_queue()
                if count > 0:
                    logger.info("Processed %d encounters this cycle.", count)
            except Exception as exc:
                logger.error("Processing loop error: %s", exc)
            await asyncio.sleep(5)

    # ── Startup ───────────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        self._print_banner()
        stats = offline_queue.get_stats()
        logger.info("Queue state: %s", stats)

        try:
            await asyncio.gather(
                self.processing_loop(),
                self.sync_loop(),
            )
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Shutdown requested.")
            self._running = False
        except Exception as exc:
            logger.critical("Fatal service error: %s", exc)
            self._running = False

    def stop(self) -> None:
        self._running = False

    def _print_banner(self) -> None:
        from facility.inference_worker import inference_worker

        lines = [
            "=" * 65,
            " RetinaShield Facility Offline Service",
            f" Facility : {self._cfg.facility_name}",
            f" ID       : {self._cfg.facility_id}",
            f" Mode     : {self._mode}",
            f" Inference: {inference_worker.capability}",
            f" Sync URL : {self._cfg.sync_server_url}",
            " RESEARCH SCREENING TOOL — Not approved for autonomous diagnosis",
            "=" * 65,
        ]

        if self._mode == "CAPTURE_ONLY":
            lines.insert(-1, " ⚠ CAPTURE_ONLY — local inference disabled")
        elif inference_worker.capability == "python_fallback":
            lines.insert(
                -1,
                " ⚠ Python fallback active — MATLAB grades unavailable",
            )

        if not self._cfg.db_encryption_key:
            lines.insert(-1, " ⚠ DB ENCRYPTION DISABLED — dev mode only!")

        for line in lines:
            logger.info(line)


def main() -> None:
    service = FacilityService()
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        service.stop()
        logger.info("Facility service stopped.")


if __name__ == "__main__":
    main()
