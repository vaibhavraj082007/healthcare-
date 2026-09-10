"""
RetinaShield — Clinical Interoperability Schemas (ABDM & FHIR R4)

Structures FHIR R4 exports and tracks ABDM (Ayushman Bharat Digital Mission)
integration readiness, capabilities, and safety boundaries.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class InteropCapability(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    profile_name: str
    standard: str = "HL7 FHIR R4 / ABDM NRCeS"
    structure_definition: str
    status: str = Field(..., description="'active_export_supported', 'ready_for_sandbox', 'disabled'")
    description: str


class IntegrationRequirement(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    milestone: str = Field(..., description="ABDM Milestone: 'M1' (ABHA & Registration), 'M2' (HIP - Health Information Provider), 'M3' (HIU - Health Information User)")
    requirement_name: str
    status: str = Field(..., description="'adapter_ready', 'pending_credentials', 'pending_consent_flows', 'pending_certification'")
    details: str
    mandatory_for_routine_screening: bool = False


class InteropStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fhir_version: str = "4.0.1"
    abdm_exchange_enabled: bool
    abha_linking_enabled: bool
    environment: str
    hip_id: str
    gateway_url: str

    supported_profiles: List[InteropCapability]
    remaining_integration_requirements: List[IntegrationRequirement]

    safeguards: str = Field(
        default=(
            "REGULATORY & INTEROPERABILITY SAFEGUARDS: National-ID (Aadhaar / ABHA) linkage is "
            "OPTIONAL and NEVER mandatory for basic diabetic retinopathy screening. Live ABDM gateway "
            "exchange is strictly DISABLED until verified NHA Sandbox credentials, certified HIP/HIU bridges, "
            "and patient consent manager flows are provisioned. RetinaShield does not invent health-system endpoints "
            "or imply government certification."
        )
    )


class FHIRBundleExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    screening_id: str
    patient_id: str
    bundle_id: str
    bundle_type: str = "document"
    composition_status: str
    has_clinician_approval: bool
    is_provisional: bool
    resource_count: int
    bundle_json: Dict[str, Any]
    integrity_sha256: str = Field(..., description="Cryptographic checksum of exported bundle content")


class ExchangeTestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    allowed: bool
    environment: str
    reason: str
    prerequisite_checklist: Dict[str, bool]
    guidance: str
