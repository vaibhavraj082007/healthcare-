"""
RetinaShield — Patient Pydantic Schemas

Request/response schemas for patient CRUD operations.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class PatientBase(BaseModel):
    """Shared patient fields."""

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = Field(None, max_length=20)
    phone: str | None = Field(None, max_length=20)
    aadhaar_last4: str | None = Field(
        None, min_length=4, max_length=4,
        description="Last 4 digits of Aadhaar — never store full number"
    )
    diabetes_type: str | None = None
    diabetes_duration_years: int | None = Field(None, ge=0)
    on_insulin: bool | None = None
    hba1c_latest: float | None = Field(None, ge=0, le=20)
    notes: str | None = None
    facility_id: str | None = None


class PatientCreate(PatientBase):
    """Schema for creating a new patient."""

    pass


class PatientUpdate(BaseModel):
    """Schema for updating a patient (all fields optional)."""

    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = None
    phone: str | None = None
    diabetes_type: str | None = None
    diabetes_duration_years: int | None = None
    on_insulin: bool | None = None
    hba1c_latest: float | None = None
    notes: str | None = None


class PatientRead(PatientBase):
    """Schema for reading a patient record."""

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    screening_count: int = 0

    class Config:
        from_attributes = True
