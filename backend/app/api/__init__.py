"""
RetinaShield — API Routes Package
"""

from app.api.patients import router as patients_router
from app.api.screenings import router as screenings_router
from app.api.analysis import router as analysis_router
from app.api.sync import router as sync_router

__all__ = ["patients_router", "screenings_router", "analysis_router", "sync_router"]
