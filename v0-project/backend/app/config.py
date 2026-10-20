from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables or defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "NetraScan"
    app_version: str = "0.2.0"
    api_prefix: str = "/api"

    secret_key: str = "netrascan-dev-secret-change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12

    database_url: str = f"sqlite:///{BASE_DIR / 'netrascan.db'}"

    upload_dir: Path = BASE_DIR / "uploads"
    models_dir: Path = BASE_DIR / "models"

    classifier_weights: Path = models_dir / "efficientnet_b0_dr.pt"
    detector_weights: Path = models_dir / "yolov8_lesion.pt"

    input_size: int = 380
    device: str = "cpu"

    # Phase 4 — the prototype runs the PHC instance and the telemedicine server
    # as the same backend, so the bandwidth probe pings our own health endpoint.
    telemedicine_base_url: str = "http://127.0.0.1:8000"


settings = Settings()