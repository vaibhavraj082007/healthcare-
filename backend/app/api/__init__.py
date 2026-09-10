"""
RetinaShield — API Routes Package
"""

from app.api.auth import router as auth_router
from app.api.facilities import router as facilities_router
from app.api.consent import router as consent_router
from app.api.patients import router as patients_router
from app.api.screenings import router as screenings_router
from app.api.reviews import router as reviews_router
from app.api.analysis import router as analysis_router
from app.api.sync import router as sync_router
from app.api.evaluation import router as evaluation_router
from app.api.audit import router as audit_router
from app.api.jobs import router as jobs_router
from app.api.monitoring import router as monitoring_router

__all__ = [
    "auth_router",
    "facilities_router",
    "consent_router",
    "patients_router",
    "screenings_router",
    "reviews_router",
    "analysis_router",
    "sync_router",
    "evaluation_router",
    "audit_router",
    "jobs_router",
    "monitoring_router",
]

