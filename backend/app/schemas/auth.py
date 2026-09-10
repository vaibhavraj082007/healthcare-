"""
RetinaShield — Authentication & User Pydantic Schemas

Schemas for staff login, JWT tokens, user creation, and role updates.
Privileged role assignment and staff provisioning are strictly administrator-controlled.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    """JWT response model."""
    access_token: str
    token_type: str = "bearer"
    role: str
    facility_id: str | None = None
    username: str


class TokenPayload(BaseModel):
    """Decoded JWT payload."""
    sub: str
    role: str
    facility_id: str | None = None
    exp: int
    iat: int


class LoginRequest(BaseModel):
    """Staff login credentials."""
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8)


class UserBase(BaseModel):
    """Base user attributes."""
    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    role: Literal["health-worker", "ophthalmologist", "administrator"] = "health-worker"
    facility_id: str | None = Field(None, max_length=100)


class UserCreate(UserBase):
    """Staff provisioning request (admin only)."""
    password: str = Field(..., min_length=8, description="Initial temporary password")


class UserRead(UserBase):
    """User response model."""
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserRoleUpdate(BaseModel):
    """Privileged role update request (admin only)."""
    role: Literal["health-worker", "ophthalmologist", "administrator"]


class UserStatusUpdate(BaseModel):
    """Activate or deactivate user account (admin only)."""
    is_active: bool
