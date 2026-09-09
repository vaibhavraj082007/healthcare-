"""
RetinaShield — Facility Offline Processing Service

Daemon that runs at rural health centres to:
  1. Monitor the offline queue for new screening requests
  2. Process fundus images through the MATLAB pipeline (or Python fallback)
  3. Store results locally in SQLite
  4. Periodically sync results to the central server when online

Usage:
    python facility_service.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path so we can import backend services
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from facility.config import facility_config
from facility.queue import offline_queue
from facility.sync_client import sync_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("facility_service")


class FacilityService:
    """
    Offline processing daemon for rural health centres.

    Processes screening requests from the local queue and syncs results
    to the central server when connectivity is available.
    """

    def __init__(self) -> None:
        self._running = False
        self._sync_interval = facility_config.sync_interval_seconds

    async def process_queue(self) -> int:
        """Process pending items in the offline queue. Returns count processed."""
        pending = offline_queue.get_pending(limit=5)
        if not pending:
            return 0

        processed = 0
        for item in pending:
            try:
                # Mark as processing
                offline_queue.update_status(item["id"], "processing")

                logger.info(
                    f"Processing screening {item['id']} "
                    f"for patient {item['patient_id']}"
                )

                # Import the MATLAB bridge for processing
                from app.services.matlab_bridge import matlab_bridge

                # Create output directory
                output_dir = str(
                    facility_config.image_dir / "analysis" / item["id"]
                )

                # Run the pipeline
                result = await matlab_bridge.run_pipeline(
                    item["image_path"], output_dir
                )

                # Store result
                offline_queue.update_status(
                    item["id"],
                    "completed",
                    analysis_result=result.model_dump(mode="json"),
                )

                processed += 1
                logger.info(f"Completed screening {item['id']}")

            except Exception as e:
                logger.error(f"Failed to process {item['id']}: {e}")
                offline_queue.update_status(
                    item["id"], "failed", error_message=str(e)
                )

        return processed

    async def sync_loop(self) -> None:
        """Periodically attempt to sync completed screenings."""
        while self._running:
            try:
                result = await sync_client.sync_completed_screenings()
                if result["status"] == "synced":
                    logger.info(f"Synced {result['synced']} screenings")
                elif result["status"] == "offline":
                    logger.debug("Server offline, will retry later")
            except Exception as e:
                logger.error(f"Sync error: {e}")

            await asyncio.sleep(self._sync_interval)

    async def processing_loop(self) -> None:
        """Continuously monitor and process the queue."""
        while self._running:
            try:
                processed = await self.process_queue()
                if processed > 0:
                    logger.info(f"Processed {processed} screenings this cycle")
            except Exception as e:
                logger.error(f"Processing error: {e}")

            # Wait before checking again
            await asyncio.sleep(5)

    async def run(self) -> None:
        """Start the facility service."""
        self._running = True

        logger.info("=" * 60)
        logger.info(f" RetinaShield Facility Service")
        logger.info(f" Facility: {facility_config.facility_name}")
        logger.info(f" ID: {facility_config.facility_id}")
        logger.info(f" MATLAB mode: {facility_config.matlab_mode}")
        logger.info(f" RESEARCH SCREENING — Not for clinical diagnosis")
        logger.info("=" * 60)

        # Print queue stats
        stats = offline_queue.get_stats()
        logger.info(f"Queue stats: {stats}")

        # Run processing and sync concurrently
        try:
            await asyncio.gather(
                self.processing_loop(),
                self.sync_loop(),
            )
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self._running = False
        except Exception as e:
            logger.error(f"Service error: {e}")
            self._running = False

    def stop(self) -> None:
        """Stop the service gracefully."""
        self._running = False


def main() -> None:
    """Entry point for the facility service."""
    service = FacilityService()
    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        service.stop()
        logger.info("Facility service stopped.")


if __name__ == "__main__":
    main()
