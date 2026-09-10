"""
RetinaShield — Consent Pydantic Schemas

Schemas for managing informed consent records under Indian DPDP Act 2023.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class ConsentCreate(BaseModel):
    """Request schema to record patient consent."""
    patient_id: uuid.UUID
    consent_type: str = Field("dr_screening_and_teleophthalmology", max_length=100)
    granted: bool = True
    obtained_by_name: str | None = Field(None, max_length=255)
    witness_name: str | None = Field(None, max_length=255)
    notes: str | None = None


class ConsentWithdraw(BaseModel):
    """Request schema to record withdrawal of consent (DPDP compliance)."""
    withdrawal_reason: str = Field(..., min_length=3, description="Reason for consent withdrawal")


class ConsentRead(BaseModel):
    """Response schema for consent record."""
    id: uuid.UUID
    patient_id: uuid.UUID
    consent_type: str
    granted: bool
    consent_date: datetime
    obtained_by_name: str | None = None
    witness_name: str | None = None
    withdrawn: bool = False
    withdrawn_at: datetime | None = None
    withdrawal_reason: str | None = None
    notes: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True
