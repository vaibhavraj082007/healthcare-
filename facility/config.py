"""
RetinaShield — Facility Offline Service Configuration
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class FacilityConfig(BaseSettings):
    """Configuration for the offline facility service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    facility_id: str = "dev-facility-001"
    facility_name: str = "Development Facility"
    facility_queue_db: str = "./data/facility_queue.db"
    sync_server_url: str = "http://localhost:8000"
    sync_interval_seconds: int = 300
    image_storage_path: str = "./data/images"
    matlab_mode: str = "fallback"
    pipeline_version: str = "0.1.0-dev"

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


facility_config = FacilityConfig()
