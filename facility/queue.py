"""
RetinaShield — Facility Offline Queue (Encrypted SQLite)

Durable outbox for offline captures and analysis results. Uses SQLCipher when
available (pysqlcipher3) and falls back to plain sqlite3 with a loud warning
when the key env var is absent or SQLCipher is not installed.

Schema columns added beyond the original design:
    local_encounter_id   — stable UUID set at first capture; deduplication key.
    image_sha256         — SHA-256 of raw (pre-encryption) image bytes.
    upload_offset_bytes  — bytes already confirmed received by server (resume).
    retry_count          — number of sync attempts so far.
    next_retry_at        — ISO timestamp: earliest time to retry this item.
    sync_conflict        — True when server rejected due to conflict.
    conflict_details     — JSON from server conflict response.
    clinician_approved_locally — True when a local ophthalmologist has signed
                                 the review; prevents silent server overwrite.
    consent_recorded     — True when informed consent has been obtained.

Sync state machine:
    pending → processing → completed → syncing → synced
                         ↘ failed ──→ (retry → syncing → synced)
                                    ↘ conflict (requires human resolution)
"""

from __future__ import annotations

import json
import logging
import math
import random
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from facility.config import facility_config

logger = logging.getLogger(__name__)

QueueStatus = Literal[
    "pending",
    "processing",
    "completed",
    "syncing",
    "synced",
    "failed",
    "conflict",
]

# ── SQLCipher support ─────────────────────────────────────────────────────────

def _open_connection(db_path: str, key: str) -> sqlite3.Connection:
    """
    Open a SQLite connection, enabling SQLCipher encryption when possible.

    Falls back to plain sqlite3 if:
    - pysqlcipher3 is not installed, or
    - `key` is empty (development mode).
    """
    if not key:
        logger.warning(
            "FACILITY DB ENCRYPTION DISABLED — db_encryption_key_env_var is not set. "
            "This is NOT acceptable for production deployments."
        )
        return sqlite3.connect(db_path)

    # Try SQLCipher
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher  # type: ignore[import]
        conn: sqlite3.Connection = sqlcipher.connect(db_path)  # type: ignore[assignment]
        conn.execute(f"PRAGMA key='{key}'")
        conn.execute("PRAGMA cipher_page_size=4096")
        conn.execute("PRAGMA kdf_iter=64000")
        conn.execute("PRAGMA cipher_hmac_algorithm=HMAC_SHA512")
        conn.execute("SELECT count(*) FROM sqlite_master")  # test key is valid
        return conn
    except ModuleNotFoundError:
        logger.warning(
            "pysqlcipher3 not installed — using plain sqlite3. "
            "Install pysqlcipher3 or sqlcipher-apsw for at-rest DB encryption."
        )
    except Exception as exc:
        logger.error("SQLCipher open failed (%s) — falling back to plain sqlite3.", exc)

    return sqlite3.connect(db_path)


