"""
RetinaShield — Application Configuration

Loads settings from environment variables / .env file using pydantic-settings.
"""

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- General ---
    app_name: str = "RetinaShield"
    app_env: Literal["development", "staging", "production"] = "development"
    pipeline_version: str = "0.1.0-dev"
    debug: bool = True
    log_level: str = "INFO"

    # --- FastAPI & Security ---
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    secret_key: str = "retinashield_super_secure_secret_key_minimum_32_bytes_long_2026"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours clinical work shift
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    # --- Database ---
    database_url: str = (
        "postgresql+asyncpg://retinashield:devpassword@localhost:5432/retinashield"
    )

    # --- Image Storage & Validation ---
    image_storage_path: str = "./data/images"
    max_upload_size_mb: int = 50
    min_upload_dim_px: int = 512
    max_upload_dim_px: int = 8192

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def image_storage_dir(self) -> Path:
        p = Path(self.image_storage_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # --- Retention & Backups ---
    retention_statutory_years: int = 7
    audit_log_retention_days: int = 2555
    backup_storage_path: str = "./data/backups"

    @property
    def backup_storage_dir(self) -> Path:
        p = Path(self.backup_storage_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # --- MATLAB ---
    matlab_mode: Literal["engine", "mcr", "fallback"] = "fallback"
    matlab_root: str = ""
    mcr_root: str = ""
    matlab_compiled_package: str = ""

    # --- YOLOv8 ---
    yolo_weights_path: str = ""
    yolo_confidence_threshold: float = 0.25
    yolo_device: str = "mps"  # Apple Silicon GPU

    # --- EfficientNet ---
    efficientnet_weights_path: str = ""
    efficientnet_input_size: int = 224

    # --- Facility / Offline ---
    facility_id: str = "dev-facility-001"
    facility_name: str = "Development Facility"
    facility_queue_db: str = "./data/facility_queue.db"
    sync_server_url: str = "http://localhost:8000"
    sync_interval_seconds: int = 300
    offline_mode: bool = False

    # --- Security ---
    image_encryption_key: str = ""
    encrypt_images: bool = False

    # --- Operational Monitoring & Privacy ---
    monitoring_small_cell_threshold: int = 5  # Counts < 5 are suppressed to prevent patient re-identification
    monitoring_baseline_window_days: int = 30
    monitoring_current_window_days: int = 7

    # --- ABDM & Interoperability Adapter ---
    # Safe default: live exchange and ABHA linking are strictly DISABLED until authorized
    # sandbox access, consent flows, and verified implementation requirements are available.
    abdm_exchange_enabled: bool = False
    abha_linking_enabled: bool = False
    abdm_environment: Literal["disabled", "sandbox", "production"] = "disabled"
    abdm_gateway_url: str = "https://dev.abdm.gov.in/gateway"
    abdm_client_id: str = ""
    abdm_client_secret: str = ""
    abdm_hip_id: str = "IN-MH-PHC-001"  # Health Information Provider ID


# Singleton instance
settings = Settings()
