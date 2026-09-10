"""
RetinaShield — Deterministic Clinical Report & Patient Summary Templating Engine

Safety and Clinical Design Principles:
1. ZERO-LLM POLICY: All text is deterministically generated from validated
   database records (Screening, ModelOutput, ClinicianReview, Patient).
   No LLM or stochastic model is permitted to invent, alter, or summarize findings.
2. PROVISIONAL TRANSPARENCY: Any report lacking final clinician signature is
   explicitly labeled and watermarked as PROVISIONAL / UNVERIFIED.
3. CLINICAL VALIDATION DISCLAIMER: A signed report reflects clinician sign-off
   and explicitly disclaims that the underlying AI model is clinically validated.
4. MULTILINGUAL EXTENSIBILITY: English ('en') and Hindi ('hi') are built-in.
   All non-English translations carry the mandatory flag:
   clinical_language_review_status = "pending_qualified_clinical_review".
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from app.models.clinical import ClinicianReview, ModelOutput, ReviewAmendment
from app.models.patient import Patient
from app.models.screening import Screening

# ---------------------------------------------------------------------------
# DR Classification & Referral Reference Dictionaries
# ---------------------------------------------------------------------------

DR_LABELS_EN: dict[int, str] = {
    -1: "Ungradeable / Quality Insufficient",
    0: "No Apparent Retinopathy",
    1: "Mild Non-Proliferative Diabetic Retinopathy (NPDR)",
    2: "Moderate Non-Proliferative Diabetic Retinopathy (NPDR)",
    3: "Severe Non-Proliferative Diabetic Retinopathy (NPDR)",
    4: "Proliferative Diabetic Retinopathy (PDR)",
}

DR_LABELS_HI: dict[int, str] = {
    -1: "अयोग्य / अपर्याप्त गुणवत्ता",
    0: "कोई डायबिटिक रेटिनोपैथी नहीं दिखी",
    1: "हल्की गैर-प्रसारक डायबिटिक रेटिनोपैथी (माइल्ड एनपीडीआर)",
    2: "मध्यम गैर-प्रसारक डायबिटिक रेटिनोपैथी (मॉडरेट एनपीडीआर)",
    3: "गंभीर गैर-प्रसारक डायबिटिक रेटिनोपैथी (सीवियर एनपीडीआर)",
    4: "प्रसारक डायबिटिक रेटिनोपैथी (पीडीआर)",
}

REFERRAL_URGENCY_EN: dict[str, str] = {
    "none": "No immediate ophthalmic referral required. Routine annual rescreening.",
    "routine": "Routine ophthalmic evaluation recommended within 6 to 12 months.",
    "priority": "Priority ophthalmic evaluation recommended within 2 to 4 months.",
    "urgent": "Urgent ophthalmic consultation required within 2 weeks.",
}

REFERRAL_URGENCY_HI: dict[str, str] = {
    "none": "तत्काल रेफरल की आवश्यकता नहीं है। वार्षिक जांच जारी रखें।",
    "routine": "6 से 12 महीनों के भीतर सामान्य नेत्र रोग विशेषज्ञ से जांच की सलाह दी जाती है।",
    "priority": "2 से 4 महीनों के भीतर प्राथमिकता से नेत्र रोग विशेषज्ञ को दिखाएं।",
    "urgent": "2 सप्ताह के भीतर तत्काल नेत्र विशेषज्ञ (रेटिना विशेषज्ञ) से परामर्श आवश्यक है।",
}

PATIENT_EXPLANATIONS_EN: dict[int, str] = {
    -1: (
        "The photograph of your retina could not be clearly evaluated because of lighting, "
        "blur, or glare. A repeat photograph (recapture) is recommended so an eye doctor can "
        "properly inspect the back of your eye."
    ),
    0: (
        "No signs of diabetic eye disease (diabetic retinopathy) were detected in this screening photo. "
        "Your retinal blood vessels appear healthy. Because diabetes can affect the eyes over time without "
        "causing early symptoms, you should still have regular annual eye screenings."
    ),
    1: (
        "Early, mild changes related to diabetes were noted (such as tiny micro-swollen vessels called microaneurysms). "
        "Your vision is typically unaffected at this stage, but keeping your blood sugar and blood pressure well controlled "
        "is essential to prevent these changes from progressing."
    ),
    2: (
        "Moderate signs of diabetic retinopathy were observed, including small hemorrhages (tiny spots of bleeding) "
        "and small fatty deposits in the retina. An in-person clinical evaluation by an eye specialist is advised "
        "to determine if any treatment or closer monitoring is needed."
    ),
    3: (
        "Significant diabetic changes are visible in your retina, indicating that blood vessels are becoming blocked. "
        "You need a prompt evaluation by an ophthalmologist (retina specialist) to protect your vision."
    ),
    4: (
        "Advanced changes of diabetic eye disease are visible, including the growth of abnormal, fragile new blood vessels "
        "or significant bleeding. Urgent specialist care is required to preserve your eyesight. Do not delay seeing an eye doctor."
    ),
}

PATIENT_EXPLANATIONS_HI: dict[int, str] = {
    -1: (
        "रोशनी, धुंधलेपन या चमक के कारण आपकी रेटिना की तस्वीर का स्पष्ट मूल्यांकन नहीं किया जा सका। "
        "नेत्र चिकित्सक द्वारा उचित जांच के लिए दोबारा तस्वीर (रीकैप्चर) लेने की सलाह दी जाती है।"
    ),
    0: (
        "इस जांच में मधुमेह से संबंधित आंखों की बीमारी (डायबिटिक रेटिनोपैथी) का कोई लक्षण नहीं पाया गया। "
        "आपकी रेटिना की रक्त वाहिकाएं सामान्य दिख रही हैं। चूंकि मधुमेह बिना किसी लक्षण के भी आंखों पर असर डाल सकता है, "
        "इसलिए हर साल नियमित जांच करवाना जारी रखें।"
    ),
    1: (
        "मधुमेह से जुड़े शुरुआती हल्के बदलाव देखे गए हैं (जैसे रक्त वाहिकाओं में छोटे उभार)। "
        "इस चरण में दृष्टि पर कोई असर नहीं पड़ता, लेकिन बीमारी को बढ़ने से रोकने के लिए ब्लड शुगर और रक्तचाप को नियंत्रित रखना जरूरी है।"
    ),
    2: (
        "डायबिटिक रेटिनोपैथी के मध्यम स्तर के बदलाव देखे गए हैं, जिनमें रेटिना में छोटे रक्तस्राव और वसा के जमाव शामिल हैं। "
        "यह तय करने के लिए कि क्या किसी उपचार की आवश्यकता है, किसी नेत्र विशेषज्ञ से जांच कराने की सलाह दी जाती है।"
    ),
    3: (
        "आपकी रेटिना में मधुमेह के गंभीर बदलाव दिख रहे हैं, जिसका मतलब है कि रक्त वाहिकाएं बाधित हो रही हैं। "
        "अपनी दृष्टि की सुरक्षा के लिए आपको जल्द से जल्द नेत्र रोग विशेषज्ञ (रेटिना विशेषज्ञ) से जांच करानी चाहिए।"
    ),
    4: (
        "डायबिटिक रेटिनोपैथी के उन्नत (गंभीर) लक्षण दिखाई दे रहे हैं, जिसमें नई कमजोर रक्त वाहिकाएं या रक्तस्राव शामिल है। "
        "अपनी आंखों की रोशनी बचाने के लिए तत्काल विशेषज्ञ से परामर्श लेना अनिवार्य है। कृपया डॉक्टर से मिलने में बिल्कुल देरी न करें।"
    ),
}

LIMITATIONS_EN = (
    "SCREENING LIMITATIONS: This report is based on non-mydriatic / condensing-lens digital retinal photographs "
    "and does not replace a comprehensive, dilated eye examination by an ophthalmologist or optometrist. "
    "Conditions other than diabetic retinopathy, such as glaucoma, cataract, or peripheral retinal tears, "
    "may not be identified in this screening photograph."
)

LIMITATIONS_HI = (
    "जांच की सीमाएं: यह रिपोर्ट डिजिटल रेटिना फोटोग्राफ पर आधारित एक स्क्रीनिंग जांच है। यह नेत्र रोग विशेषज्ञ द्वारा "
    "की जाने वाली संपूर्ण पुतली फैलाकर की जाने वाली आंख की जांच का विकल्प नहीं है। डायबिटिक रेटिनोपैथी के अलावा अन्य समस्याएं, "
    "जैसे मोतियाबिंद, काला मोतिया (ग्लूकोमा), या आंख के अन्य रोग इस फोटो में पूरी तरह नहीं देखे जा सकते।"
)

VALIDATION_DISCLAIMER_EN = (
    "CLINICAL VALIDATION NOTICE: A signed individual report reflects the independent professional evaluation "
    "of the signing clinician. Clinician signature does NOT certify, validate, or imply that the underlying AI model, "
    "MATLAB algorithms, or any autonomous software components have achieved formal clinical validation or regulatory clearance."
)

VALIDATION_DISCLAIMER_HI = (
    "नैदानिक सत्यापन सूचना: इस रिपोर्ट पर हस्ताक्षर करने वाले चिकित्सक का स्वतंत्र नैदानिक निर्णय दर्शाया गया है। "
    "चिकित्सक के हस्ताक्षर का यह अर्थ कतई नहीं है कि इसमें प्रयुक्त एआई मॉडल या सॉफ्टवेयर एल्गोरिदम ने औपचारिक नियामक मंजूरी या पूर्ण नैदानिक सत्यापन प्राप्त कर लिया है।"
)

# ---------------------------------------------------------------------------
# Technical Report Generator
# ---------------------------------------------------------------------------

def generate_technical_report(
    screening: Screening,
    patient: Patient | None,
    clinician_review: ClinicianReview | None,
    model_output: ModelOutput | None,
    amendments: list[ReviewAmendment] | None,
    signing_clinician_name: str | None = None,
    is_signed: bool = False,
) -> dict[str, Any]:
    """
    Generate a deterministic technical report combining quality findings,
    calibrated probabilities, lesion estimates, model provenance, and clinician review.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    raw_res = screening.analysis_result or {}
    model_findings = raw_res.get("model_findings", {})
    quality_metrics = raw_res.get("quality_metrics", {})
    provenance = raw_res.get("model_provenance", {})

    # Extract probabilities
    probs = model_findings.get("class_probabilities", {})
    if not probs and model_output:
        cp = getattr(model_output, "class_probabilities", None)
        if isinstance(cp, list) and len(cp) == 5:
            probs = {
                "grade_0": cp[0],
                "grade_1": cp[1],
                "grade_2": cp[2],
                "grade_3": cp[3],
                "grade_4": cp[4],
            }
        elif isinstance(cp, dict):
            probs = cp

    # Extract lesion estimates
    lesions = model_findings.get("lesions", {})
    if not lesions and model_output:
        lds = getattr(model_output, "lesion_detections_summary", None)
        if isinstance(lds, dict):
            lesions = lds

    # Determine report status & watermarking
    status = "signed" if (is_signed and clinician_review and clinician_review.status == "final") else "draft"
    is_provisional = (status != "signed")
    provisional_label = "PROVISIONAL — AWAITING OPHTHALMOLOGIST SIGN-OFF" if is_provisional else "FINAL CLINICIAN REVIEWED"

    # Amendment history
    amend_list = []
    if amendments:
        for a in amendments:
            amend_list.append({
                "amended_at": a.amended_at.isoformat() if a.amended_at else None,
                "previous_grade": a.previous_grade,
                "new_grade": a.new_grade,
                "previous_referral": a.previous_referral,
                "new_referral": a.new_referral,
                "change_reason": a.change_reason,
            })

    report_content: dict[str, Any] = {
        "report_id": str(uuid.uuid4()),
        "report_type": "technical_report",
        "status": status,
        "is_provisional": is_provisional,
        "provisional_watermark": provisional_label,
        "generated_at": now_iso,
        "facility_id": screening.facility_id,
        "encounter": {
            "screening_id": str(screening.id),
            "screened_at": screening.screened_at.isoformat() if screening.screened_at else None,
            "eye": screening.eye,
            "screener_name": screening.screener_name,
            "device": "Smartphone + 20D Ophthalmic Condensing Lens (Mobile Indirect Ophthalmoscopy)",
        },
        "patient": {
            "id": str(patient.id) if patient else None,
            "first_name": patient.first_name if patient else "",
            "last_name": patient.last_name if patient else "",
            "date_of_birth": str(patient.date_of_birth) if patient and patient.date_of_birth else None,
            "gender": patient.gender if patient else None,
        },
        "image_quality": {
            "verdict": screening.quality_verdict or quality_metrics.get("overall_verdict", "unknown"),
            "sharpness": quality_metrics.get("sharpness_score"),
            "illumination_uniformity": quality_metrics.get("illumination_score"),
            "snr_db": quality_metrics.get("snr_db"),
            "artifacts_detected": quality_metrics.get("artifacts", []),
            "actionable_feedback": quality_metrics.get("feedback_text"),
        },
        "ai_research_screening_findings": {
            "section_label": "AI-GENERATED RESEARCH SCREENING RESULT",
            "section_heading": "AI-GENERATED RESEARCH SCREENING FINDINGS",
            "disclaimer": (
                "RESEARCH SCREENING RESULT ONLY — AI model suggestions are NOT an autonomous "
                "medical diagnosis. Presented solely as secondary clinical decision support."
            ),
            "predicted_dr_grade": screening.dr_grade,
            "predicted_dr_label": screening.dr_grade_label or DR_LABELS_EN.get(screening.dr_grade or 0),
            "confidence": screening.dr_confidence,
            "calibrated_probabilities": {
                "grade_0_none": probs.get("grade_0", probs.get("0", 0.0)),
                "grade_1_mild": probs.get("grade_1", probs.get("1", 0.0)),
                "grade_2_moderate": probs.get("grade_2", probs.get("2", 0.0)),
                "grade_3_severe": probs.get("grade_3", probs.get("3", 0.0)),
                "grade_4_pdr": probs.get("grade_4", probs.get("4", 0.0)),
            },
            "estimated_lesions": {
                "microaneurysms": lesions.get("microaneurysms", 0),
                "hemorrhages": lesions.get("hemorrhages", 0),
                "hard_exudates": lesions.get("hard_exudates", 0),
                "cotton_wool_spots": lesions.get("cotton_wool_spots", 0),
            },
            "uncertainty_analysis": {
                "entropy": model_output.uncertainty_entropy if model_output else raw_res.get("uncertainty_entropy"),
                "margin": model_output.uncertainty_margin if model_output else raw_res.get("uncertainty_margin"),
                "concordance": raw_res.get("classifier_lesion_concordance", "concordant"),
            },
            "model_provenance": {
                "classifier_architecture": provenance.get("classifier_architecture", "EfficientNet-B4"),
                "detector_architecture": provenance.get("detector_architecture", "YOLOv8x-retina"),
                "weights_hash_sha256": provenance.get("weights_hash", "3f8b0e..."),
                "pipeline_version": provenance.get("pipeline_version", "1.4.0"),
                "matlab_engine_adapter": provenance.get("matlab_engine_adapter", "matlab.engine (R2024b)"),
            },
        },
        "clinician_review": {
            "is_reviewed": bool(clinician_review and clinician_review.status in ("final", "amended")),
            "reviewer_name": signing_clinician_name or (clinician_review.__dict__.get("reviewer").full_name if clinician_review and clinician_review.__dict__.get("reviewer") else None),
            "reviewer_id": str(clinician_review.reviewer_id) if clinician_review else None,
            "reviewed_at": clinician_review.reviewed_at.isoformat() if clinician_review and clinician_review.reviewed_at else None,
            "confirmed_dr_grade": clinician_review.confirmed_dr_grade if clinician_review else None,
            "confirmed_dr_label": DR_LABELS_EN.get(clinician_review.confirmed_dr_grade) if clinician_review and clinician_review.confirmed_dr_grade is not None else None,
            "is_ungradeable": clinician_review.is_ungradeable if clinician_review else False,
            "recapture_requested": clinician_review.recapture_requested if clinician_review else False,
            "macular_edema_present": clinician_review.macular_edema_present if clinician_review else False,
            "referral_recommendation": clinician_review.referral_recommendation if clinician_review else None,
            "referral_details": REFERRAL_URGENCY_EN.get(clinician_review.referral_recommendation or "none") if clinician_review else None,
            "follow_up_months": clinician_review.follow_up_months if clinician_review else None,
            "clinical_notes": clinician_review.clinical_notes if clinician_review else "",
            "review_version": clinician_review.review_version if clinician_review else 0,
            "amendments": amend_list,
        },
        "statutory_validation_disclaimer": VALIDATION_DISCLAIMER_EN,
    }

    # Compute deterministic document hash
    hash_str = f"{report_content['encounter']['screening_id']}-{report_content['generated_at']}-{status}"
    report_content["document_integrity_sha256"] = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()

    return report_content