class OfflineQueue:
    """
    SQLite-backed (optionally SQLCipher-encrypted) queue for offline screening data.

    Thread safety: each public method opens and closes its own connection.
    Do not share connection objects across threads.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or str(facility_config.queue_db_path)
        self._key = facility_config.db_encryption_key
        self._cfg = facility_config
        self._init_db()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = _open_connection(self._db_path, self._key)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        """Create tables and indices; safe to call on every startup."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS screening_queue (
                    id                          TEXT PRIMARY KEY,
                    local_encounter_id          TEXT NOT NULL,
                    patient_id                  TEXT NOT NULL,
                    facility_id                 TEXT NOT NULL,
                    eye                         TEXT NOT NULL DEFAULT 'both',
                    image_path                  TEXT,
                    image_sha256                TEXT,
                    status                      TEXT NOT NULL DEFAULT 'pending',
                    analysis_result             TEXT,
                    error_message               TEXT,
                    upload_offset_bytes         INTEGER NOT NULL DEFAULT 0,
                    retry_count                 INTEGER NOT NULL DEFAULT 0,
                    next_retry_at               TEXT,
                    sync_conflict               INTEGER NOT NULL DEFAULT 0,
                    conflict_details            TEXT,
                    clinician_approved_locally  INTEGER NOT NULL DEFAULT 0,
                    consent_recorded            INTEGER NOT NULL DEFAULT 0,
                    created_at                  TEXT NOT NULL,
                    processed_at                TEXT,
                    synced_at                   TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_queue_status
                    ON screening_queue(status);

                CREATE INDEX IF NOT EXISTS idx_queue_encounter
                    ON screening_queue(local_encounter_id);

                CREATE INDEX IF NOT EXISTS idx_queue_retry
                    ON screening_queue(next_retry_at)
                    WHERE status = 'failed';
            """)
        logger.info("Offline queue initialised: %s", self._db_path)

    # ── Write operations ──────────────────────────────────────────────────────

    def enqueue(
        self,
        patient_id: str,
        image_path: str | None,
        eye: str = "both",
        image_sha256: str | None = None,
        consent_recorded: bool = False,
        local_encounter_id: str | None = None,
    ) -> str:
        """
        Add a screening to the offline queue.

        `local_encounter_id` is a stable UUID assigned at capture time and used
        as the server-side idempotency key.  If not supplied, a new UUID is
        generated.

        Returns the queue item ID (same as `local_encounter_id`).
        """
        enc_id = local_encounter_id or str(uuid.uuid4())
        item_id = enc_id  # item ID == encounter ID for deduplication
        now = _now()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM screening_queue WHERE local_encounter_id = ?",
                (enc_id,),
            ).fetchone()

            if existing:
                logger.warning(
                    "Encounter %s already in queue — skipping duplicate enqueue.", enc_id
                )
                return existing["id"]

            conn.execute(
                """
                INSERT INTO screening_queue
                    (id, local_encounter_id, patient_id, facility_id, eye,
                     image_path, image_sha256, status, consent_recorded, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    item_id,
                    enc_id,
                    patient_id,
                    self._cfg.facility_id,
                    eye,
                    image_path,
                    image_sha256,
                    int(consent_recorded),
                    now,
                ),
            )
            conn.commit()

        logger.info("Enqueued encounter %s patient=%s eye=%s", enc_id, patient_id, eye)
        return item_id

    def update_status(
        self,
        item_id: str,
        status: QueueStatus,
        analysis_result: dict | None = None,
        error_message: str | None = None,
        upload_offset_bytes: int | None = None,
    ) -> None:
        """Generic status update — use specific helpers where possible."""
        now = _now()
        result_json = json.dumps(analysis_result) if analysis_result else None

        with self._connect() as conn:
            if status == "completed":
                conn.execute(
                    """
                    UPDATE screening_queue
                    SET status=?, analysis_result=?, processed_at=?
                    WHERE id=?
                    """,
                    (status, result_json, now, item_id),
                )
            elif status == "synced":
                conn.execute(
                    "UPDATE screening_queue SET status=?, synced_at=? WHERE id=?",
                    (status, now, item_id),
                )
            elif status == "failed":
                conn.execute(
                    """
                    UPDATE screening_queue
                    SET status=?, error_message=?, processed_at=?
                    WHERE id=?
                    """,
                    (status, error_message, now, item_id),
                )
            elif status == "syncing" and upload_offset_bytes is not None:
                conn.execute(
                    """
                    UPDATE screening_queue
                    SET status=?, upload_offset_bytes=?
                    WHERE id=?
                    """,
                    (status, upload_offset_bytes, item_id),
                )
            else:
                conn.execute(
                    "UPDATE screening_queue SET status=? WHERE id=?",
                    (status, item_id),
                )
            conn.commit()

    def record_retry_failure(self, item_id: str, error_message: str) -> None:
        """
        Increment retry_count and set next_retry_at using exponential backoff.
        Marks the item 'failed' (eligible for future retry).
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT retry_count FROM screening_queue WHERE id=?", (item_id,)
            ).fetchone()
            if not row:
                return

            retry_count = row["retry_count"] + 1
            delay = _backoff_delay(
                retry_count,
                self._cfg.retry_backoff_base_seconds,
                self._cfg.retry_backoff_max_seconds,
                self._cfg.retry_backoff_jitter_fraction,
            )
            next_retry = (
                datetime.now(timezone.utc) + timedelta(seconds=delay)
            ).isoformat()

            conn.execute(
                """
                UPDATE screening_queue
                SET status='failed', retry_count=?, next_retry_at=?, error_message=?
                WHERE id=?
                """,
                (retry_count, next_retry, error_message, item_id),
            )
            conn.commit()

        logger.warning(
            "Retry %d/%d for %s in %.0fs: %s",
            retry_count,
            self._cfg.max_retry_attempts,
            item_id,
            delay,
            error_message,
        )

    def mark_conflict(self, item_id: str, conflict_details: dict) -> None:
        """
        Mark a queue item as having a sync conflict.

        Clinician-approved records are NEVER silently overwritten — the conflict
        is surfaced to a human for resolution.
        """
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE screening_queue
                SET status='conflict', sync_conflict=1, conflict_details=?
                WHERE id=?
                """,
                (json.dumps(conflict_details), item_id),
            )
            conn.commit()
        logger.warning("Sync conflict for encounter %s: %s", item_id, conflict_details)

    def mark_clinician_approved(self, item_id: str) -> None:
        """Record that a local ophthalmologist has approved this encounter."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE screening_queue SET clinician_approved_locally=1 WHERE id=?",
                (item_id,),
            )
            conn.commit()

    def update_upload_offset(self, item_id: str, offset: int) -> None:
        """Record how many bytes the server has confirmed for partial-upload resume."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE screening_queue SET upload_offset_bytes=?, status='syncing' WHERE id=?",
                (offset, item_id),
            )
            conn.commit()

    # ── Read operations ───────────────────────────────────────────────────────

    def get_pending(self, limit: int = 5) -> list[dict]:
        """Items queued for local inference."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM screening_queue
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_for_retry(self, limit: int = 10) -> list[dict]:
        """
        Items that failed but are now past their `next_retry_at` and have not
        exceeded `max_retry_attempts`.
        """
        now = _now()
        max_retries = self._cfg.max_retry_attempts
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM screening_queue
                WHERE status = 'failed'
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
                  AND retry_count < ?
                ORDER BY next_retry_at ASC
                LIMIT ?
                """,
                (now, max_retries, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_unsynced(self, limit: int = 50) -> list[dict]:
        """Completed (locally-inferred) items waiting to be uploaded."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM screening_queue
                WHERE status IN ('completed', 'syncing')
                  AND sync_conflict = 0
                ORDER BY processed_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            if item.get("analysis_result"):
                item["analysis_result"] = json.loads(item["analysis_result"])
            if item.get("conflict_details"):
                item["conflict_details"] = json.loads(item["conflict_details"])
            items.append(item)
        return items

    def get_conflict_items(self) -> list[dict]:
        """Items blocked on a sync conflict requiring human resolution."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM screening_queue WHERE status='conflict' ORDER BY created_at ASC"
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            if item.get("conflict_details"):
                item["conflict_details"] = json.loads(item["conflict_details"])
            items.append(item)
        return items

    def get_stats(self) -> dict:
        """Queue statistics by status."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM screening_queue GROUP BY status"
            ).fetchall()
        stats = {row["status"]: row["cnt"] for row in rows}
        return {
            "pending": stats.get("pending", 0),
            "processing": stats.get("processing", 0),
            "completed": stats.get("completed", 0),
            "syncing": stats.get("syncing", 0),
            "synced": stats.get("synced", 0),
            "failed": stats.get("failed", 0),
            "conflict": stats.get("conflict", 0),
            "total": sum(stats.values()),
        }

    def prune_old_synced(self) -> int:
        """Delete synced items older than `max_outbox_age_days`. Returns count removed."""
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(days=self._cfg.max_outbox_age_days)
        ).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM screening_queue WHERE status='synced' AND synced_at < ?",
                (cutoff,),
            )
            conn.commit()
        removed = cursor.rowcount
        if removed:
            logger.info("Pruned %d old synced items.", removed)
        return removed


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backoff_delay(
    retry_count: int,
    base: float,
    cap: float,
    jitter_fraction: float,
) -> float:
    """Full-jitter exponential backoff."""
    exp = min(base * (2 ** (retry_count - 1)), cap)
    jitter = exp * jitter_fraction * (2 * random.random() - 1)
    return max(1.0, exp + jitter)


# Singleton
offline_queue = OfflineQueue()
