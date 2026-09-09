"""
RetinaShield — Facility Offline Queue

SQLite-based persistent queue for offline screening processing.
Stores screening requests and results locally until they can be synced
to the central server.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from facility.config import facility_config

logger = logging.getLogger(__name__)

QueueStatus = Literal["pending", "processing", "completed", "failed", "synced"]


class OfflineQueue:
    """SQLite-backed queue for offline screening data."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or str(facility_config.queue_db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Create the queue table if it doesn't exist."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS screening_queue (
                    id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL,
                    facility_id TEXT NOT NULL,
                    eye TEXT NOT NULL DEFAULT 'both',
                    image_path TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    analysis_result TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    processed_at TEXT,
                    synced_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_status
                ON screening_queue(status)
            """)
            conn.commit()
        logger.info(f"Offline queue initialized at: {self._db_path}")

    def enqueue(
        self,
        patient_id: str,
        image_path: str,
        eye: str = "both",
    ) -> str:
        """Add a screening to the offline queue. Returns the queue item ID."""
        item_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO screening_queue
                    (id, patient_id, facility_id, eye, image_path, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (item_id, patient_id, facility_config.facility_id, eye, image_path, now),
            )
            conn.commit()

        logger.info(f"Enqueued screening {item_id} for patient {patient_id}")
        return item_id

    def get_pending(self, limit: int = 10) -> list[dict]:
        """Get pending items from the queue."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM screening_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_status(
        self,
        item_id: str,
        status: QueueStatus,
        analysis_result: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update the status of a queue item."""
        now = datetime.now(timezone.utc).isoformat()
        result_json = json.dumps(analysis_result) if analysis_result else None

        with sqlite3.connect(self._db_path) as conn:
            if status == "completed":
                conn.execute(
                    """
                    UPDATE screening_queue
                    SET status = ?, analysis_result = ?, processed_at = ?
                    WHERE id = ?
                    """,
                    (status, result_json, now, item_id),
                )
            elif status == "synced":
                conn.execute(
                    """
                    UPDATE screening_queue
                    SET status = ?, synced_at = ?
                    WHERE id = ?
                    """,
                    (status, now, item_id),
                )
            elif status == "failed":
                conn.execute(
                    """
                    UPDATE screening_queue
                    SET status = ?, error_message = ?, processed_at = ?
                    WHERE id = ?
                    """,
                    (status, error_message, now, item_id),
                )
            else:
                conn.execute(
                    "UPDATE screening_queue SET status = ? WHERE id = ?",
                    (status, item_id),
                )
            conn.commit()

    def get_unsynced(self, limit: int = 50) -> list[dict]:
        """Get completed but unsynced items for batch upload."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM screening_queue
                WHERE status = 'completed'
                ORDER BY processed_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row)
                if item.get("analysis_result"):
                    item["analysis_result"] = json.loads(item["analysis_result"])
                results.append(item)
            return results

    def get_stats(self) -> dict:
        """Get queue statistics."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM screening_queue
                GROUP BY status
                """
            )
            stats = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            "pending": stats.get("pending", 0),
            "processing": stats.get("processing", 0),
            "completed": stats.get("completed", 0),
            "failed": stats.get("failed", 0),
            "synced": stats.get("synced", 0),
            "total": sum(stats.values()),
        }


# Singleton
offline_queue = OfflineQueue()