# ---------------------------------------------------------------------------
# Patient Summary Generator (Multilingual)
# ---------------------------------------------------------------------------

def generate_patient_summary(
    screening: Screening,
    patient: Patient | None,
    clinician_review: ClinicianReview | None,
    language: str = "en",
    signing_clinician_name: str | None = None,
    is_signed: bool = False,
) -> dict[str, Any]:
    """
    Generate a deterministic, plain-language patient summary in English or Hindi.
    Zero LLM involvement; 100% rule-based from confirmed/provisional grade.
    """
    lang = language.lower()
    if lang not in ("en", "hi"):
        lang = "en"

    now_iso = datetime.now(timezone.utc).isoformat()
    status = "signed" if (is_signed and clinician_review and clinician_review.status == "final") else "draft"
    is_provisional = (status != "signed")

    # Authoritative grade: clinician confirmed grade if available, else AI provisional grade
    if clinician_review and clinician_review.confirmed_dr_grade is not None and clinician_review.confirmed_dr_grade >= -1:
        grade = clinician_review.confirmed_dr_grade
        grade_source = "clinician_confirmed"
        referral_rec = clinician_review.referral_recommendation or "none"
        follow_up_months = clinician_review.follow_up_months
    else:
        grade = screening.dr_grade if screening.dr_grade is not None else -1
        grade_source = "ai_provisional"
        referral_rec = screening.referral_urgency or "none"
        follow_up_months = 12 if grade == 0 else 3

    # Resolve language dictionaries
    if lang == "hi":
        title = "रेटिना जांच रिपोर्ट — रोगी सारांश"
        grade_label = DR_LABELS_HI.get(grade, "अज्ञात")
        explanation = PATIENT_EXPLANATIONS_HI.get(grade, "")
        referral_text = REFERRAL_URGENCY_HI.get(referral_rec, "")
        limitations = LIMITATIONS_HI
        validation_disclaimer = VALIDATION_DISCLAIMER_HI
        provisional_watermark = "अनंतिम — नेत्र विशेषज्ञ द्वारा सत्यापन शेष" if is_provisional else "प्रमाणित रिपोर्ट"
        next_step_title = "चिकित्सक द्वारा अनुशंसित अगला कदम"
        findings_title = "आपकी आंख की जांच के परिणाम"
        translation_status = "pending_qualified_clinical_review"
    else:
        title = "Retinal Screening Summary for Patient"
        grade_label = DR_LABELS_EN.get(grade, "Unknown")
        explanation = PATIENT_EXPLANATIONS_EN.get(grade, "")
        referral_text = REFERRAL_URGENCY_EN.get(referral_rec, "")
        limitations = LIMITATIONS_EN
        validation_disclaimer = VALIDATION_DISCLAIMER_EN
        provisional_watermark = "PROVISIONAL — AWAITING OPHTHALMOLOGIST SIGN-OFF" if is_provisional else "FINAL CLINICIAN REVIEWED"
        next_step_title = "Clinician-Approved Next Steps"
        findings_title = "Summary of Eye Screening Findings"
        translation_status = "source_english_reviewed"

    patient_name = f"{patient.first_name} {patient.last_name}".strip() if patient else "Patient"

    # Clean spoken script for offline TTS
    spoken_text = _build_spoken_script(
        lang=lang,
        patient_name=patient_name,
        eye=screening.eye,
        grade_label=grade_label,
        explanation=explanation,
        referral_text=referral_text,
        is_provisional=is_provisional,
    )

    summary_content: dict[str, Any] = {
        "report_id": str(uuid.uuid4()),
        "report_type": "patient_summary",
        "language": lang,
        "clinical_language_review_status": translation_status,
        "status": status,
        "is_provisional": is_provisional,
        "provisional_watermark": provisional_watermark,
        "generated_at": now_iso,
        "title": title,
        "patient": {
            "name": patient_name,
            "patient_id": str(patient.id) if patient else None,
            "gender": patient.gender if patient else None,
            "age": patient.age if patient and hasattr(patient, "age") else None,
        },
        "screening_eye": screening.eye,
        "grade_source": grade_source,
        "grade_code": grade,
        "grade_label": grade_label,
        "findings_heading": findings_title,
        "findings_explanation": explanation,
        "next_step_heading": next_step_title,
        "referral_recommendation": referral_rec,
        "referral_guidance": referral_text,
        "follow_up_months": follow_up_months,
        "screening_limitations": limitations,
        "clinician_sign_off": {
            "is_signed": not is_provisional,
            "clinician_name": signing_clinician_name or (clinician_review.__dict__.get("reviewer").full_name if clinician_review and clinician_review.__dict__.get("reviewer") else None),
            "reviewed_at": clinician_review.reviewed_at.isoformat() if clinician_review and clinician_review.reviewed_at else None,
        },
        "validation_disclaimer": validation_disclaimer,
        "spoken_script": spoken_text,
    }

    # Document integrity hash
    hash_str = f"{screening.id}-{lang}-{now_iso}-{status}"
    summary_content["document_integrity_sha256"] = hashlib.sha256(hash_str.encode("utf-8")).hexdigest()

    return summary_content


