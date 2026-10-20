from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401 — ensure ORM models are registered
from .config import settings
from .database import Base, engine
from .ml.registry import registry
from .routers import (
    analyze,
    auth,
    cases,
    dashboard,
    patients,
    reports,
    telemedicine,
    uploads,
)
from .sync import sync_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Lightweight additive migrations for existing SQLite DBs.
    from sqlalchemy import text

    with engine.connect() as conn:
        for stmt in (
            "ALTER TABLE image_uploads ADD COLUMN retake_count INTEGER DEFAULT 0",
            "ALTER TABLE image_uploads ADD COLUMN eye_laterality VARCHAR DEFAULT 'unknown'",
            "ALTER TABLE ai_findings ADD COLUMN model_version VARCHAR DEFAULT NULL",
            "ALTER TABLE screening_reports ADD COLUMN patient_id INTEGER",
            "ALTER TABLE screening_reports ADD COLUMN patient_name VARCHAR",
            "ALTER TABLE screening_reports ADD COLUMN patient_age INTEGER",
            "ALTER TABLE screening_reports ADD COLUMN patient_gender VARCHAR",
            "ALTER TABLE screening_reports ADD COLUMN referring_phc VARCHAR",
            "ALTER TABLE screening_reports ADD COLUMN submitting_worker VARCHAR",
            "ALTER TABLE screening_reports ADD COLUMN scan_date DATETIME",
            "ALTER TABLE screening_reports ADD COLUMN eye_laterality VARCHAR",
            "ALTER TABLE screening_reports ADD COLUMN image_quality VARCHAR",
            "ALTER TABLE screening_reports ADD COLUMN quality_score FLOAT",
        ):
            try:
                conn.execute(text(stmt))
            except Exception:
                pass  # column already exists
        conn.commit()
    registry.load()
    # Phase 4 Part A — backfill case_tracking rows for reports that already exist.
    from .cases import backfill_case_tracking
    from .database import SessionLocal as CaseSessionLocal

    try:
        with CaseSessionLocal() as db:
            backfill_case_tracking(db)
    except Exception:
        pass  # a failure here must not prevent the API from serving
    sync_worker.start()
    yield
    sync_worker.stop()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="NetraScan — automated DR analysis & explainable diagnostic platform (SIH 2026)",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    auth.router,
    patients.router,
    uploads.router,
    analyze.router,
    dashboard.router,
    reports.router,
    telemedicine.router,
    cases.router,
):
    app.include_router(router, prefix=settings.api_prefix)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "classifier_ready": registry.classifier is not None,
        "detector_ready": registry.detector is not None,
    }