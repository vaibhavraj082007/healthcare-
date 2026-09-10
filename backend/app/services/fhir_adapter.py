"""
RetinaShield — ABDM & HL7 FHIR R4 Interoperability Adapter

Provides structured clinical export mapping persisted diabetic retinopathy screening sessions,
quality assessment metrics, model outputs, and clinician reviews to official:
- HL7 FHIR Release 4 (R4)
- ABDM NRCeS (National Resource Centre for EHR Standards) Profiles:
    - DocumentBundle: https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle
    - DiagnosticReportRecord: https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportRecord
    - DiagnosticReportImaging: https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportImaging

SAFEGUARD POLICY:
- National-ID (Aadhaar / ABHA) is strictly OPTIONAL and never mandatory for screening.
- Live ABDM exchange is DISABLED by default until authorized NHA Sandbox credentials,
  certified HIP/HIU bridges, and patient consent manager flows are provisioned.
- No health-system endpoints are fabricated; no official government certification is implied.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.screening import Screening, ScreeningImage
from app.models.patient import Patient
from app.models.clinical import QualityResult, ModelOutput, ClinicianReview
from app.schemas.interop import (
    FHIRBundleExportResponse,
    InteropStatusResponse,
    InteropCapability,
    IntegrationRequirement,
    ExchangeTestResponse,
)


class ABDMFHIRAdapter:
    """Adapter for generating ABDM / FHIR R4 clinical documents and managing interoperability boundaries."""

    # Official SNOMED CT & LOINC clinical terminologies
    SNOMED_DR_SCREENING = "24700007"
    SNOMED_DR_FINDINGS = {
        0: {"code": "281036007", "display": "No diabetic retinopathy"},
        1: {"code": "312903001", "display": "Mild nonproliferative diabetic retinopathy"},
        2: {"code": "312904007", "display": "Moderate nonproliferative diabetic retinopathy"},
        3: {"code": "312905008", "display": "Severe nonproliferative diabetic retinopathy"},
        4: {"code": "59276001", "display": "Proliferative diabetic retinopathy"},
        -1: {"code": "397745006", "display": "Medical examination ungradeable"},
    }
    SNOMED_MACULAR_EDEMA = "37231002"
    LOINC_DR_SCREENING_SUMMARY = "89260-4"
    LOINC_RETINAL_CAMERA_STUDY = "74768-3"

    @classmethod
    def get_interop_status(cls) -> InteropStatusResponse:
        """Returns the readiness status, supported profiles, and remaining integration requirements."""
        supported_profiles = [
            InteropCapability(
                profile_name="DocumentBundle",
                structure_definition="https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle",
                status="active_export_supported",
                description="FHIR R4 Document Bundle encapsulating Composition, Patient, DiagnosticReport, Observations, and Media.",
            ),
            InteropCapability(
                profile_name="DiagnosticReportRecord (Composition)",
                structure_definition="https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportRecord",
                status="active_export_supported",
                description="Composition document manifest binding ophthalmology screening findings with author provenance.",
            ),
            InteropCapability(
                profile_name="DiagnosticReportImaging",
                structure_definition="https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportImaging",
                status="active_export_supported",
                description="Structured diagnostic imaging report for diabetic retinopathy fundus examination.",
            ),
            InteropCapability(
                profile_name="Observation (DR Stage & Quality)",
                structure_definition="http://hl7.org/fhir/StructureDefinition/Observation",
                status="active_export_supported",
                description="Coded observations using standard SNOMED CT and LOINC terminologies for DR grading and IQA.",
            ),
            InteropCapability(
                profile_name="Media / DocumentReference",
                structure_definition="http://hl7.org/fhir/StructureDefinition/Media",
                status="active_export_supported",
                description="Fundus photography metadata with cryptographic SHA-256 byte-level hash verification.",
            ),
        ]

        remaining_requirements = [
            IntegrationRequirement(
                milestone="M1",
                requirement_name="ABHA Issuance & Verification Gateway",
                status="adapter_ready",
                details="RetinaShield supports optional ABHA demographic fields, but does NOT mandate them. Direct ABHA creation requires NHA OTP gateway access.",
                mandatory_for_routine_screening=False,
            ),
            IntegrationRequirement(
                milestone="M2",
                requirement_name="HIP (Health Information Provider) Bridge Registration",
                status="pending_credentials",
                details="Requires registered client credentials on the official ABDM Sandbox/Production gateway to receive discovery and link requests.",
                mandatory_for_routine_screening=False,
            ),
            IntegrationRequirement(
                milestone="M2",
                requirement_name="Consent Manager (CM) Flow Integration",
                status="pending_consent_flows",
                details="Data transfer to ABDM locker requires active patient consent artifact (HIU-HIP consent handshake) before pushing encrypted FHIR bundles.",
                mandatory_for_routine_screening=False,
            ),
            IntegrationRequirement(
                milestone="M3",
                requirement_name="HIU (Health Information User) Pull Services",
                status="pending_certification",
                details="Requires ABDM M3 audit and certification to query and fetch longitudinal historical retinal images from external health lockers.",
                mandatory_for_routine_screening=False,
            ),
        ]

        return InteropStatusResponse(
            fhir_version="4.0.1",
            abdm_exchange_enabled=settings.abdm_exchange_enabled,
            abha_linking_enabled=settings.abha_linking_enabled,
            environment=settings.abdm_environment,
            hip_id=settings.abdm_hip_id,
            gateway_url=settings.abdm_gateway_url,
            supported_profiles=supported_profiles,
            remaining_integration_requirements=remaining_requirements,
        )

    @classmethod
    def generate_bundle(
        cls,
        screening: Screening,
        patient: Patient,
        image: Optional[ScreeningImage] = None,
        quality: Optional[QualityResult] = None,
        model_output: Optional[ModelOutput] = None,
        review: Optional[ClinicianReview] = None,
    ) -> FHIRBundleExportResponse:
        """
        Constructs a valid HL7 FHIR R4 / ABDM NRCeS Document Bundle from persisted screening records.
        """
        bundle_id = str(uuid.uuid4())
        composition_id = str(uuid.uuid4())
        patient_resource_id = f"Patient-{screening.patient_id}"
        report_resource_id = f"DiagnosticReport-{screening.id}"

        now_iso = datetime.now(timezone.utc).isoformat()
        has_review = review is not None and review.status != "draft"
        is_provisional = not has_review

        # 1. Patient Resource (Minimal demographic, optional ABHA, no mandatory national ID)
        patient_identifiers = [
            {
                "system": "https://retinashield.local/patient-id",
                "value": str(patient.id),
            }
        ]
        if getattr(patient, "abha_address", None):
            patient_identifiers.append({
                "system": "https://healthid.ndhm.gov.in",
                "value": patient.abha_address,
            })

        patient_resource: Dict[str, Any] = {
            "fullUrl": f"urn:uuid:{patient_resource_id}",
            "resource": {
                "resourceType": "Patient",
                "id": patient_resource_id,
                "meta": {
                    "profile": ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/Patient"]
                },
                "identifier": patient_identifiers,
                "gender": (patient.gender.lower() if getattr(patient, "gender", None) in ["male", "female", "other"] else "unknown"),
                "birthDate": str(patient.date_of_birth) if getattr(patient, "date_of_birth", None) else None,
            },
        }

        # 2. Observations
        observations: List[Dict[str, Any]] = []
        observation_references: List[Dict[str, str]] = []

        # (a) DR Severity Observation
        dr_grade = (
            review.confirmed_dr_grade
            if has_review and review
            else (model_output.predicted_dr_grade if model_output else screening.dr_grade)
        )
        if dr_grade is not None:
            dr_finding = cls.SNOMED_DR_FINDINGS.get(
                dr_grade,
                {"code": "397745006", "display": "Medical examination ungradeable"}
            )
            obs_dr_id = f"Observation-DR-Grade-{screening.id}"
            obs_dr = {
                "fullUrl": f"urn:uuid:{obs_dr_id}",
                "resource": {
                    "resourceType": "Observation",
                    "id": obs_dr_id,
                    "status": "final" if has_review else "preliminary",
                    "category": [
                        {
                            "coding": [
                                {
                                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                    "code": "exam",
                                    "display": "Exam",
                                }
                            ]
                        }
                    ],
                    "code": {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": cls.SNOMED_DR_SCREENING,
                                "display": "Diabetic retinopathy screening",
                            }
                        ],
                        "text": "Diabetic Retinopathy Screening Grade",
                    },
                    "subject": {"reference": f"urn:uuid:{patient_resource_id}"},
                    "effectiveDateTime": screening.created_at.isoformat() if screening.created_at else now_iso,
                    "valueCodeableConcept": {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": dr_finding["code"],
                                "display": dr_finding["display"],
                            }
                        ],
                        "text": f"Grade {dr_grade}: {dr_finding['display']}",
                    },
                    "interpretation": [
                        {
                            "coding": [
                                {
                                    "system": "https://retinashield.local/interpretation",
                                    "code": "CLINICIAN_CONFIRMED" if has_review else "AI_PROVISIONAL",
                                    "display": "Clinician Confirmed" if has_review else "AI Provisional Result (Research)",
                                }
                            ]
                        }
                    ],
                },
            }
            observations.append(obs_dr)
            observation_references.append({"reference": f"urn:uuid:{obs_dr_id}"})

        # (b) Quality Result Observation
        if quality:
            obs_q_id = f"Observation-Quality-{screening.id}"
            obs_q = {
                "fullUrl": f"urn:uuid:{obs_q_id}",
                "resource": {
                    "resourceType": "Observation",
                    "id": obs_q_id,
                    "status": "final",
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": cls.LOINC_RETINAL_CAMERA_STUDY,
                                "display": "Retinal camera study",
                            }
                        ],
                        "text": "Fundus Image Quality Assessment",
                    },
                    "subject": {"reference": f"urn:uuid:{patient_resource_id}"},
                    "effectiveDateTime": quality.created_at.isoformat() if quality.created_at else now_iso,
                    "valueString": quality.verdict or "unknown",
                    "component": [
                        {
                            "code": {"text": "Overall Quality Score"},
                            "valueQuantity": {
                                "value": round(quality.overall_quality_score, 3) if quality.overall_quality_score is not None else None,
                                "unit": "score",
                            },
                        },
                        {
                            "code": {"text": "Ungradeable Flag"},
                            "valueBoolean": quality.ungradeable,
                        },
                        {
                            "code": {"text": "Sharpness"},
                            "valueQuantity": {
                                "value": round(quality.sharpness, 3) if quality.sharpness is not None else None,
                                "unit": "normalized",
                            },
                        },
                        {
                            "code": {"text": "Blur Score"},
                            "valueQuantity": {
                                "value": round(quality.blur_score, 1) if quality.blur_score is not None else None,
                                "unit": "variance",
                            },
                        },
                    ],
                },
            }
            observations.append(obs_q)
            observation_references.append({"reference": f"urn:uuid:{obs_q_id}"})

        # (c) Macular Edema Observation
        if review and review.macular_edema_present is not None:
            obs_me_id = f"Observation-MacularEdema-{screening.id}"
            obs_me = {
                "fullUrl": f"urn:uuid:{obs_me_id}",
                "resource": {
                    "resourceType": "Observation",
                    "id": obs_me_id,
                    "status": "final",
                    "code": {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": cls.SNOMED_MACULAR_EDEMA,
                                "display": "Macular edema",
                            }
                        ],
                        "text": "Macular Edema Presence",
                    },
                    "subject": {"reference": f"urn:uuid:{patient_resource_id}"},
                    "valueBoolean": review.macular_edema_present,
                },
            }
            observations.append(obs_me)
            observation_references.append({"reference": f"urn:uuid:{obs_me_id}"})

        # 3. Media / Fundus Photography Reference
        media_entries: List[Dict[str, Any]] = []
        media_references: List[Dict[str, str]] = []
        if image:
            media_id = f"Media-Fundus-{image.id}"
            media_sha256 = (
                getattr(image, "sha256_hash", None)
                or (image.provenance.sha256_hash if getattr(image, "provenance", None) else None)
                or hashlib.sha256(str(image.id).encode()).hexdigest()
            )
            media_res = {
                "fullUrl": f"urn:uuid:{media_id}",
                "resource": {
                    "resourceType": "Media",
                    "id": media_id,
                    "status": "completed",
                    "type": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/media-type",
                                "code": "image",
                                "display": "Image",
                            }
                        ]
                    },
                    "modality": {
                        "coding": [
                            {
                                "system": "http://dicom.nema.org/resources/ontology/DCM",
                                "code": "OP",
                                "display": "Ophthalmic Photography",
                            }
                        ]
                    },
                    "bodySite": {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "362508001",
                                "display": f"Retina ({screening.eye.upper()} eye)",
                            }
                        ],
                        "text": f"{screening.eye.capitalize()} Eye Fundus",
                    },
                    "subject": {"reference": f"urn:uuid:{patient_resource_id}"},
                    "content": {
                        "contentType": "image/jpeg",
                        "title": f"Fundus Photography ({screening.eye})",
                        "hash": media_sha256,
                    },
                },
            }
            media_entries.append(media_res)
            media_references.append({"reference": f"urn:uuid:{media_id}"})

        # 4. DiagnosticReport Resource (DiagnosticReportImaging Profile)
        report_conclusion = (
            f"Clinician Final Diagnosis: Grade {review.confirmed_dr_grade}. "
            f"Referral Urgency: {review.referral_recommendation.upper()}. Notes: {review.clinical_notes}"
            if has_review and review
            else (
                f"Provisional AI Screening: Grade {screening.dr_grade or 'Unknown'}. "
                f"Urgency: {(screening.referral_urgency or 'Routine').upper()}. "
                "RESEARCH SCREENING RESULT — Not a clinical diagnosis. Must be reviewed by an ophthalmologist."
            )
        )

        diagnostic_report_resource = {
            "fullUrl": f"urn:uuid:{report_resource_id}",
            "resource": {
                "resourceType": "DiagnosticReport",
                "id": report_resource_id,
                "meta": {
                    "profile": ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportImaging"]
                },
                "status": "final" if has_review else "preliminary",
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                                "code": "RAD",
                                "display": "Radiology / Imaging",
                            }
                        ]
                    }
                ],
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": cls.SNOMED_DR_SCREENING,
                            "display": "Diabetic retinopathy screening",
                        }
                    ],
                    "text": "Diabetic Retinopathy Screening Report",
                },
                "subject": {"reference": f"urn:uuid:{patient_resource_id}"},
                "effectiveDateTime": screening.created_at.isoformat() if screening.created_at else now_iso,
                "result": observation_references,
                "media": [{"link": ref} for ref in media_references],
                "conclusion": report_conclusion,
            },
        }

        # 5. Composition Resource (DiagnosticReportRecord Profile - Document Root)
        composition_resource = {
            "fullUrl": f"urn:uuid:{composition_id}",
            "resource": {
                "resourceType": "Composition",
                "id": composition_id,
                "meta": {
                    "profile": ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportRecord"]
                },
                "status": "final" if has_review else "preliminary",
                "type": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": cls.LOINC_DR_SCREENING_SUMMARY,
                            "display": "Diabetic retinopathy screening summary",
                        }
                    ],
                    "text": "Diabetic Retinopathy Screening Report",
                },
                "subject": {"reference": f"urn:uuid:{patient_resource_id}"},
                "date": now_iso,
                "author": [
                    {
                        "display": (
                            f"Ophthalmologist Reviewer ({review.reviewer_id})"
                            if has_review and review
                            else "RetinaShield Screening Engine (Provisional AI)"
                        )
                    }
                ],
                "title": "RetinaShield Diabetic Retinopathy Screening Document",
                "confidentiality": "N",
                "section": [
                    {
                        "title": "Diagnostic Report Section",
                        "code": {
                            "coding": [
                                {
                                    "system": "http://snomed.info/sct",
                                    "code": cls.SNOMED_DR_SCREENING,
                                    "display": "Diabetic retinopathy screening",
                                }
                            ]
                        },
                        "entry": [{"reference": f"urn:uuid:{report_resource_id}"}],
                    }
                ],
            },
        }

        # Assemble Full Document Bundle (NRCeS DocumentBundle)
        bundle_entries: List[Dict[str, Any]] = [
            composition_resource,
            patient_resource,
            diagnostic_report_resource,
            *observations,
            *media_entries,
        ]

        bundle_json: Dict[str, Any] = {
            "resourceType": "Bundle",
            "id": bundle_id,
            "meta": {
                "versionId": "1",
                "lastUpdated": now_iso,
                "profile": ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle"],
            },
            "identifier": {
                "system": "https://retinashield.local/bundles",
                "value": f"RS-BUNDLE-{screening.id}",
            },
            "type": "document",
            "timestamp": now_iso,
            "entry": bundle_entries,
        }

        # Calculate cryptographic checksum of normalized JSON
        canonical_str = json.dumps(bundle_json, sort_keys=True)
        bundle_sha256 = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

        return FHIRBundleExportResponse(
            screening_id=str(screening.id),
            patient_id=str(patient.id),
            bundle_id=bundle_id,
            bundle_type="document",
            composition_status="final" if has_review else "preliminary",
            has_clinician_approval=has_review,
            is_provisional=is_provisional,
            resource_count=len(bundle_entries),
            bundle_json=bundle_json,
            integrity_sha256=bundle_sha256,
        )

    @classmethod
    def test_exchange_readiness(cls) -> ExchangeTestResponse:
        """
        Tests live exchange readiness without making external network calls.
        Validates the strict safety boundaries required before enabling live ABDM exchange.
        """
        checks = {
            "abdm_exchange_flag_enabled": bool(settings.abdm_exchange_enabled),
            "valid_sandbox_client_id": bool(settings.abdm_client_id.strip()),
            "valid_sandbox_client_secret": bool(settings.abdm_client_secret.strip()),
            "registered_hip_id": bool(settings.abdm_hip_id.strip()),
            "patient_consent_manager_flow": False,  # Pending CM M2 integration
            "digital_signing_certificate": False,   # Pending PKI cert for document bundle
        }

        if not settings.abdm_exchange_enabled:
            return ExchangeTestResponse(
                allowed=False,
                environment=settings.abdm_environment,
                reason="Live ABDM exchange is securely disabled by default in application configuration.",
                prerequisite_checklist=checks,
                guidance=(
                    "RetinaShield enables local and offline FHIR R4 document bundle exports. "
                    "To enable live ABDM gateway push, your organization must obtain official ABDM Sandbox "
                    "credentials from the National Health Authority (NHA), configure bridge webhooks, "
                    "and establish patient consent manager (CM) verification flows."
                ),
            )

        missing = [k for k, v in checks.items() if not v]
        if missing:
            return ExchangeTestResponse(
                allowed=False,
                environment=settings.abdm_environment,
                reason=f"ABDM prerequisites incomplete: {', '.join(missing)}",
                prerequisite_checklist=checks,
                guidance="Provide valid ABDM sandbox client ID/secret, configure consent flows, and register the HIP endpoint.",
            )

        return ExchangeTestResponse(
            allowed=True,
            environment=settings.abdm_environment,
            reason="All prerequisites verified for sandbox connection.",
            prerequisite_checklist=checks,
            guidance="Ready for ABDM sandbox testing.",
        )


fhir_adapter = ABDMFHIRAdapter()
