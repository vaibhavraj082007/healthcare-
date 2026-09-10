"""
RetinaShield — Audit Log API

Provides immutable security and access audit logs for administrators.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.audit import AuditEvent
from app.models.user import User
from app.schemas.clinical import AuditEventRead

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("/", response_model=list[AuditEventRead])
async def list_audit_events(
    event_type: str | None = Query(None, description="Filter by event type"),
    facility_id: str | None = Query(None, description="Filter by facility code"),
    user_id: uuid.UUID | None = Query(None, description="Filter by user ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Sequence[AuditEvent]:
    """List security audit trail events (Administrator only)."""
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc())

    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    if facility_id:
        query = query.where(AuditEvent.facility_id == facility_id)
    if user_id:
        query = query.where(AuditEvent.user_id == user_id)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()
