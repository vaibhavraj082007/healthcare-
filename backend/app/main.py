"""
RetinaShield — FastAPI Application Entry Point

Main application with CORS, lifespan management, and route registration.

IMPORTANT: This is a RESEARCH SCREENING prototype.
All analysis outputs must be reviewed by a qualified ophthalmologist.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.session import init_db, close_db
from app.api import patients_router, screenings_router, analysis_router, sync_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info("=" * 60)
    logger.info(f" {settings.app_name} v{settings.pipeline_version}")
    logger.info(" RESEARCH SCREENING PROTOTYPE — Not for clinical use")
    logger.info("=" * 60)
    logger.info(f" Environment: {settings.app_env}")
    logger.info(f" MATLAB mode: {settings.matlab_mode}")
    logger.info(f" Debug: {settings.debug}")
    logger.info("=" * 60)

    # Initialize database tables (dev only — use Alembic in production)
    if settings.app_env == "development":
        try:
            await init_db()
            logger.info("Database tables initialized")
        except Exception as e:
            logger.warning(f"Database initialization skipped: {e}")
            logger.warning("Ensure PostgreSQL is running and DATABASE_URL is correct")

    yield

    # Shutdown
    logger.info("Shutting down...")
    from app.services.matlab_bridge import matlab_bridge
    matlab_bridge.shutdown()
    await close_db()
    logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.app_name,
    description=(
        "Research prototype for explainable diabetic retinopathy screening "
        "in rural Indian primary healthcare centres. "
        "**All outputs are research screening results — NOT autonomous clinical diagnoses.** "
        "Must be reviewed by a qualified ophthalmologist."
    ),
    version=settings.pipeline_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(patients_router)
app.include_router(screenings_router)
app.include_router(analysis_router)
app.include_router(sync_router)


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------

@app.get("/")
async def root() -> dict:
    """API root — health check and system info."""
    return {
        "name": settings.app_name,
        "version": settings.pipeline_version,
        "status": "running",
        "matlab_mode": settings.matlab_mode,
        "disclaimer": (
            "RESEARCH SCREENING PROTOTYPE — Not for clinical diagnosis. "
            "All results must be reviewed by a qualified ophthalmologist."
        ),
    }


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint for monitoring."""
    return {"status": "healthy", "version": settings.pipeline_version}