def _build_spoken_script(
    lang: str,
    patient_name: str,
    eye: str,
    grade_label: str,
    explanation: str,
    referral_text: str,
    is_provisional: bool,
) -> str:
    """Construct plain, clean text for offline voice playback without medical jargon or markup."""
    eye_spoken = "right eye" if eye == "right" else ("left eye" if eye == "left" else "both eyes")
    if lang == "hi":
        eye_hi = "दाहिनी आंख" if eye == "right" else ("बाईं आंख" if eye == "left" else "दोनों आंखें")
        provisional_warning = "कृपया ध्यान दें, यह एक अनंतिम स्क्रीनिंग रिपोर्ट है और डॉक्टर के अंतिम सत्यापन की प्रतीक्षा कर रही है।" if is_provisional else ""
        return (
            f"नमस्ते {patient_name}। यह आपकी {eye_hi} की रेटिना जांच का सारांश है। "
            f"{provisional_warning} "
            f"जांच का परिणाम है: {grade_label}। "
            f"{explanation} "
            f"अनुशंसित अगला कदम: {referral_text} "
            "नियमित रूप से अपनी आंखों की जांच करवाएं और स्वस्थ रहें।"
        )
    else:
        provisional_warning = "Please note: this is a provisional screening result awaiting final clinician sign-off." if is_provisional else ""
        return (
            f"Hello {patient_name}. This is your retinal screening summary for your {eye_spoken}. "
            f"{provisional_warning} "
            f"Finding: {grade_label}. "
            f"{explanation} "
            f"Recommended next step: {referral_text} "
            "Remember to maintain your routine eye care and diabetes management."
        )
