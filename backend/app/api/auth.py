"""
RetinaShield — Staff Authentication & User Management API

Provides:
- Staff login with Argon2id verification and JWT issuance.
- Current user profile retrieval.
- Administrator-controlled staff provisioning and privileged role assignments.
- Account activation and deactivation.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin, log_audit_event
from app.core.security import hash_password, verify_password, create_access_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.auth import (
    Token,
    LoginRequest,
    UserCreate,
    UserRead,
    UserRoleUpdate,
    UserStatusUpdate,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/login", response_model=Token)
async def login(
    credentials: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Token:
    """
    Authenticate staff credentials and issue a signed JWT access token.
    Uses Argon2id password verification.
    """
    result = await db.execute(select(User).where(User.username == credentials.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(credentials.password, user.password_hash):
        await log_audit_event(
            db=db,
            event_type="login_failure",
            resource_type="auth",
            resource_id=credentials.username,
            details={"reason": "invalid_credentials"},
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        await log_audit_event(
            db=db,
            event_type="login_blocked",
            resource_type="auth",
            resource_id=str(user.id),
            details={"reason": "account_deactivated"},
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff account has been deactivated. Contact an administrator.",
        )

    role_str = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    token = create_access_token(
        subject=str(user.id),
        role=role_str,
        facility_id=user.facility_id,
    )

    await log_audit_event(
        db=db,
        event_type="login_success",
        resource_type="user",
        user=user,
        facility_id=user.facility_id,
        resource_id=str(user.id),
        request=request,
    )

    return Token(
        access_token=token,
        token_type="bearer",
        role=role_str,
        facility_id=user.facility_id,
        username=user.username,
    )


@router.get("/me", response_model=UserRead)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
) -> User:
    """Return the profile and role details of the currently authenticated staff member."""
    return current_user


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def provision_staff_user(
    data: UserCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Provision a new staff account (Health Worker, Ophthalmologist, Administrator).
    Strictly administrator-controlled.
    """
    # Check for existing username or email
    existing_username = await db.execute(select(User).where(User.username == data.username))
    if existing_username.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{data.username}' is already registered",
        )

    existing_email = await db.execute(select(User).where(User.email == data.email))
    if existing_email.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{data.email}' is already registered",
        )

    user = User(
        username=data.username,
        email=data.email,
        full_name=data.full_name,
        role=UserRole(data.role),
        facility_id=data.facility_id,
        password_hash=hash_password(data.password),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    await log_audit_event(
        db=db,
        event_type="staff_provisioned",
        resource_type="user",
        user=admin,
        facility_id=user.facility_id,
        resource_id=str(user.id),
        details={"provisioned_role": data.role, "facility": data.facility_id},
        request=request,
    )

    return user


@router.get("/users", response_model=list[UserRead])
async def list_staff_users(
    role: str | None = None,
    facility_id: str | None = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Sequence[User]:
    """List staff user accounts (Administrator only)."""
    query = select(User).order_by(User.created_at.desc())
    if role:
        query = query.where(User.role == role)
    if facility_id:
        query = query.where(User.facility_id == facility_id)

    result = await db.execute(query)
    return result.scalars().all()


@router.patch("/users/{user_id}/role", response_model=UserRead)
async def update_staff_role(
    user_id: uuid.UUID,
    data: UserRoleUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Assign or modify privileged role (Administrator only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    user.role = UserRole(data.role)
    await db.flush()
    await db.refresh(user)

    await log_audit_event(
        db=db,
        event_type="role_assigned",
        resource_type="user",
        user=admin,
        resource_id=str(user.id),
        details={"previous_role": old_role, "new_role": data.role},
        request=request,
    )

    return user


@router.patch("/users/{user_id}/status", response_model=UserRead)
async def update_staff_status(
    user_id: uuid.UUID,
    data: UserStatusUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Activate or deactivate a staff member account (Administrator only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent admin from deactivating themselves
    if user.id == admin.id and not data.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administrators cannot deactivate their own active account",
        )

    user.is_active = data.is_active
    await db.flush()
    await db.refresh(user)

    await log_audit_event(
        db=db,
        event_type="status_changed",
        resource_type="user",
        user=admin,
        resource_id=str(user.id),
        details={"is_active": data.is_active},
        request=request,
    )

    return user
