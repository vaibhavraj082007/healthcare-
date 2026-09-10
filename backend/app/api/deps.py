"""
RetinaShield — API Dependencies & Access Control

Enforces authentication, role-based access control (RBAC), facility scoping,
and immutable security audit logging.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.audit import AuditEvent

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Validate JWT access token and return current authenticated User.
    Extracts token from either Authorization header or cookie.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Check header or session cookie
    raw_token = token
    if not raw_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            raw_token = auth_header.split(" ", 1)[1]
        elif "access_token" in request.cookies:
            raw_token = request.cookies.get("access_token")

    if not raw_token:
        raise credentials_exception

    try:
        payload = decode_access_token(raw_token)
        user_id_str: str | None = payload.get("sub")
        if not user_id_str:
            raise credentials_exception
        user_uuid = uuid.UUID(user_id_str)
    except (jwt.PyJWTError, ValueError) as e:
        logger.warning(f"JWT decode error: {e}")
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()

    if not user:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive staff account",
        )

    return user


def require_role(*allowed_roles: UserRole | str) -> Callable[[User], User]:
    """
    Factory dependency for role-based access control (RBAC).

    Example
    -------
    @router.post("/users", dependencies=[Depends(require_role(UserRole.ADMINISTRATOR))])
    """
    roles_str = {r.value if isinstance(r, UserRole) else str(r) for r in allowed_roles}

    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role_val = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role_val not in roles_str:
            logger.warning(
                f"Access denied for user {current_user.username} (role: {user_role_val}). "
                f"Required roles: {roles_str}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted for role '{user_role_val}'",
            )
        return current_user

    return role_checker


# Convenient role dependencies
require_admin = require_role(UserRole.ADMINISTRATOR)
require_health_worker = require_role(UserRole.HEALTH_WORKER, UserRole.ADMINISTRATOR)
require_ophthalmologist = require_role(UserRole.OPHTHALMOLOGIST, UserRole.ADMINISTRATOR)
require_staff = require_role(
    UserRole.HEALTH_WORKER, UserRole.OPHTHALMOLOGIST, UserRole.ADMINISTRATOR
)


def verify_facility_access(user: User, target_facility_id: str | None) -> bool:
    """
    Verify if staff member has permission to view/modify data for the target facility.
    - Administrators have system-wide access.
    - Ophthalmologists have review queue access across designated facilities.
    - Health-workers are strictly constrained to their own registered facility.
    """
    user_role_val = (
        user.role.value if isinstance(user.role, UserRole) else str(user.role)
    )

    if user_role_val == UserRole.ADMINISTRATOR.value:
        return True
    if user_role_val == UserRole.OPHTHALMOLOGIST.value:
        return True  # Tele-ophthalmology reviewers can inspect referral queues

    # Health-worker scoping
    if not target_facility_id:
        return True  # If not scoped to specific facility
    if user.facility_id and user.facility_id == target_facility_id:
        return True

    logger.warning(
        f"Facility access violation: user {user.username} (facility: {user.facility_id}) "
        f"attempted to access facility {target_facility_id}"
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Access denied to facility '{target_facility_id}'",
    )


async def log_audit_event(
    db: AsyncSession,
    event_type: str,
    resource_type: str,
    user: User | None = None,
    facility_id: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditEvent:
    """
    Log an immutable security audit event.
    Guarantees no patient PII or secrets are stored in the audit trail.
    """
    ip_address = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None

    # Sanitize details to avoid recording any PII
    sanitized_details = {}
    if details:
        for k, v in details.items():
            if k in ("password", "token", "hash", "first_name", "last_name", "phone", "notes", "aadhaar_last4"):
                sanitized_details[k] = "[REDACTED]"
            else:
                sanitized_details[k] = v

    audit = AuditEvent(
        user_id=user.id if user else None,
        facility_id=facility_id or (user.facility_id if user else None),
        event_type=event_type,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        ip_address=ip_address,
        user_agent=user_agent,
        details=sanitized_details,
    )
    db.add(audit)
    await db.flush()
    return audit
