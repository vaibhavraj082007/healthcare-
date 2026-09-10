"""
RetinaShield — Conservative Dual-Engine Consistency Layer

Evaluates concordance and resolves clinical discrepancies between:
  1. Engine A: Global DR Severity Classifier (EfficientNet-B0 + Temperature Scaling)
  2. Engine B: Focal Lesion Analysis Branch (YOLOv8 / Candidate Baselines)
  3. Image Quality Assessment (IQA)
  4. Component Availability

Clinical Safety Invariants:
  - A softmax score alone is not clinical certainty.
  - Do not use a simplistic lesion-count-to-grade rule.
  - Absence of detected lesions MUST NEVER downgrade a moderate/severe classifier prediction or referral urgency.
  - Concordant findings are labeled 'Concordant AI findings', strictly never 'Confirmed diagnosis'.
  - Flags disagreement, missing components, ungradeable quality, and high predictive uncertainty for mandatory human review.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.analysis_result import (
    ConfidenceCalibration,
    ConsistencyAnalysis,
    LesionDetectionResult,
    QualityAssessment,
    ReferralRecommendation,
    SeverityClassification,
    StructureAnalysis,
)

logger = logging.getLogger(__name__)

CONSISTENCY_RULES_VERSION = "1.0.0"


class ConsistencyEvaluator:
    """Evaluates multi-engine consistency, enforces clinical safety rules, and generates referral suggestions."""

    def __init__(self, rules_version: str = CONSISTENCY_RULES_VERSION):
        self.rules_version = rules_version

    def evaluate(
        self,
        severity: Optional[SeverityClassification | Dict[str, Any]],
        lesions: Optional[LesionDetectionResult | Dict[str, Any]],
        calibration: Optional[ConfidenceCalibration | Dict[str, Any]],
        iqa: Optional[QualityAssessment | Dict[str, Any]],
        structure: Optional[StructureAnalysis | Dict[str, Any]] = None,
    ) -> Tuple[ConsistencyAnalysis, ReferralRecommendation]:
        """
        Run multi-engine consistency analysis and compute conservative referral suggestion.
        """
        # Unpack / normalize inputs
        sev_dict = severity.dict() if hasattr(severity, "dict") else (severity or {})
        les_dict = lesions.dict() if hasattr(lesions, "dict") else (lesions or {})
        cal_dict = calibration.dict() if hasattr(calibration, "dict") else (calibration or {})
        iqa_dict = iqa.dict() if hasattr(iqa, "dict") else (iqa or {})
        struct_dict = structure.dict() if hasattr(structure, "dict") else (structure or {})

        review_reasons: List[str] = []
        human_review_required = False

        # --- 1. Component Availability Gate ---
        classifier_trained = sev_dict.get("model_trained", False)
        lesion_trained = les_dict.get("model_trained", False)
        lesion_status = les_dict.get("status", "unavailable")

        if not classifier_trained:
            review_reasons.append("DR Severity Classifier is untrained / missing weights")
            human_review_required = True

        if not lesion_trained and lesion_status == "unavailable":
            review_reasons.append("Lesion detector is unavailable / missing weights")
            human_review_required = True

        # --- 2. Image Quality Gate ---
        quality_verdict = iqa_dict.get("overall_quality", "acceptable")
        if quality_verdict == "rejected":
            review_reasons.append("Image rejected by IQA: severe blur, artifact, or out-of-focus aperture")
            human_review_required = True
            consistency = ConsistencyAnalysis(
                consistency_status="quality_compromised",
                finding_label="Ungradeable Image — Automated analysis refused",
                human_review_required=True,
                review_reasons=review_reasons,
                recommended_grade=None,
                recommended_urgency="none",
                rules_version=self.rules_version,
            )
            referral = ReferralRecommendation(
                urgency="none",
                reason="Image is ungradeable. Refusal of autonomous grading. Repeat fundus photography or clinical examination required.",
                suggested_followup_weeks=0,
            )
            return consistency, referral

        if quality_verdict == "poor":
            review_reasons.append("Suboptimal image quality / illumination uniformity may compromise subtle lesion detection")
            human_review_required = True

        # --- 3. Uncertainty Gate ---
        is_uncertain = cal_dict.get("is_uncertain", False)
        if is_uncertain:
            entropy = cal_dict.get("shannon_entropy")
            margin = cal_dict.get("confidence_margin")
            review_reasons.append(
                f"High predictive uncertainty (normalized entropy: {entropy}, margin: {margin})"
            )
            human_review_required = True

        # --- 4. Evaluate Classifier Findings ---
        pred_grade = sev_dict.get("predicted_grade")
        if pred_grade is None or pred_grade < 0 or not classifier_trained:
            # Classifier unable to provide valid grade
            consistency = ConsistencyAnalysis(
                consistency_status="component_unavailable",
                finding_label="Component Unavailable — Clinical review required",
                human_review_required=True,
                review_reasons=review_reasons,
                recommended_grade=None,
                recommended_urgency="none",
                rules_version=self.rules_version,
            )
            referral = ReferralRecommendation(
                urgency="none",
                reason="Pipeline components unavailable or uncalibrated. Mandatory in-person ophthalmologist review required.",
                suggested_followup_weeks=0,
            )
            return consistency, referral

        # --- 5. Evaluate Lesion Findings ---
        detected_lesions = les_dict.get("detections", [])
        counts = les_dict.get("model_estimated_count", {})

        # Check for hallmark severe lesions
        has_nv = counts.get("neovascularization", 0) > 0 or any(d.get("lesion_type") == "neovascularization" for d in detected_lesions)
        he_count = counts.get("hemorrhage", 0) + sum(1 for d in detected_lesions if d.get("lesion_type") == "hemorrhage")
        ma_count = counts.get("microaneurysm", 0) + sum(1 for d in detected_lesions if d.get("lesion_type") == "microaneurysm")
        ex_count = counts.get("hard_exudate", 0) + sum(1 for d in detected_lesions if d.get("lesion_type") == "hard_exudate")
        cws_count = counts.get("cotton_wool_spot", 0) + counts.get("soft_exudate", 0) + sum(1 for d in detected_lesions if d.get("lesion_type") in ["cotton_wool_spot", "soft_exudate"])
        total_lesions = len(detected_lesions)

        # Macula involvement check (Hard exudates near fovea)
        macula_involved = False
        fovea_info = struct_dict.get("fovea") or struct_dict.get("macula") or {}
        if fovea_info.get("detected") and (ex_count > 0 or he_count > 0):
            fx = fovea_info.get("center_x")
            fy = fovea_info.get("center_y")
            fr = fovea_info.get("radius", 25) or 25
            if fx is not None and fy is not None:
                for d in detected_lesions:
                    bx = d.get("bbox", {})
                    cx = (bx.get("x_min", 0) + bx.get("x_max", 0)) / 2.0
                    cy = (bx.get("y_min", 0) + bx.get("y_max", 0)) / 2.0
                    dist = ((cx - fx) ** 2 + (cy - fy) ** 2) ** 0.5
                    if dist < 2.0 * fr:  # Within 1 disc diameter of fovea
                        macula_involved = True
                        break

        # --- 6. Conservative Cross-Engine Decision Rules ---
        consistency_status = "concordant"
        finding_label = "Concordant AI findings"
        recommended_grade = pred_grade

        # RULE 6A: Classifier High (Grade >= 2), Lesions Zero -> DISCORDANT CLASSIFIER HIGH
        # CRITICAL SAFETY: Never downgrade severity or referral priority when classifier indicates disease
        if pred_grade >= 2 and total_lesions == 0:
            consistency_status = "discordant_classifier_high"
            finding_label = "Discordant Findings — Global classifier elevated but lesion detector empty"
            review_reasons.append(
                f"Disagreement: Classifier predicts Grade {pred_grade} ({sev_dict.get('grade_label', '')}) "
                f"but lesion detector found no candidate boxes. Classifier finding conservatively retained."
            )
            human_review_required = True
            recommended_grade = pred_grade  # Retain high grade

        # RULE 6B: Classifier Low (Grade 0), Hallmark Lesions Present -> DISCORDANT LESIONS HIGH
        # ESCALATION: Upgrade review priority if significant pathology was spotted by lesion branch
        elif pred_grade == 0 and (has_nv or he_count >= 2 or ex_count >= 2 or cws_count >= 2):
            consistency_status = "discordant_lesions_high"
            finding_label = "Discordant Findings — Classifier predicts No DR but hallmark lesions detected"
            review_reasons.append(
                f"Disagreement: Global classifier predicted Grade 0 (No DR), but focal lesions detected "
                f"(NV: {int(has_nv)}, HE: {he_count}, EX: {ex_count}, CWS: {cws_count}). Escalating for review."
            )
            human_review_required = True
            # Escalate grade: PDR if NV, else Moderate (2)
            recommended_grade = 4 if has_nv else 2

        # RULE 6C: Classifier Grade 1, High-Grade Lesions (e.g. NV or Multiple HE) -> ESCALATE
        elif pred_grade == 1 and (has_nv or he_count >= 4):
            consistency_status = "discordant_lesions_high"
            finding_label = "Discordant Findings — Severe focal lesions detected exceeding Grade 1"
            review_reasons.append("Disagreement: High-grade focal lesions exceed Mild NPDR classification.")
            human_review_required = True
            recommended_grade = 4 if has_nv else 3

        # RULE 6D: Concordance
        else:
            if is_uncertain:
                consistency_status = "uncertain_prediction"
                finding_label = "Borderline Prediction — Expert validation suggested"
                human_review_required = True
            else:
                consistency_status = "concordant"
                finding_label = "Concordant AI findings"

        # --- 7. Referral Recommendation Determination ---
        urgency, reason, followup_weeks = self._compute_referral_urgency(recommended_grade, macula_involved, review_reasons)

        consistency = ConsistencyAnalysis(
            consistency_status=consistency_status,
            finding_label=finding_label,
            human_review_required=human_review_required,
            review_reasons=review_reasons,
            recommended_grade=recommended_grade,
            recommended_urgency=urgency,
            rules_version=self.rules_version,
        )

        referral = ReferralRecommendation(
            urgency=urgency,
            reason=reason,
            suggested_followup_weeks=followup_weeks,
        )

        return consistency, referral

    def _compute_referral_urgency(
        self,
        grade: int,
        macula_involved: bool,
        review_reasons: List[str],
    ) -> Tuple[str, str, int]:
        """Map conservative recommended grade and macula status to referral urgency."""
        if grade == 0:
            urgency = "none"
            reason = "No apparent diabetic retinopathy detected. Routine annual screening recommended."
            weeks = 52
        elif grade == 1:
            urgency = "routine"
            reason = "Mild NPDR detected (microaneurysms only). Referral for ophthalmological evaluation within 6 months."
            weeks = 26
        elif grade == 2:
            urgency = "priority"
            reason = "Moderate NPDR detected. Priority referral for ophthalmological evaluation within 3 months."
            weeks = 13
        elif grade == 3:
            urgency = "priority"
            reason = "Severe NPDR detected (4-2-1 criteria). Priority referral to retina specialist within 2-4 weeks."
            weeks = 4
        elif grade == 4:
            urgency = "urgent"
            reason = "Proliferative Diabetic Retinopathy (PDR) detected. URGENT referral to retina specialist within 1 week."
            weeks = 1
        else:
            urgency = "none"
            reason = "Grade undetermined. Clinical evaluation required."
            weeks = 0

        # Macular escalation
        if macula_involved:
            reason += " Macular involvement / exudate proximity suspected — consider OCT evaluation."
            if urgency in ["routine", "priority"]:
                urgency = "urgent"
                weeks = min(weeks, 2)

        # Append review triggers if human review is flagged
        if review_reasons:
            reason += f" [Human Review Flags: {'; '.join(review_reasons[:2])}]"

        return urgency, reason, weeks
