"""
RetinaShield — Facility Offline Service Configuration

Keys for encryption are read from environment variables (or an OS keyring when
keyring_enabled=True). They are NEVER stored in browser storage or application
database rows.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class FacilityConfig(BaseSettings):
    """Configuration for the offline facility service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    facility_id: str = "dev-facility-001"
    facility_name: str = "Development Facility"

    # ── Database ──────────────────────────────────────────────────────────────
    facility_queue_db: str = "./data/facility_queue.db"

    # SQLCipher passphrase — read from env var; empty string disables encryption
    # (development only). In production this MUST be set.
    db_encryption_key_env_var: str = "FACILITY_DB_KEY"

    # ── Image storage ─────────────────────────────────────────────────────────
    image_storage_path: str = "./data/images"

    # AES-256-GCM image-level encryption
    image_encryption_enabled: bool = True
    image_encryption_key_env_var: str = "FACILITY_IMAGE_KEY"

    # ── Sync ──────────────────────────────────────────────────────────────────
    sync_server_url: str = "http://localhost:8000"
    sync_interval_seconds: int = 300
    sync_server_auth_token_env_var: str = "FACILITY_SYNC_TOKEN"

    # Retry / backoff
    max_retry_attempts: int = 10
    retry_backoff_base_seconds: float = 30.0
    retry_backoff_max_seconds: float = 3600.0
    retry_backoff_jitter_fraction: float = 0.20

    # Prune synced items older than this many days
    max_outbox_age_days: int = 30

    # Chunked upload — 2 MB chunks by default
    upload_chunk_size_bytes: int = 2 * 1024 * 1024

    # ── Inference mode ────────────────────────────────────────────────────────
    # CAPTURE_ONLY  — queue items, do not attempt inference locally
    # OFFLINE_FULL  — run MATLAB / MCR / Python-fallback inference locally
    # ONLINE_REMOTE — forward to central server inference jobs
    operation_mode: Literal["CAPTURE_ONLY", "OFFLINE_FULL", "ONLINE_REMOTE"] = "OFFLINE_FULL"
    matlab_mode: str = "fallback"
    pipeline_version: str = "0.1.0-dev"
    max_concurrent_inference_jobs: int = 1

    # ── Misc ──────────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def queue_db_path(self) -> Path:
        p = Path(self.facility_queue_db)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def image_dir(self) -> Path:
        p = Path(self.image_storage_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_encryption_key(self) -> str:
        """
        Return the SQLCipher passphrase.

        Reads from the env var named by `db_encryption_key_env_var`.
        Returns empty string (unencrypted) if the env var is absent — which
        generates a loud warning at startup.
        """
        key = os.environ.get(self.db_encryption_key_env_var, "")
        return key

    @property
    def image_encryption_key(self) -> bytes | None:
        """
        Return raw key bytes for AES-256-GCM image encryption, or None if
        encryption is disabled. The env var must contain a hex-encoded 32-byte
        (64 hex char) key.
        """
        if not self.image_encryption_enabled:
            return None
        raw = os.environ.get(self.image_encryption_key_env_var, "")
        if not raw:
            return None
        try:
            key_bytes = bytes.fromhex(raw)
            if len(key_bytes) != 32:
                raise ValueError("Image encryption key must be 32 bytes (64 hex chars).")
            return key_bytes
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid {self.image_encryption_key_env_var}: {exc}"
            ) from exc

    @property
    def sync_auth_token(self) -> str | None:
        """Bearer token for authenticating to the central sync server."""
        return os.environ.get(self.sync_server_auth_token_env_var)


facility_config = FacilityConfig()
