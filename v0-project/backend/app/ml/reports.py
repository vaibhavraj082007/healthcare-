"""Phase 3 — structured clinical findings, evidence fusion and report NLG.

Triggered automatically once a Phase 2 ``ai_findings`` row is completed
(falling back to a text-only report when Grad-CAM cannot run). Everything is
persisted in ``screening_reports`` and regenerated only when the engine
signature (``model_version``) changes.

Since the Phase-4-A fix cycle the reports use a universal clinical layout:
fixed header snapshot (demographics frozen at generation time), a Findings body
with a full per-lesion-type breakdown (including explicit "0"), a highlighted
Observations section, a severity-appropriate Recommendation and a standardized
closing disclaimer. The region description (Fix 2) is computed from the real
Grad-CAM heatmap (thresholded + connected components against the optic-disc
reference), not a generic line.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from ..models import AIFinding, ImageUpload, ScreeningReport
from .consistency import (
    CLASSIFIER_ONLY,
    CONSISTENT,
    FLAGGED,
    LOW_LESION_EVIDENCE,
    lesion_grade_estimate,
)
from .gradcam import (
    analyze_heatmap_regions,
    generate_gradcam,
    report_dir,
)
from .registry import registry
from ..cases import ensure_case_tracking
from ..sync import enqueue_sync

logger = logging.getLogger("netrascan.reports")

# ---------------------------------------------------------------------------
# Fixed clinical terminology lookup (standard ICDR — not generated per case).
# ---------------------------------------------------------------------------
ICDR_LABELS = {
    0: "No DR",
    1: "Mild NPDR",
    2: "Moderate NPDR",
    3: "Severe NPDR",
    4: "Proliferative DR",
}

# Every lesion class the detector can report. The report must name all of them,
# including explicit "0" counts (Fix 3), so it never reads as selective.
LESION_TYPES = ["microaneurysm", "hemorrhage", "hard_exudate", "soft_exudate"]
LESION_PRINT = {
    "microaneurysm": "Microaneurysms",
    "hemorrhage": "Hemorrhages",
    "hard_exudate": "Hard exudates",
    "soft_exudate": "Soft exudates / cotton-wool spots",
}

# ---------------------------------------------------------------------------
# Severity-appropriate next-step recommendations.
#
# Thresholds follow the International Clinical Diabetic Retinopathy (ICDR)
# severity scale and the American Academy of Ophthalmology Diabetic
# Retinopathy Preferred Practice Pattern (2019), which recommends:
#   No DR           -> repeat retinal exam in ~12 months
#   Mild NPDR       -> 6-12 months
#   Moderate NPDR   -> 6 months (closer follow-up; refer if worsening)
#   Severe NPDR     -> prompt referral to an ophthalmologist
#   Proliferative DR-> urgent ophthalmology referral
# ---------------------------------------------------------------------------
RECOMMENDATIONS = {
    0: "Routine follow-up: repeat a retinal screening in 12 months, and keep "
       "blood sugar, blood pressure and cholesterol well controlled.",
    1: "Routine follow-up: repeat a retinal screening within 6-12 months.",
    2: "Close follow-up: another retinal examination and a clinical consult "
       "within 6 months is advised.",
    3: "Prompt referral: please see an ophthalmologist within the next few "
       "weeks for a comprehensive dilated eye exam.",
    4: "Urgent referral: please see an ophthalmologist urgently, ideally "
       "within days, for evaluation and treatment.",
}

# Standardized closing disclaimer, identical on every report (Fix 4).
STANDARD_DISCLAIMER = (
    "This report has been generated through AI-assisted analysis (CNN severity "
    "classification and YOLOv8 lesion detection) of the submitted fundus image. "
    "It is intended as a screening aid and does not constitute a confirmed "
    "clinical diagnosis. Please consult a qualified ophthalmologist for "
    "clinical evaluation and management."
)

# Closing disclaimer for the professional medical report — exact wording
# mandated by the product spec (universal diagnostic-report format).
MEDICAL_DISCLAIMER = (
    "This report contains findings generated with the assistance of artificial "
    "intelligence from the submitted fundus image. The AI output is intended to "
    "support clinical decision-making and does not replace examination, "
    "diagnosis, or treatment by a qualified ophthalmologist. Final clinical "
    "interpretation and patient management should be determined by the treating "
    "clinician."
)

EMBEDDED_DISCLAIMER = STANDARD_DISCLAIMER  # kept as an alias for compat

# ---------------------------------------------------------------------------
# Hindi (Devanagari) patient-facing rendering — authored by hand, not machine
# translated. Every report ships the same content in English and Hindi; the
# patient UI toggles between the two. The keys mirror the English fields the
# patient report panel renders, so the toggle is a pure lookup swap.
# ---------------------------------------------------------------------------
ICDR_LABELS_HI = {
    0: "डीआर नहीं",
    1: "हल्का एनपीडीआर",
    2: "मध्यम एनपीडीआर",
    3: "गंभीर एनपीडीआर",
    4: "प्रसारी डीआर",
}
LESION_LABELS_HI = {
    "microaneurysm": "माइक्रोएन्यूरिज्म",
    "hemorrhage": "रक्तस्राव",
    "hard_exudate": "हार्ड एक्सयूडेट",
    "soft_exudate": "सॉफ्ट एक्सयूडेट",
}
RECOMMENDATIONS_HI = {
    0: "नियमित अनुवर्ती: 12 महीने में दोबारा रेटिना स्क्रीनिंग कराएं, तथा रक्त "
       "शर्करा, रक्तचाप और कोलेस्ट्रॉल को अच्छी तरह नियंत्रित रखें।",
    1: "नियमित अनुवर्ती: 6–12 महीनों के भीतर दोबारा रेटिना स्क्रीनिंग कराएं।",
    2: "निकट अनुवर्ती: 6 महीनों के भीतर दोबारा रेटिना जाँच और चिकित्सकीय "
       "परामर्श लेने की सलाह दी जाती है।",
    3: "शीघ्र रेफरल: कृपया कुछ ही हफ्तों में नेत्र रोग विशेषज्ञ से पूर्ण "
       "डाइलेटेड (आई-ड्रॉप से फैली पुतली) आँख की जाँच कराएं।",
    4: "तत्काल रेफरल: कृपया तुरंत, आदर्शतः कुछ ही दिनों में, नेत्र रोग "
       "विशेषज्ञ से मूल्यांकन और उपचार कराएं।",
}
STANDARD_DISCLAIMER_HI = (
    "यह रिपोर्ट सबमिट की गई फंडस छवि के AI-सहायित विश्लेषण (CNN गंभीरता "
    "वर्गीकरण और YOLOv8 घाव डिटेक्शन) के माध्यम से तैयार की गई है। यह केवल "
    "स्क्रीनिंग सहायता के रूप में है और पुष्ट चिकित्सकीय निदान नहीं है। "
    "चिकित्सकीय मूल्यांकन और प्रबंधन के लिए कृपया योग्य नेत्र रोग विशेषज्ञ "
    "से परामर्श करें।"
)
_CONSISTENCY_HI = {
    CONSISTENT: "सुसंगत (दोनों इंजन मेल खाते हैं)",
    FLAGGED: "समीक्षा हेतु चिह्नित",
    LOW_LESION_EVIDENCE: "समीक्षा — कम घाव साक्ष्य",
    CLASSIFIER_ONLY: "केवल वर्गीकरण इंजन",
}
_FLAGGED_REASON_HI = {
    FLAGGED: (
        "अनुमानित गंभीरता स्तर पाए गए घावों से मेल नहीं खाता — दोनों इंजनों की "
        "एक साथ समीक्षा की जानी चाहिए"
    ),
    LOW_LESION_EVIDENCE: (
        "मध्यम-या-अधिक ग्रेड की भविष्यवाणी हुई, जबकि घाव डिटेक्टर को लगभग कोई "
        "घाव नहीं मिला — डिटेक्टर से छूटने की संभावना, चिकित्सकीय समीक्षा सलाहकार"
    ),
    CLASSIFIER_ONLY: (
        "इस स्कैन के लिए केवल गंभीरता वर्गीकरण इंजन उपलब्ध था; घाव डिटेक्टर नहीं चला"
    ),
}
_EYE_LABELS_HI = {
    "OD (right eye)": "दाहिनी आँख (OD)",
    "OS (left eye)": "बाईं आँख (OS)",
    "OU (both eyes)": "दोनों आँखें (OU)",
    "Unknown": "अनजान",
    "Not captured (laterality was not recorded at image capture)": (
        "दर्ज नहीं (स्कैन के समय आँख का विवरण दर्ज नहीं किया गया था)"
    ),
}
_VISIBILITY_HI = {"Yes": "हाँ", "Partially": "आंशिक रूप से", "No": "नहीं"}

# Hard-exudate load considered "heavy" for the macular-oedema risk note.
HEAVY_EXUDATE_COUNT = 8

LOW_RAM_GRADCAM_FLOOR_MB = 300  # heatmaps disabled only when RAM is critically low


def _gradcam_ram_floor_mb() -> int:
    """Overridable via NETRASCAN_RAM_FLOOR_MB (0 = always allow heatmaps)."""
    import os

    try:
        return int(os.environ.get("NETRASCAN_RAM_FLOOR_MB", LOW_RAM_GRADCAM_FLOOR_MB))
    except (TypeError, ValueError):
        return LOW_RAM_GRADCAM_FLOOR_MB


def _free_ram_mb() -> int:
    """Free physical RAM in MB on Windows (best-effort; 0 is never returned)."""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return int(stat.ullAvailPhys // (1024 * 1024))
    except Exception:  # noqa: BLE001 — non-Windows/ctypes-less: assume enough RAM
        return 4096


def model_signature(clf) -> str:
    """Short engine signature used to invalidate stale reports on re-analysis
    or after a checkpoint update."""
    if clf is None:
        return "unknown"
    meta = getattr(clf, "_meta", {}) or {}
    qwk = meta.get("validation_qwk")
    return f"efficientnet_b0_dr:{qwk if qwk is not None else 'na'}"


def _lesion_entries(finding: AIFinding) -> list[dict]:
    """Parse the stored lesion list, tolerant of {type,count}, richer
    {type,count,boxes} and {type,count,boxes,confidence} formats. Whenever
    boxes exist the mean detector confidence per type is derived from them."""
    try:
        raw = json.loads(finding.lesion_list or "[]")
    except json.JSONDecodeError:
        raw = []
    entries: list[dict] = []
    for item in raw:
        ltype = str(item.get("type", "unknown"))
        boxes = item.get("boxes")
        if isinstance(boxes, list) and boxes:
            count = len(boxes)
        else:
            count = int(item.get("count", 0))
            boxes = None
        confs = item.get("confidence")
        mean_conf = None
        if isinstance(confs, list) and confs:
            valid = [float(c) for c in confs if isinstance(c, (int, float))]
            if valid:
                mean_conf = round(sum(valid) / len(valid), 4)
        entries.append(
            {"type": ltype, "count": count, "boxes": boxes, "confidence": mean_conf}
        )
    return entries


def build_lesion_breakdown(entries: list[dict]) -> list[dict]:
    """Full per-lesion-type count, explicitly including types with zero
    detections (Fix 3 — the report reads complete, not selective)."""
    counts: dict[str, int] = defaultdict(int)
    for e in entries:
        counts[e["type"]] += e["count"]
    return [{"type": t, "count": counts.get(t, 0)} for t in LESION_TYPES]


def _mean_confidence_by_type(entries: list[dict]) -> dict[str, Optional[float]]:
    """Mean detector confidence per lesion type from the stored boxes/conf. A
    type with boxes but no recorded confidences yields None (reports "Not
    available" honestly instead of fabricating a number)."""
    scores: dict[str, list[float]] = defaultdict(list)
    for e in entries:
        if e.get("count", 0) <= 0:
            continue
        if e.get("boxes") and e.get("confidence") is not None:
            scores[e["type"]].append(e["confidence"])
    return {t: round(sum(v) / len(v), 4) for t, v in scores.items() if v}


def _lesion_truncated_note(counts: dict[str, int]) -> Optional[str]:
    """A single-line anatomical note when the tracker ran but no lesions were
    detected — used verbatim inside the Findings tables (kept explicitly
    separate from the classifier conclusions in the Assessment)."""
    if sum(counts.values()) > 0:
        return None
    return "No diabetic-retinopathy lesions detected by the lesion detector on this image."


# Consult the gradcam MACULA_OD_DIAMETERS constant: the macula/fovea estimate is
# placed two disc-diameters temporal to the detected disc centroid. We mirror
# that geometry here, so the visibility flags always agree with the region map.
_EYE_LABELS = {
    "od": "OD (right eye)",
    "os": "OS (left eye)",
    "ou": "OU (both eyes)",
    "unknown": "Unknown",
}

# The region analyzer runs in a 380x380 displayed frame; a structure must keep
# a 10% margin away from the frame edge to be reported as fully visible.
_VISIBILITY_FRAME_SIZE = 380
_VISIBILITY_FRAME_MARGIN_FRACTION = 0.10


def _eye_display(raw) -> Optional[str]:
    """Map stored laterality codes to the report's display label. Empty/None
    (pre-capture or not recorded) maps to None so callers fall back to the
    'Not captured' sentence."""
    if not raw:
        return None
    return _EYE_LABELS.get(str(raw).strip().lower(), str(raw))


def _visibility_from_region(region: Optional[dict]) -> tuple[str, str]:
    """Derive structured optic-disc / macula visibility (Yes | Partially | No)
    from the region analysis produced by the heatmap analyzer. Pure geometry on
    the already-detected disc centroid — no new detection. Returns
    ``(disc_visible, macula_visible)``."""
    disc = (region or {}).get("disc") if region else None
    if disc is None:
        return "No", "No"
    size = _VISIBILITY_FRAME_SIZE
    margin = _VISIBILITY_FRAME_MARGIN_FRACTION * size
    cx, cy = float(disc["x"]), float(disc["y"])
    radius = float(disc.get("radius") or 0.0)

    if (
        0 <= cx - radius <= size
        and 0 <= cx + radius <= size
        and 0 <= cy - radius <= size
        and 0 <= cy + radius <= size
        and 0 <= cx - margin <= size
        and 0 <= cx + margin <= size
        and 0 <= cy - margin <= size
        and 0 <= cy + margin <= size
    ):
        disc_visible = "Yes"
    elif 0 <= cx <= size and 0 <= cy <= size:
        disc_visible = "Partially"
    else:
        disc_visible = "No"

    # Fovea estimate, derived from the disc centroid (temporal side).
    temporal_sign = 1.0 if cx < size / 2.0 else -1.0
    mx, my = cx + temporal_sign * 2.0 * radius, cy
    if 0 <= mx - margin <= size and 0 <= mx + margin <= size and 0 <= my - margin <= size and 0 <= my + margin <= size:
        macula_visible = "Yes"
    elif 0 <= mx <= size and 0 <= my <= size:
        macula_visible = "Partially"
    else:
        macula_visible = "No"

    return disc_visible, macula_visible


def build_medical_report(
    struct: dict,
    header: dict,
    finding: AIFinding,
    region: Optional[dict],
    entries: list[dict],
    upload=None,
) -> dict:
    """Assemble the professional medical report content bundle (universal
    diagnostic-report format). Pure organization of existing AI output — no new
    inference. Missing data is surfaced as "Not Available" / "Unable to assess
    reliably from the available image." rather than suppressed."""

    def _na() -> str:
        return "Not Available"

    def _count_line(t: str, counts: dict[str, int]) -> str:
        noun = LESION_PRINT[t].replace(" / cotton-wool spots", "")
        return f"{counts.get(t, 0)} {noun.lower()} detected."

    def _conf_fmt(t: str, conf_by_type: dict[str, Optional[float]]) -> str:
        conf = conf_by_type.get(t)
        if conf is None:
            return "Not Available"
        return f"{conf:.2f} (mean detection confidence)"

    grade = struct.get("icdr_grade")
    label = struct.get("icdr_grade_label") or "Unknown"
    consistency = struct.get("consistency_status")
    flagged_reason = struct.get("flagged_reason")
    counts = {b["type"]: b["count"] for b in struct.get("lesion_breakdown", [])}
    conf_by_type = _mean_confidence_by_type(entries)
    # Severity scale positions — reuse the exact lesion->band mapping the
    # dual-engine consistency check uses so the scale never disagrees with it.
    lesion_grade = lesion_grade_estimate(counts)
    heatmap_available = bool(struct.get("gradcam_path"))

    # -- Anatomical sections -------------------------------------------------
    disc, macula, vasculature, background = "Not Available", "Not Available", "Not Available", "Not Available"
    region_attention_text = "No concentrated region of AI attention was detected on this image."
    if grade is not None:
        if grade == 0:
            disc = "No abnormalities detected by the AI-assisted analysis — the optic disc appears unremarkable."
            macula = "No diabetic-retinopathy abnormalities detected by the AI-assisted analysis."
            vasculature = "No diabetic-retinopathy abnormalities detected by the AI-assisted analysis."
            background = (
                "No microaneurysms, dot-blot hemorrhages or lipid exudates were detected by the "
                "AI-assisted lesion analysis; the background retina appears unremarkable."
            )
        else:
            disc = "No specific abnormality of the optic disc identified on this image by the AI-assisted analysis."
            macula = (
                "Diabetic retinopathy lesions may involve the macular region. Although edema cannot "
                "be reliably assessed on color fundus photography, macular involvement is possible "
                "and warrants clinical correlation."
            )
            vasculature = (
                "May be abnormal given the severity grade. Neovascularization, venous beading or IRMA "
                "cannot be confirmed on a color fundus photo and require clinical assessment."
            )
            background = (
                "Background retinopathy — multiple microaneurysms, hemorrhages and exudates identified "
                "by the AI-assisted lesion analysis (see lesion table)."
            )
    if region:
        parts = []
        if region.get("cluster_count"):
            parts.append(
                f"Top AI attention concentrated in {region.get('cluster_count')} region(s)."
            )
        if region.get("description"):
            parts.append(region["description"])
        if region.get("macula_attention"):
            parts.append(
                "AI attention includes the macular zone — correlation with dilated clinical examination advised."
            )
        if region.get("used_optic_disc"):
            parts.append(
                "Anatomic position referenced to the detected optic-disc location."
            )
        else:
            parts.append(
                "Anatomic reference (optic disc) could not be localized; attention positions are image-relative."
            )
        region_attention_text = " ".join(parts)
    elif not heatmap_available:
        region_attention_text = (
            "Heatmap unavailable — the AI explainability overlay was not generated "
            "for this scan, so region-of-attention analysis is not available."
        )

    # -- Examination / quality ----------------------------------------------
    eff_quality = None
    if upload is not None:
        eff_quality = getattr(upload, "quality_status", None) or None
    quality_status = header.get("image_quality") or eff_quality or "pending"
    quality_score = header.get("quality_score")
    if quality_score is None and upload is not None:
        quality_score = getattr(upload, "quality_score", None)
    if quality_status == "acceptable":
        quality_line = (
            f"Image quality: acceptable (focus score {quality_score:.0f})."
            if quality_score is not None else "Image quality: acceptable."
        )
    elif quality_status == "poor":
        quality_line = (
            f"Image quality: poor (focus score {quality_score:.0f}). The image is insufficiently "
            "reliable for AI-assisted assessment; interpretation is limited."
            if quality_score is not None else
            "Image quality: poor — insufficiently reliable for AI-assisted assessment; interpretation is limited."
        )
    else:
        quality_line = "Image quality: not assessed."

    # -- Consistency / status ------------------------------------------------
    if consistency in (FLAGGED, LOW_LESION_EVIDENCE):
        discrepant = "Discrepant — Clinical Review Required."
    else:
        discrepant = "Not applicable — no discrepancy flagged."
    if consistency == CONSISTENT:
        consistency_headline = "Consistent"
        consistency_status = "Both engines were concordant on the severity grade and the detected lesion load."
    elif consistency == FLAGGED:
        consistency_headline = "Discrepant — Clinical Review Required."
        consistency_status = (
            "Predicted severity grade and detected lesion load do not align. The finding requires "
            "clinical review before any action."
        )
    elif consistency == LOW_LESION_EVIDENCE:
        consistency_headline = "Discrepant — Clinical Review Required."
        consistency_status = (
            "A moderate-or-higher severity was predicted despite few or no lesions detected — possible "
            "detector miss. Clinical review required."
        )
    elif consistency == CLASSIFIER_ONLY:
        consistency_headline = "Classifier-only Analysis"
        consistency_status = (
            "Only the severity classifier was available for this scan; no lesion detector ran. "
            "Interpret with caution."
        )
    else:
        consistency_headline = str(consistency or _na())
        consistency_status = _na()
    if flagged_reason:
        consistency_status = f"{consistency_status} {flagged_reason.capitalize()}."

    # -- Recommendation -------------------------------------------------------
    rec_parts = []
    if struct.get("recommendation"):
        rec_parts.append(struct["recommendation"])
    if struct.get("possible_macular_edema"):
        rec_parts.append(
            "Given the possible macular-edema risk, an optical coherence tomography (OCT) assessment is advisable."
        )

    # -- AI analysis summary ---------------------------------------------------
    classifier_prov, detector_prov = _na(), _na()
    if finding.model_provenance:
        try:
            prov = json.loads(finding.model_provenance)
        except (ValueError, TypeError):
            prov = {}
        clf = prov.get("classifier")
        if isinstance(clf, dict):
            classifier_prov = clf.get("model") or _na()
        det = prov.get("detector")
        if isinstance(det, str):
            detector_prov = det
        elif isinstance(det, dict):
            detector_prov = det.get("option") or _na()

    # -- Report status (sign-off is merged from case detail on the client) ----
    generated = header.get("generated_at")
    if isinstance(generated, str):
        generated_line = generated
    elif isinstance(generated, datetime):
        generated_line = generated.strftime("%d %b %Y, %I:%M %p")
    else:
        generated_line = _na()

    scan_date = header.get("scan_date")
    if isinstance(scan_date, datetime):
        scan_date_iso = scan_date.isoformat()
    elif isinstance(scan_date, str):
        scan_date_iso = scan_date
    else:
        scan_date_iso = None

    discrepancies = bool(consistency in (FLAGGED, LOW_LESION_EVIDENCE))

    # -- Impression -----------------------------------------------------------
    # For flagged/mismatched scans the predicted grade must never read as a
    # flat fact: it is attributed to the classifier and explicitly marked as
    # not independently confirmed by the lesion detector (checklist item 4).
    if discrepancies and grade is not None and lesion_grade is not None:
        impression_line = (
            f"AI-assisted assessment — the severity classifier predicted {label} "
            f"(ICDR grade {grade}), but this was not independently confirmed by the "
            f"lesion detector (lesion-based estimate: ICDR grade {lesion_grade}). "
            f"{discrepant}"
        )
    else:
        impression_line = (
            f"AI-assisted assessment — {label}{' (ICDR grade ' + str(grade) + ')' if grade is not None else ''}. "
            f"{discrepant if consistency in (FLAGGED, LOW_LESION_EVIDENCE) else ('Only the severity classifier was available; no lesion detector ran.' if consistency == CLASSIFIER_ONLY else 'No discrepancy flagged between the two AI engines.')}"
        )

    # -- Severity scale render mode ------------------------------------------
    # The scale must agree with the consistency status by construction:
    #   concordant       -> single combined "AI assessment" marker at icdr_grade
    #   discordant       -> two markers (classifier vs lesion-based estimate)
    #   classifier_only  -> classifier marker only; no lesion estimate exists
    if grade is None:
        scale_mode = "unavailable"
        scale_lesion = None
    elif consistency == CLASSIFIER_ONLY:
        scale_mode = "classifier_only"
        scale_lesion = None
    elif consistency in (FLAGGED, LOW_LESION_EVIDENCE):
        scale_mode = "discordant"
        scale_lesion = lesion_grade
    else:
        scale_mode = "concordant"
        scale_lesion = lesion_grade

    return {
        "report_id": header.get("report_id") or f"NS-{ (finding.image_id or '')[:8].upper() }",
        "generated_at": generated_line,
        "severity_scale": {
            "classifier_grade": grade,
            "lesion_grade": scale_lesion,
            "mode": scale_mode,
        },
        "heatmap_available": heatmap_available,
        "patient": {
            "name": header.get("patient_name") or _na(),
            "patient_id": str(header.get("patient_id")) if header.get("patient_id") is not None else _na(),
            "age": str(header.get("patient_age")) if header.get("patient_age") is not None else _na(),
            "gender": header.get("patient_gender") or _na(),
            "referring_phc": header.get("referring_phc") or _na(),
            "submitting_worker": header.get("submitting_worker") or _na(),
        },
        "examination": {
            "scan_id": header.get("scan_id") or (finding.image_id or _na()),
            "scan_date": scan_date_iso,
            "eye": header.get("eye_laterality") or "Not captured (laterality was not recorded at image capture)",
            "modality": "Color fundus photography (screening)",
            "quality": quality_line,
            "optic_disc_visible": header.get("optic_disc_visible") or "Not Available",
            "macula_visible": header.get("macula_visible") or "Not Available",
        },
        "findings": {
            "optic_disc": disc,
            "macula": macula,
            "vasculature": vasculature,
            "background": background,
            "lesion_lines": [
                {
                    "label": LESION_PRINT[t],
                    "count_text": _count_line(t, counts),
                    "confidence_text": _conf_fmt(t, conf_by_type),
                }
                for t in LESION_TYPES
            ],
            "lesion_note": _lesion_truncated_note(counts),
            "region_attention": region_attention_text,
        },
        "lesion_table": [
            {
                "type": t,
                "label": LESION_PRINT[t],
                "count": counts.get(t, 0),
                "confidence": conf_by_type.get(t),
            }
            for t in LESION_TYPES
        ],
        "classification": {
            "grade": grade,
            "label": label,
            "basis": struct.get("grade_basis") or _na(),
            "icdr_confidence": finding.icdr_confidence,
            "total_lesion_count": struct.get("total_lesion_count", 0),
        },
        "consistency": {
            "headline": consistency_headline,
            "status": consistency_status,
            "discrepant": discrepancies,
        },
        "impression": impression_line,
        "observations": struct.get("observations") or ["No abnormal findings of note were detected."],
        "recommendation": " ".join(rec_parts) or (
            "An ophthalmology review is advised."
        ),
        "ai_analysis_summary": {
            "classifier": classifier_prov,
            "detector": detector_prov,
            "grade": f"{label} (ICDR grade {grade})" if grade is not None else _na(),
            "consistency": consistency or _na(),
            "region_analysis": (
                "Computed from the actual Grad-CAM heatmap."
                if (region and region.get("cluster_count") is not None)
                else "Region analysis unavailable for this scan."
            ),
        },
        "report_status": {
            "report_id": header.get("report_id") or f"NS-{ (finding.image_id or '')[:8].upper() }",
            "generated_at": generated_line,
            "method": "AI-assisted template report",
            "model_version": finding.model_version or _na(),
        },
        "disclaimer": MEDICAL_DISCLAIMER,
    }


def _grade_basis_note(
    grade: Optional[int],
    breakdown: list[dict],
    consistency: str,
) -> str:
    """Names the lesion types that actually drive the ICDR grade (Fix 3) —
    never letting an exudate count alone imply the severity. Venous beading and
    IRMA are part of ETDRS severe-NPDR staging but are NOT detectable by the
    current YOLOv8 lesion detector, and that limitation is stated honestly."""
    counts = {b["type"]: b["count"] for b in breakdown}
    ma = counts.get("microaneurysm", 0)
    he = counts.get("hemorrhage", 0)
    hexu = counts.get("hard_exudate", 0)
    sexu = counts.get("soft_exudate", 0)

    if grade is None:
        return "The severity grade could not be determined for this scan."

    if grade == 0:
        return (
            f"No microaneurysms or other retinopathy lesions were detected "
            f"(microaneurysms {ma}, hemorrhages {he}, hard exudates {hexu}, "
            f"soft exudates {sexu}), consistent with no DR."
        )
    if grade == 1:
        return (
            f"The mild grade is driven by the presence of microaneurysms ({ma}) — "
            f"the hallmark earliest lesion of non-proliferative DR in ICDR staging."
        )
    if grade == 2:
        drivers = []
        if he > 0:
            drivers.append(f"hemorrhages ({he})")
        if ma > 0:
            drivers.append(f"microaneurysms ({ma})")
        if not drivers:
            drivers = ["the combined lesion load shown below"]
        return (
            f"Per standard ICDR staging the moderate grade is driven by "
            f"{', '.join(drivers)} — not by exudates alone. Exudates ({hexu} hard, "
            f"{sexu} soft), when present, are a sign of lipid leakage rather than "
            f"the severity driver."
        )
    if grade == 3:
        return (
            f"The severe grade reflects extensive microaneurysm ({ma}) and "
            f"hemorrhage ({he}) load across the field. Venous beading and IRMA — "
            f"the other features of ETDRS severe-NPDR staging — cannot be detected "
            f"by the current lesion detector and must be assessed at the slit lamp."
        )
    return (
        f"The proliferative grade indicates suspected neovascularization, which "
        f"a fundus-photo lesion detector cannot confirm; an urgent clinical "
        f"assessment is required."
    )


def _assess_macular_edema(breakdown: list[dict], region: Optional[dict]) -> dict:
    """Separate, explicit macular-oedema risk signal (Fix 3) — distinct from the
    NPC severity grade. Evidence = heavy hard exudation AND either AI-attention
    hotspots in the macular zone or exudate boxes sitting within it."""
    counts = {b["type"]: b["count"] for b in breakdown}
    hexu = counts.get("hard_exudate", 0)
    if hexu < HEAVY_EXUDATE_COUNT:
        return {"possible_macular_edema": False, "macular_edema_note": None}

    region = region or {}
    macula_attention = bool(region.get("macula_attention"))
    near_macula = int(region.get("exudates_near_macula") or 0)
    evidence = macula_attention or near_macula >= max(3, int(0.3 * hexu))

    if evidence:
        basis = []
        if macula_attention:
            basis.append("the AI's attention is concentrated near the macula")
        if near_macula > 0:
            basis.append(f"{near_macula} of {hexu} hard exudates sit in the macular zone")
        return {
            "possible_macular_edema": True,
            "macular_edema_note": (
                f"Hard exudates are heavy ({hexu}) and {', and '.join(basis)}. "
                f"Clinically significant macular edema should be assessed "
                f"separately from the NPDR severity grade."
            ),
        }
    return {
        "possible_macular_edema": True,
        "macular_edema_note": (
            f"Hard exudate load is heavy ({hexu}). Though the AI attention is not "
            f"centered on the macula, a clinical check for possible macular edema "
            f"is advisable given the exudate load."
        ),
    }


def build_observations(
    grade,
    label,
    breakdown: list[dict],
    consistency: str,
    flagged_reason: Optional[str],
    macula: dict,
    region: Optional[dict],
) -> list[str]:
    """Plain-language Observations for the highlighted Observations block shared
    by the patient and clinical layouts. Produces 2-3 distinct, concrete points
    — the finding, the specific lesion evidence, and the dual-engine status —
    each traceable to a real field (severity grade, per-type lesion counts,
    consistency status). Extra real findings (macular-oedema risk, AI attention
    near the macula) are appended when present. Never collapses to a single
    generic line while more than one real fact exists."""
    counts = {b["type"]: b["count"] for b in breakdown}

    _LESION_NOUNS = {
        "microaneurysm": "microaneurysm",
        "hemorrhage": "hemorrhage",
        "hard_exudate": "hard exudate",
        "soft_exudate": "soft exudate",
    }

    def _counted(n: int, noun: str) -> str:
        return f"{n} {noun}" + ("" if n == 1 else "s")

    obs: list[str] = []

    # 1. The finding itself, in plain terms.
    if grade is None:
        obs.append("This scan could not be assigned a diabetic retinopathy severity grade.")
    elif grade == 0:
        obs.append("No diabetic retinopathy changes were observed in this scan.")
    else:
        obs.append(
            f"{label} (ICDR grade {grade}) changes were observed in this scan."
        )

    # Classifier-only: the detector never ran, so there is no lesion evidence
    # to report separately — a single point covers both facts (no duplication).
    if consistency == CLASSIFIER_ONLY:
        obs.append(
            "No lesion-detector evidence was available for this scan — only the "
            "severity classifier ran."
        )
    else:
        # 2. The specific lesion evidence behind the finding.
        positive = sorted(
            (
                (t, counts.get(t, 0))
                for t in ("microaneurysm", "hemorrhage", "hard_exudate", "soft_exudate")
                if counts.get(t, 0) > 0
            ),
            key=lambda item: -item[1],
        )
        if positive:
            parts = ", ".join(_counted(n, _LESION_NOUNS[t]) for t, n in positive)
            obs.append(f"The lesion detector identified: {parts}.")
        elif grade == 0:
            obs.append(
                "The lesion detector found no microaneurysms, hemorrhages, hard "
                "exudates, or soft exudates in this scan."
            )
        else:
            obs.append(
                "The lesion detector found no microaneurysms, hemorrhages, hard "
                "exudates, or soft exudates, despite the predicted severity grade."
            )

        # 3. The consistency / discordance status, when relevant.
        if consistency == FLAGGED:
            obs.append(
                "The two AI models did not fully agree on the severity — this scan "
                "has been flagged for a doctor's review before acting on it."
            )
        elif consistency == LOW_LESION_EVIDENCE:
            obs.append(
                "A moderate-or-higher severity was predicted despite few or no "
                "lesions detected — possible detector miss, clinical review advised."
            )
        elif consistency == CONSISTENT:
            obs.append(
                "The severity classifier and the lesion detector agreed on the "
                "severity grade."
            )

    # Extra real findings, when present.
    if macula.get("possible_macular_edema") and macula.get("macular_edema_note"):
        obs.append(macula["macular_edema_note"])
    if region and region.get("macula_attention"):
        obs.append("The AI's attention is concentrated near the macular region.")

    if not obs:
        obs.append("No abnormal findings of note were detected.")
    return obs


# ---------------------------------------------------------------------------
# Hindi builders — mirror of the English + Section-3 prose above, author-written
# in Devanagari. Numeric placeholders stay Arabic so counts read identically in
# both languages. Each returns content shaped exactly like its English twin.
# ---------------------------------------------------------------------------
def _grade_basis_note_hi(grade, breakdown: list[dict]) -> str:
    counts = {b["type"]: b["count"] for b in breakdown}
    ma = counts.get("microaneurysm", 0)
    he = counts.get("hemorrhage", 0)
    hexu = counts.get("hard_exudate", 0)
    sexu = counts.get("soft_exudate", 0)

    if grade is None:
        return "इस स्कैन के लिए गंभीरता स्तर निर्धारित नहीं किया जा सका।"
    if grade == 0:
        return (
            f"कोई माइक्रोएन्यूरिज्म या अन्य रेटिनोपैथी घाव नहीं मिले "
            f"(माइक्रोएन्यूरिज्म {ma}, रक्तस्राव {he}, हार्ड एक्सयूडेट {hexu}, "
            f"सॉफ्ट एक्सयूडेट {sexu}), जो डीआर-रहित होने के अनुरूप है।"
        )
    if grade == 1:
        return (
            f"हल्का ग्रेड माइक्रोएन्यूरिज्म ({ma}) की उपस्थिति पर आधारित है — "
            f"ICDR मंचन के अनुसार यह गैर-प्रसारी डीआर का सबसे प्रारंभिक घाव है।"
        )
    if grade == 2:
        drivers = []
        if he > 0:
            drivers.append(f"रक्तस्राव ({he})")
        if ma > 0:
            drivers.append(f"माइक्रोएन्यूरिज्म ({ma})")
        if not drivers:
            drivers = ["नीचे दिखाया गया संयुक्त घाव भार"]
        return (
            f"मानक ICDR मंचन के अनुसार मध्यम ग्रेड {', '.join(drivers)} द्वारा "
            f"निर्धारित है — न कि केवल एक्सयूडेट से। एक्सयूडेट ({hexu} हार्ड, "
            f"{sexu} सॉफ्ट), यदि मौजूद हों, लिपिड रिसाव का संकेत हैं, न कि "
            f"गंभीरता का मुख्य कारण।"
        )
    if grade == 3:
        return (
            f"गंभीर ग्रेड पूरे क्षेत्र में व्यापक माइक्रोएन्यूरिज्म ({ma}) और "
            f"रक्तस्राव ({he}) भार दर्शाता है। शिरापरक मनका और IRMA — ETDRS "
            f"गंभीर-एनपीडीआर मंचन के अन्य लक्षण — वर्तमान घाव डिटेक्टर से नहीं "
            f"पहचाने जा सकते और स्लिट-लैंप जाँच आवश्यक है।"
        )
    return (
        "प्रसारी ग्रेड संदिग्ध नव-संवहन का संकेत देता है, जिसकी पुष्टि फंडस-फोटो "
        "घाव डिटेक्टर नहीं कर सकता; तत्काल चिकित्सकीय आकलन आवश्यक है।"
    )


def _macular_edema_note_hi(breakdown: list[dict], region: Optional[dict]) -> Optional[str]:
    """Hindi twin of the EN note inside ``_assess_macular_edema`` — re-derives
    the exact same evidence so the two never contradict each other."""
    counts = {b["type"]: b["count"] for b in breakdown}
    hexu = counts.get("hard_exudate", 0)
    if hexu < HEAVY_EXUDATE_COUNT:
        return None
    region = region or {}
    macula_attention = bool(region.get("macula_attention"))
    near_macula = int(region.get("exudates_near_macula") or 0)
    evidence = macula_attention or near_macula >= max(3, int(0.3 * hexu))

    if evidence:
        basis = []
        if macula_attention:
            basis.append("AI का ध्यान मैकुला के पास केंद्रित है")
        if near_macula > 0:
            basis.append(f"{hexu} में से {near_macula} हार्ड एक्सयूडेट मैकुलर क्षेत्र में हैं")
        return (
            f"हार्ड एक्सयूडेट अधिक हैं ({hexu}), और {', और '.join(basis)}। "
            f"चिकित्सकीय रूप से महत्वपूर्ण मैकुलर एडिमा का आकलन एनपीडीआर "
            f"गंभीरता स्तर से अलग किया जाना चाहिए।"
        )
    return (
        f"हार्ड एक्सयूडेट का भार अधिक है ({hexu})। यद्यपि AI का ध्यान मैकुला पर "
        f"केंद्रित नहीं है, फिर भी एक्सयूडेट भार को देखते हुए संभावित मैकुलर "
        f"एडिमा की चिकित्सकीय जाँच सलाहकार है।"
    )


def _region_notes_hi(region: Optional[dict], heatmap_available: bool) -> Optional[str]:
    """Hindi summary of the region analysis — derived from the same structured
    region fields the English prose uses (cluster count, macula attention,
    optic-disc reference), so it always agrees with the English text."""
    if not region:
        if not heatmap_available:
            return (
                "हीटमैप उपलब्ध नहीं — इस स्कैन के लिए AI व्याख्या ओवरले नहीं "
                "बना, इसलिए ध्यान-क्षेत्र विश्लेषण उपलब्ध नहीं है।"
            )
        return "इस छवि पर AI ध्यान का कोई केंद्रित क्षेत्र नहीं मिला।"
    parts = []
    if region.get("cluster_count"):
        n = int(region.get("cluster_count") or 0)
        parts.append(
            f"AI का मुख्य ध्यान {n} क्षेत्र{'ों' if n != 1 else ''} पर केंद्रित है।"
        )
    if region.get("macula_attention"):
        parts.append("AI ध्यान में मैकुलर क्षेत्र भी शामिल है — फैली हुई पुतली से जाँच की सलाह दी जाती है।")
    if region.get("used_optic_disc"):
        parts.append("स्थिति संदर्भ पहचाने गए ऑप्टिक-डिस्क स्थान से लिया गया है।")
    else:
        parts.append("ऑप्टिक डिस्क (स्थिति संदर्भ) स्थानीयकृत नहीं हो सका; ध्यान की स्थितियाँ छवि-सापेक्ष हैं।")
    return " ".join(parts)


def _recommendation_hi(
    grade: Optional[int],
    macula_possible: bool,
    consistency: str,
) -> str:
    rec: str = RECOMMENDATIONS_HI.get(grade, "")
    if macula_possible:
        rec += (
            " संभावित मैकुलर एडिमा जोखिम को देखते हुए अनुवर्ती के भाग के रूप में "
            "ऑप्टिकल कोहेरेंस टोमोग्राफी (OCT) जाँच सलाहकार है।"
        )
    if consistency in (FLAGGED, LOW_LESION_EVIDENCE):
        rec += (
            " क्योंकि दोनों इंजन पूरी तरह सहमत नहीं थे, इस परिणाम पर कार्य करने से "
            "पहले नेत्र रोग विशेषज्ञ से समीक्षा कराई जानी चाहिए।"
        )
    return rec


def build_observations_hi(
    grade,
    label_hi: str,
    breakdown: list[dict],
    consistency: str,
    macula: dict,
    region: Optional[dict],
) -> list[str]:
    """Plain-language Observations in Hindi — same 2-3 concrete, data-backed
    points as the English block, mirroring its decision logic exactly."""
    counts = {b["type"]: b["count"] for b in breakdown}
    order = ("microaneurysm", "hemorrhage", "hard_exudate", "soft_exudate")
    obs: list[str] = []

    if grade is None:
        obs.append("इस स्कैन के लिए मधुमेह संबंधी रेटिना रोग की गंभीरता निर्धारित नहीं हो सकी।")
    elif grade == 0:
        obs.append("इस स्कैन में मधुमेह संबंधी रेटिना रोग के कोई परिवर्तन नहीं देखे गए।")
    else:
        obs.append(f"{label_hi} (ICDR ग्रेड {grade}) के परिवर्तन इस स्कैन में देखे गए।")

    if consistency == CLASSIFIER_ONLY:
        obs.append(
            "इस स्कैन के लिए घाव-डिटेक्टर का कोई साक्ष्य उपलब्ध नहीं था — केवल "
            "गंभीरता वर्गीकरण इंजन चला।"
        )
    else:
        positive = sorted(
            ((t, counts.get(t, 0)) for t in order if counts.get(t, 0) > 0),
            key=lambda item: -item[1],
        )
        if positive:
            parts = ", ".join(f"{n} {LESION_LABELS_HI[t]}" for t, n in positive)
            obs.append(f"घाव डिटेक्टर ने पहचान की: {parts}।")
        elif grade == 0:
            obs.append(
                "घाव डिटेक्टर को इस स्कैन में कोई माइक्रोएन्यूरिज्म, रक्तस्राव, "
                "हार्ड एक्सयूडेट या सॉफ्ट एक्सयूडेट नहीं मिला।"
            )
        else:
            obs.append(
                "अनुमानित गंभीरता के बावजूद घाव डिटेक्टर को कोई माइक्रोएन्यूरिज्म, "
                "रक्तस्राव, हार्ड एक्सयूडेट या सॉफ्ट एक्सयूडेट नहीं मिला।"
            )
        if consistency == FLAGGED:
            obs.append(
                "दो AI मॉडल गंभीरता पर पूरी तरह सहमत नहीं थे — कार्रवाई से पहले "
                "इस स्कैन को डॉक्टर की समीक्षा के लिए चिह्नित किया गया है।"
            )
        elif consistency == LOW_LESION_EVIDENCE:
            obs.append(
                "कुछ या कोई घाव न मिलने के बावजूद मध्यम-या-अधिक गंभीरता की "
                "भविष्यवाणी हुई — डिटेक्टर से छूटने की संभावना, चिकित्सकीय समीक्षा सलाहकार।"
            )
        elif consistency == CONSISTENT:
            obs.append(
                "गंभीरता वर्गीकरण और घाव डिटेक्टर गंभीरता स्तर पर सहमत थे।"
            )

    if macula.get("possible_macular_edema"):
        note_hi = _macular_edema_note_hi(breakdown, region)
        if note_hi:
            obs.append(note_hi)
    if region and region.get("macula_attention"):
        obs.append("AI का ध्यान मैकुलर क्षेत्र के पास केंद्रित है।")
    if not obs:
        obs.append("कोई विशेष असामान्य निष्कर्ष नहीं मिला।")
    return obs


def generate_report_text_hi(
    patient_name: str,
    image_id: str,
    analyzed_at: Optional[datetime],
    structured: dict,
    hi: dict,
    header: dict,
) -> str:
    """Hindi plain-language patient report — same layout and fact content as the
    English ``generate_report_text``, author-translated into Devanagari."""
    grade = structured["icdr_grade"]
    label_hi = hi["grade_label"]
    consistency_hi = hi["consistency_status"]
    counts = {b["type"]: b["count"] for b in structured["lesion_breakdown"]}

    lines: list[str] = []
    lines.append("NetraScan — AI मधुमेह रेटिना जाँच रिपोर्ट")
    lines.append("")
    lines.append(
        f"रोगी: {header.get('patient_name') or patient_name}"
        f"{'  |  आयु: ' + str(header.get('patient_age')) if header.get('patient_age') is not None else ''}"
        f"{'  |  लिंग: ' + header.get('patient_gender') if header.get('patient_gender') else ''}"
    )
    lines.append(
        f"रोगी ID: {header.get('patient_id') or '—'}   |   स्कैन ID: #{image_id[:8]}"
    )
    lines.append(
        f"स्कैन की तारीख: {header.get('scan_date') or (analyzed_at.strftime('%d %b %Y') if analyzed_at else '—')}"
    )
    lines.append(
        f"संदर्भित PHC / ASHA कार्यकर्ता: {header.get('referring_phc') or '—'} / "
        f"{header.get('submitting_worker') or '—'}"
    )
    lines.append(f"आँख: {hi.get('eye') or 'दर्ज नहीं'}")
    if header.get("optic_disc_visible") and header.get("macula_visible"):
        disc_hi = _VISIBILITY_HI.get(str(header.get("optic_disc_visible")), str(header.get("optic_disc_visible")))
        mac_hi = _VISIBILITY_HI.get(str(header.get("macula_visible")), str(header.get("macula_visible")))
        lines.append(f"ऑप्टिक डिस्क दृश्यता: {disc_hi}   |   मैकुला दृश्यता: {mac_hi}")
    lines.append("")

    lines.append("निष्कर्ष")
    if grade is None:
        lines.append(
            "• गंभीरता: इस स्कैन के लिए मधुमेह रेटिना रोग की मात्रा निर्धारित "
            "नहीं हो सकी।"
        )
    else:
        lines.append(
            f"• गंभीरता: {label_hi} (ICDR ग्रेड {grade}) [{consistency_hi}]"
        )
    for t in LESION_TYPES:
        lines.append(f"• {LESION_LABELS_HI[t]}: {counts.get(t, 0)}")
    if hi.get("region_notes"):
        lines.append(f"• AI ध्यान क्षेत्र: {hi['region_notes']}।")
    lines.append(
        f"• ग्रेड का आधार: {hi.get('grade_basis') or 'नीचे सादा-भाषा सारांश देखें।'}"
    )

    lines.append("")
    lines.append("अवलोकन")
    for item in hi.get("observations") or []:
        lines.append(f"• {item}")

    lines.append("")
    lines.append("अनुशंसा")
    lines.append(hi.get("recommendation") or "नेत्र रोग विशेषज्ञ से परामर्श सलाहकार है।")

    lines.append("")
    lines.append("अस्वीकरण")
    lines.append(hi.get("disclaimer") or STANDARD_DISCLAIMER_HI)
    return "\n".join(lines)


def build_hindi_bundle(
    grade,
    breakdown: list[dict],
    consistency: str,
    region: Optional[dict],
    macula: dict,
    header: dict,
    image_id: str,
    analyzed_at: Optional[datetime],
    patient_name: str,
    gradcam_path: Optional[str],
) -> dict:
    """Assemble the structured Hindi bundle shipped inside ``structured_findings['hi']``.
    Everything a patient panel needs in Devanagari, pre-translated like the rest
    of the report — the UI toggle is a pure data swap, never on-the-fly translation."""
    label_hi = ICDR_LABELS_HI.get(grade, "अज्ञात") if grade is not None else "अज्ञात"
    observations_hi = build_observations_hi(
        grade, label_hi, breakdown, consistency, macula, region
    )
    ec = _EYE_LABELS_HI.get(
        header.get("eye_laterality") or "Not captured (laterality was not recorded at image capture)"
    ) or "दर्ज नहीं"
    hi = {
        "grade_label": label_hi,
        "consistency_status": _CONSISTENCY_HI.get(consistency, consistency),
        "flagged_reason": _FLAGGED_REASON_HI.get(consistency),
        "lesion_labels": dict(LESION_LABELS_HI),
        "region_notes": _region_notes_hi(region, bool(gradcam_path)),
        "grade_basis": _grade_basis_note_hi(grade, breakdown),
        "observations": observations_hi,
        "recommendation": _recommendation_hi(
            grade, macula.get("possible_macular_edema"), consistency
        ),
        "macular_edema_note": _macular_edema_note_hi(breakdown, region),
        "eye": ec,
        "disclaimer": STANDARD_DISCLAIMER_HI,
    }
    hi["patient_report"] = generate_report_text_hi(
        patient_name,
        image_id,
        analyzed_at,
        {"icdr_grade": grade, "lesion_breakdown": breakdown},
        hi,
        header,
    )
    return hi


def build_structured_findings(
    finding: AIFinding,
    region: Optional[dict] = None,
    header: Optional[dict] = None,
    upload=None,
    gradcam_path: Optional[str] = None,
) -> dict:
    """Restructure the Phase 2 ``ai_findings`` row into a clinician-readable
    object (no new AI — just organizing what already exists). Since the Phase
    4-A fix this includes the full lesion breakdown, the grade driver statement,
    the macular-oedema risk and the computed heatmap region analysis. The
    professional MedicalReport bundle is included as ``medical_report``."""
    entries = _lesion_entries(finding)
    breakdown = build_lesion_breakdown(entries)
    total = sum(b["count"] for b in breakdown)

    flagged_reason = None
    if finding.consistency_status == FLAGGED:
        flagged_reason = (
            "the predicted severity grade does not align with the detected "
            "lesion load — both engines should be reviewed together"
        )
    elif finding.consistency_status == LOW_LESION_EVIDENCE:
        flagged_reason = (
            "a moderate-or-higher grade was predicted even though the lesion "
            "detector found no lesions — possible detector miss"
        )
    elif finding.consistency_status == CLASSIFIER_ONLY:
        flagged_reason = (
            "only the severity classifier was available for this scan; "
            "no lesion detector ran"
        )

    grade = int(finding.icdr_grade) if finding.icdr_grade is not None else None
    label = ICDR_LABELS.get(grade, "Unknown") if grade is not None else "Unknown"
    macula = _assess_macular_edema(breakdown, region)

    summary = sorted(
        (b for b in breakdown if b["count"] > 0), key=lambda s: -s["count"]
    )
    observations = build_observations(
        grade,
        label,
        breakdown,
        finding.consistency_status,
        flagged_reason,
        macula,
        region,
    )

    rec = RECOMMENDATIONS.get(grade, "")
    if macula["possible_macular_edema"]:
        rec += (
            " Given the possible macular-edema risk, an optical coherence "
            "tomography (OCT) assessment is advisable as part of the follow-up."
        )
    if finding.consistency_status in (FLAGGED, LOW_LESION_EVIDENCE):
        rec += (
            " Because the two engines did not fully agree, an ophthalmologist "
            "should review this result before acting on it."
        )

    hi = build_hindi_bundle(
        grade,
        breakdown,
        finding.consistency_status,
        region,
        macula,
        header or {},
        finding.image_id,
        finding.analyzed_at,
        (header or {}).get("patient_name") or "Patient",
        gradcam_path=gradcam_path,
    )

    return {
        "icdr_grade": grade,
        "icdr_grade_label": label,
        "lesion_breakdown": breakdown,
        "lesion_summary": summary,
        "total_lesion_count": total,
        "consistency_status": finding.consistency_status,
        "flagged_reason": flagged_reason,
        "model_version": finding.model_version or "unknown",
        "grade_basis": _grade_basis_note(
            grade, breakdown, finding.consistency_status
        ),
        "possible_macular_edema": macula["possible_macular_edema"],
        "macular_edema_note": macula["macular_edema_note"],
        "region_analysis": region if region is not None else None,
        "region_notes": (region or {}).get("description"),
        "observations": observations,
        "recommendation": rec,
        "disclaimer": STANDARD_DISCLAIMER,
        "hi": hi,
        "medical_report": build_medical_report(
            {
                "icdr_grade": grade,
                "icdr_grade_label": label,
                "lesion_breakdown": breakdown,
                "total_lesion_count": total,
                "consistency_status": finding.consistency_status,
                "flagged_reason": flagged_reason,
                "grade_basis": _grade_basis_note(
                    grade, breakdown, finding.consistency_status
                ),
                "possible_macular_edema": macula["possible_macular_edema"],
                "recommendation": rec,
                "observations": observations,
                "gradcam_path": gradcam_path,
            },
            header or {},
            finding,
            region,
            entries,
            upload=upload,
        ),
    }


def build_evidence_fusion(
    image_id: str,
    structured: dict,
    gradcam_path: Optional[str],
    region_notes: Optional[str],
) -> dict:
    return {
        "image_id": image_id,
        "gradcam_path": gradcam_path,
        "structured_findings": structured,
        "region_notes": region_notes,
    }


def generate_report_text(
    patient_name: str,
    image_id: str,
    analyzed_at: Optional[datetime],
    structured: dict,
    header: dict,
) -> str:
    """Deterministic template NLG. Patient-facing, plain language, but in the
    same universal layout (header / findings / observations / recommendation /
    disclaimer) as the clinical view (Fix 4)."""
    grade = structured["icdr_grade"]
    label = structured["icdr_grade_label"]
    consistency = structured["consistency_status"]
    breakdown = structured["lesion_breakdown"]
    counts = {b["type"]: b["count"] for b in breakdown}
    region_notes = structured["region_notes"]
    observations = structured["observations"]
    rec = structured["recommendation"]
    disclaimer = structured["disclaimer"]

    lines: list[str] = []
    lines.append("NetraScan — AI Diabetic Retinopathy Screening Report")
    lines.append("")
    lines.append(
        f"Patient: {header.get('patient_name') or patient_name}"
        f"{'  |  Age: ' + str(header.get('patient_age')) if header.get('patient_age') is not None else ''}"
        f"{'  |  Gender: ' + header.get('patient_gender') if header.get('patient_gender') else ''}"
    )
    lines.append(
        f"Patient ID: {header.get('patient_id') or '—'}   |   Scan ID: #{image_id[:8]}"
    )
    lines.append(
        f"Date of scan: {header.get('scan_date') or (analyzed_at.strftime('%d %b %Y') if analyzed_at else '—')}"
    )
    lines.append(
        f"Referring PHC / ASHA worker: {header.get('referring_phc') or '—'} / "
        f"{header.get('submitting_worker') or '—'}"
    )
    lines.append(
        f"Eye: {header.get('eye_laterality') or 'Not captured (laterality was not recorded at image capture)'}"
    )
    if header.get("optic_disc_visible") and header.get("macula_visible"):
        lines.append(
            f"Optic disc visibility: {str(header.get('optic_disc_visible')).lower()}  |  "
            f"Macula visibility: {str(header.get('macula_visible')).lower()}"
        )
    lines.append("")

    # Body — Findings
    lines.append("FINDINGS")
    if grade is None:
        lines.append(
            "• Severity: the degree of diabetic retinopathy could not be "
            "determined for this scan."
        )
    else:
        lines.append(
            f"• Severity: {label} (ICDR grade {grade}) [{consistency}]"
        )
    for t in LESION_TYPES:
        lines.append(f"• {LESION_PRINT[t]}: {counts.get(t, 0)}")
    if region_notes:
        lines.append(f"• Region of AI attention: {region_notes}.")
    lines.append(f"• Basis for the grade: {structured['grade_basis']}")

    # Observations — highlighted in the UI; plain block in the text.
    lines.append("")
    lines.append("OBSERVATIONS")
    for item in observations:
        lines.append(f"• {item}")

    # Recommendation
    lines.append("")
    lines.append("RECOMMENDATION")
    lines.append(rec if rec else "An ophthalmology review is advised.")

    # Standardized closing disclaimer
    lines.append("")
    lines.append("DISCLAIMER")
    lines.append(disclaimer)
    return "\n".join(lines)


def ensure_report(
    db: Session,
    finding: AIFinding,
    *,
    allow_gradcam: bool = True,
    force: bool = False,
) -> Optional[ScreeningReport]:
    """Generate (or refresh) the report for a completed finding.

    Idempotent and cheap when nothing changed: any mismatch in ``model_version``
    between the finding and the stored report triggers a rebuild. Grad-CAM runs
    only when the weights are actually loaded and there is enough free RAM
    (so a live upload during training never OOMs the trainer).
    """
    if finding.icdr_grade is None or finding.analysis_status != "completed":
        return None

    current_sig = model_signature(registry.classifier)
    if finding.model_version is None:
        finding.model_version = current_sig if current_sig != "unknown" else "unknown"

    report = (
        db.query(ScreeningReport).filter(ScreeningReport.image_id == finding.image_id).first()
    )
    if report is not None and not force:
        stale = report.model_version != finding.model_version
        missing_heatmap = allow_gradcam and report.gradcam_path is None
        if not stale and not missing_heatmap:
            enqueue_sync(db, finding.image_id)  # Phase 4 — cover pre-Phase-4 rows
            return report  # cached report is current — don't regenerate
        # fall through: rebuild because the model changed or heatmap is missing

    upload = db.query(ImageUpload).filter(ImageUpload.image_id == finding.image_id).first()
    image_path = Path(upload.file_path) if upload and upload.file_path else None

    gradcam_path: Optional[str] = None
    cam = None
    if (
        allow_gradcam
        and registry.classifier is not None
        and image_path is not None
        and image_path.exists()
        and _free_ram_mb() >= _gradcam_ram_floor_mb()
    ):
        out = report_dir() / f"{finding.image_id}_gradcam.png"
        res = generate_gradcam(
            image_path,
            predicted_class=finding.icdr_grade,
            out_path=out,
            model=registry.classifier._model,
            ordinal=registry.classifier.ordinal,
            device="cpu",
        )
        gradcam_path = res.path
        if res.path is not None:
            cam = res.cam

    # Fix 2 — region description from the real heatmap (thresholded clusters vs
    # the optic-disc reference), including per-type lesion-box overlap.
    lesion_boxes = {
        e["type"]: e["boxes"]
        for e in _lesion_entries(finding)
        if e.get("boxes") and e["type"] in LESION_TYPES
    }
    region = None
    if cam is not None:
        from .gradcam import analyze_heatmap_regions  # local to keep imports light

        analysis = analyze_heatmap_regions(
            cam,
            image_path=image_path,
            lesion_boxes=lesion_boxes,
            size=380,
        )
        if analysis is not None:
            region = {
                "cluster_count": analysis.cluster_count,
                "used_optic_disc": analysis.used_optic_disc,
                "disc": analysis.disc,
                "clusters": analysis.clusters,
                "description": analysis.description,
                "macula_attention": analysis.macula_attention,
                "exudates_near_macula": analysis.exudates_near_macula,
                "spread_evenly": analysis.spread_evenly,
            }
    elif image_path is not None and image_path.exists():
        # No heatmap (RAM floor / classifier offline): keep the hamlet null so
        # the report clearly shows "region analysis unavailable".
        region = None
    region_notes = (region or {}).get("description")
    disc_visible, macula_visible = _visibility_from_region(region)

    # Universal report header — demographics snapshot at generation time so the
    # report never changes when the patient profile is edited later (Fix 4).
    patient = upload.patient if upload is not None else None
    worker = upload.uploaded_by_user if upload is not None else None
    header = {
        "patient_id": patient.id if patient is not None else None,
        "patient_name": patient.full_name if patient is not None else None,
        "patient_age": patient.age if patient is not None else None,
        "patient_gender": patient.gender if patient is not None else None,
        "referring_phc": (
            ", ".join(filter(None, [patient.village, patient.district]))
            if patient is not None and (patient.village or patient.district)
            else None
        ),
        "submitting_worker": worker.full_name if worker is not None else None,
        "scan_date": (upload.uploaded_at if upload is not None else None),
        "eye_laterality": _eye_display(upload.eye_laterality if upload is not None else None),
        # Structured anatomical-visibility flags (Fix 2) derived from the region
        # analysis above — Yes | Partially | No.
        "optic_disc_visible": disc_visible,
        "macula_visible": macula_visible,
        # Professional medical-report fields.
        "report_id": f"NS-{finding.image_id[:8].upper()}",
        "generated_at": datetime.utcnow(),
        "scan_id": finding.image_id,
        "image_quality": upload.quality_status if upload is not None else None,
        "quality_score": upload.quality_score if upload is not None else None,
    }

    structured = build_structured_findings(
        finding, region=region, header=header, upload=upload, gradcam_path=gradcam_path
    )

    report_text = generate_report_text(
        patient_name=header["patient_name"] or "Patient",
        image_id=finding.image_id,
        analyzed_at=finding.analyzed_at,
        structured=structured,
        header=header,
    )

    if report is None:
        report = ScreeningReport(
            image_id=finding.image_id,
            report_text=report_text,
            structured_findings=json.dumps(structured),
            region_notes=region_notes,
            gradcam_path=gradcam_path,
            generation_method="template",
            model_version=finding.model_version,
            generated_at=datetime.utcnow(),
            patient_id=header["patient_id"],
            patient_name=header["patient_name"],
            patient_age=header["patient_age"],
            patient_gender=header["patient_gender"],
            referring_phc=header["referring_phc"],
            submitting_worker=header["submitting_worker"],
            scan_date=header["scan_date"],
            eye_laterality=header["eye_laterality"],
            image_quality=header.get("image_quality"),
            quality_score=header.get("quality_score"),
        )
        db.add(report)
    else:
        report.report_text = report_text
        report.structured_findings = json.dumps(structured)
        report.region_notes = region_notes
        report.gradcam_path = gradcam_path
        report.generation_method = "template"
        report.model_version = finding.model_version
        report.generated_at = datetime.utcnow()
        report.patient_id = header["patient_id"]
        report.patient_name = header["patient_name"]
        report.patient_age = header["patient_age"]
        report.patient_gender = header["patient_gender"]
        report.referring_phc = header["referring_phc"]
        report.submitting_worker = header["submitting_worker"]
        report.scan_date = header["scan_date"]
        report.eye_laterality = header["eye_laterality"]
        report.image_quality = header.get("image_quality")
        report.quality_score = header.get("quality_score")

    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001 — DB write must not break the request
        logger.warning("Could not persist report for %s: %s", finding.image_id, exc)
        db.rollback()

    # Phase 4 — a real report exists: it is now eligible for store-and-forward
    # sync into the telemedicine queue (idempotent).
    try:
        enqueue_sync(db, finding.image_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not enqueue %s for sync: %s", finding.image_id, exc)

    # Phase 4 Part A — the report existing means the case is trackable. Create
    # (or refresh) the case_tracking row with its severity band.
    try:
        ensure_case_tracking(db, finding)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not create case tracking for %s: %s", finding.image_id, exc)
    return report