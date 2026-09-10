"""
RetinaShield — ABDM & HL7 FHIR R4 Interoperability Adapter Test Suite

Tests:
1. FHIR R4 Document Bundle generation adhering to ABDM NRCeS profiles.
2. LOINC & SNOMED CT clinical coding mappings for DR screening and IQA.
3. Cryptographic SHA-256 integrity hash verification.
4. Optional nature of national IDs (no mandatory Aadhaar / ABHA).
5. Safe disablement of live ABDM exchange unless authorized sandbox credentials and consent flows exist.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from app.models.screening import Screening, ScreeningImage
from app.models.patient import Patient
from app.models.clinical import QualityResult, ModelOutput, ClinicianReview
from app.services.fhir_adapter import ABDMFHIRAdapter


class TestFHIRABDMAdapter(unittest.TestCase):

    def setUp(self):
        self.patient = Patient(
            id=uuid.uuid4(),
            first_name="Sunita",
            last_name="Sharma",
            facility_id="PHC-DEV-01",
        )
        self.screening = Screening(
            id=uuid.uuid4(),
            patient_id=self.patient.id,
            facility_id="PHC-DEV-01",
            eye="right",
            status="completed",
            dr_grade=2,
            referral_urgency="priority",
            created_at=datetime.now(timezone.utc),
        )
        self.quality = QualityResult(
            image_id=uuid.uuid4(),
            screening_id=self.screening.id,
            verdict="good",
            ungradeable=False,
            overall_quality_score=0.88,
            sharpness=0.82,
            blur_score=195.0,
            created_at=datetime.now(timezone.utc),
        )
        self.model_output = ModelOutput(
            screening_id=self.screening.id,
            model_name="RetinaShield-EfficientNetB0",
            model_version="1.0.0",
            predicted_dr_grade=2,
            confidence=0.85,
            created_at=datetime.now(timezone.utc),
        )

    def test_provisional_fhir_document_bundle_generation(self):
        """Verify generation of compliant FHIR R4 Document Bundle for provisional (unreviewed) screening."""
        bundle_resp = ABDMFHIRAdapter.generate_bundle(
            screening=self.screening,
            patient=self.patient,
            quality=self.quality,
            model_output=self.model_output,
            review=None,
        )

        self.assertTrue(bundle_resp.is_provisional)
        self.assertFalse(bundle_resp.has_clinician_approval)
        self.assertEqual(bundle_resp.composition_status, "preliminary")
        self.assertIsNotNone(bundle_resp.integrity_sha256)

        bundle = bundle_resp.bundle_json
        self.assertEqual(bundle["resourceType"], "Bundle")
        self.assertEqual(bundle["type"], "document")
        self.assertIn("https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle", bundle["meta"]["profile"])

        # Validate entries
        entries = bundle["entry"]
        resource_types = [e["resource"]["resourceType"] for e in entries]
        self.assertIn("Composition", resource_types)
        self.assertIn("Patient", resource_types)
        self.assertIn("DiagnosticReport", resource_types)
        self.assertIn("Observation", resource_types)

        # Composition checks
        comp = next(e["resource"] for e in entries if e["resource"]["resourceType"] == "Composition")
        self.assertEqual(comp["status"], "preliminary")
        self.assertEqual(comp["type"]["coding"][0]["code"], ABDMFHIRAdapter.LOINC_DR_SCREENING_SUMMARY)

        # DiagnosticReport checks
        report = next(e["resource"] for e in entries if e["resource"]["resourceType"] == "DiagnosticReport")
        self.assertEqual(report["status"], "preliminary")
        self.assertIn("RESEARCH SCREENING RESULT", report["conclusion"])
        self.assertIn("https://nrces.in/ndhm/fhir/r4/StructureDefinition/DiagnosticReportImaging", report["meta"]["profile"])

        # Patient checks: verify minimal details without mandatory ABHA
        patient_res = next(e["resource"] for e in entries if e["resource"]["resourceType"] == "Patient")
        self.assertIn("https://nrces.in/ndhm/fhir/r4/StructureDefinition/Patient", patient_res["meta"]["profile"])
        # No ABHA forced
        systems = [i["system"] for i in patient_res["identifier"]]
        self.assertIn("https://retinashield.local/patient-id", systems)

        # Observation checks
        observations = [e["resource"] for e in entries if e["resource"]["resourceType"] == "Observation"]
        self.assertGreaterEqual(len(observations), 2)  # DR grade + Quality

        dr_obs = next(o for o in observations if o["code"]["coding"][0]["code"] == ABDMFHIRAdapter.SNOMED_DR_SCREENING)
        self.assertEqual(dr_obs["valueCodeableConcept"]["coding"][0]["code"], "312904007")  # Moderate NPDR
        self.assertEqual(dr_obs["interpretation"][0]["coding"][0]["code"], "AI_PROVISIONAL")

    def test_clinician_approved_fhir_bundle(self):
        """Verify final status and clinician findings in approved screening export."""
        review = ClinicianReview(
            screening_id=self.screening.id,
            reviewer_id=uuid.uuid4(),
            confirmed_dr_grade=3,
            macular_edema_present=True,
            referral_recommendation="urgent",
            clinical_notes="Severe NPDR with macular involvement. Immediate tertiary referral advised.",
            status="final",
        )

        bundle_resp = ABDMFHIRAdapter.generate_bundle(
            screening=self.screening,
            patient=self.patient,
            quality=self.quality,
            model_output=self.model_output,
            review=review,
        )

        self.assertFalse(bundle_resp.is_provisional)
        self.assertTrue(bundle_resp.has_clinician_approval)
        self.assertEqual(bundle_resp.composition_status, "final")

        bundle = bundle_resp.bundle_json
        entries = bundle["entry"]

        # Composition status must be final
        comp = next(e["resource"] for e in entries if e["resource"]["resourceType"] == "Composition")
        self.assertEqual(comp["status"], "final")

        # DiagnosticReport status must be final
        report = next(e["resource"] for e in entries if e["resource"]["resourceType"] == "DiagnosticReport")
        self.assertEqual(report["status"], "final")
        self.assertIn("Clinician Final Diagnosis: Grade 3", report["conclusion"])

        # Check Macular Edema observation
        observations = [e["resource"] for e in entries if e["resource"]["resourceType"] == "Observation"]
        me_obs = next(o for o in observations if o["code"]["coding"][0]["code"] == ABDMFHIRAdapter.SNOMED_MACULAR_EDEMA)
        self.assertTrue(me_obs["valueBoolean"])

    def test_safe_disablement_of_live_abdm_exchange(self):
        """Verify live ABDM exchange is securely disabled by default and provides prerequisite diagnostics."""
        test_result = ABDMFHIRAdapter.test_exchange_readiness()

        self.assertFalse(test_result.allowed)
        self.assertIn("securely disabled by default", test_result.reason)
        self.assertFalse(test_result.prerequisite_checklist["abdm_exchange_flag_enabled"])
        self.assertIn("National Health Authority (NHA)", test_result.guidance)

    def test_interop_status_metadata(self):
        """Verify status endpoint documents supported capabilities and remaining integration milestones."""
        status = ABDMFHIRAdapter.get_interop_status()

        self.assertEqual(status.fhir_version, "4.0.1")
        self.assertFalse(status.abdm_exchange_enabled)
        self.assertFalse(status.abha_linking_enabled)

        # Profiles list
        profile_names = [p.profile_name for p in status.supported_profiles]
        self.assertIn("DocumentBundle", profile_names)
        self.assertIn("DiagnosticReportRecord (Composition)", profile_names)
        self.assertIn("DiagnosticReportImaging", profile_names)

        # Milestones check
        milestones = [req.milestone for req in status.remaining_integration_requirements]
        self.assertIn("M1", milestones)
        self.assertIn("M2", milestones)
        self.assertIn("M3", milestones)

        # Safeguard text
        self.assertIn("OPTIONAL and NEVER mandatory", status.safeguards)


if __name__ == "__main__":
    unittest.main()
