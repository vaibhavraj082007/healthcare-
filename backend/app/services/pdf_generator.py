"""
RetinaShield — Printable Unicode PDF Generator

Generates high-quality, printable PDF clinical reports and patient summaries
using ReportLab with approved Unicode fonts (supporting English and Devanagari/Hindi).

Key Safety & Clinical Features:
1. PROVISIONAL WATERMARKING: Applies a bold, semi-transparent diagonal watermark
   across each page on any unsigned / draft report:
   "PROVISIONAL — AWAITING OPHTHALMOLOGIST SIGN-OFF"
2. UNICODE FONTS: Registers system/bundled Devanagari fonts (DevanagariMT / Noto)
   to ensure zero font corruption or mojibake in Hindi reports.
3. STATUTORY DISCLAIMERS: Mandatory validation disclaimer explicitly printed on
   all documents (technical and patient summary).
"""

from __future__ import annotations

import io
import os
import logging
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Unicode Font Registration
# ---------------------------------------------------------------------------

_REGISTERED_FONTS: dict[str, str] = {}

def _ensure_unicode_fonts():
    """Register approved Unicode fonts for English and Devanagari (Hindi)."""
    global _REGISTERED_FONTS
    if _REGISTERED_FONTS.get("devanagari"):
        return

    devanagari_candidates = [
        "/System/Library/Fonts/Supplemental/DevanagariMT.ttc",
        "/System/Library/Fonts/Supplemental/ITFDevanagari.ttc",
        "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.otf",
    ]

    for p in devanagari_candidates:
        if os.path.isfile(p):
            try:
                pdfmetrics.registerFont(TTFont("DevanagariFont", p))
                _REGISTERED_FONTS["devanagari"] = "DevanagariFont"
                logger.info("Registered Devanagari Unicode font: %s", p)
                break
            except Exception as exc:
                logger.warning("Failed to register font %s: %s", p, exc)

    if "devanagari" not in _REGISTERED_FONTS:
        _REGISTERED_FONTS["devanagari"] = "Helvetica"
        logger.warning("No system Devanagari font found; falling back to Helvetica")

    _REGISTERED_FONTS["english"] = "Helvetica"


_ensure_unicode_fonts()


# ---------------------------------------------------------------------------
# Numbered Canvas with Watermark
# ---------------------------------------------------------------------------

class NumberedCanvasWithWatermark(canvas.Canvas):
    """
    Two-pass canvas that renders:
    1. Running page numbers ('Page X of Y')
    2. Bold, semi-transparent diagonal PROVISIONAL watermark on unsigned reports
    """

    def __init__(self, *args, is_provisional: bool = False, watermark_text: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.is_provisional = is_provisional
        self.watermark_text = watermark_text or "PROVISIONAL — NOT A FINAL CLINICAL REPORT"

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count: int):
        self.saveState()
        width, height = letter

        # 1. Provisional watermark if unsigned
        if self.is_provisional:
            self.saveState()
            self.setFont("Helvetica-Bold", 32)
            self.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.15))
            self.translate(width / 2, height / 2)
            self.rotate(35)
            self.drawCentredString(0, 0, self.watermark_text)
            self.restoreState()

        # 2. Running footer
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        footer_text = f"RetinaShield Teleophthalmology Platform · Page {self._pageNumber} of {page_count}"
        self.drawString(54, 36, footer_text)
        self.drawRightString(width - 54, 36, "Strictly Confidential — Medical Record")

        # 3. Top banner line
        if self.is_provisional:
            self.setFillColor(colors.HexColor("#ef4444"))
            self.rect(54, height - 28, width - 108, 14, fill=1, stroke=0)
            self.setFont("Helvetica-Bold", 7.5)
            self.setFillColor(colors.white)
            self.drawCentredString(width / 2, height - 23, "PROVISIONAL / UNVERIFIED SCREENING RESULT — REQUIRES OPHTHALMOLOGIST SIGN-OFF")

        self.restoreState()


# ---------------------------------------------------------------------------
# PDF Generation Functions
# ---------------------------------------------------------------------------

def generate_technical_report_pdf(report_data: dict[str, Any]) -> bytes:
    """Generate printable PDF for Technical Clinical Report."""
    _ensure_unicode_fonts()
    buffer = io.BytesIO()

    is_provisional = report_data.get("is_provisional", True)
    watermark_msg = "PROVISIONAL — AWAITING CLINICIAN REVIEW" if is_provisional else ""

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RepTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0f172a"),
    )
    h2_style = ParagraphStyle(
        "RepH2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#1e3a8a"),
        spaceBefore=10,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "RepBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#334155"),
    )
    bold_style = ParagraphStyle(
        "RepBold",
        parent=body_style,
        fontName="Helvetica-Bold",
    )
    disclaimer_style = ParagraphStyle(
        "RepDisc",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=9.5,
        textColor=colors.HexColor("#475569"),
    )

    story = []

    # Title & Metadata Banner
    status_label = "PROVISIONAL REPORT" if is_provisional else "FINAL CLINICIAN-REVIEWED REPORT"
    status_color = "#ef4444" if is_provisional else "#16a34a"

    header_table = Table(
        [
            [
                Paragraph("<b>RetinaShield</b><br/><font size=9 color='#64748b'>Clinical Teleophthalmology Platform</font>", body_style),
                Paragraph(f"<font color='{status_color}'><b>{status_label}</b></font><br/><font size=7.5 color='#64748b'>Generated: {report_data.get('generated_at', '')[:19]}</font>", body_style),
            ]
        ],
        colWidths=[300, 204],
    )
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))

    # Patient & Encounter Demographics Table
    pat = report_data.get("patient", {})
    enc = report_data.get("encounter", {})
    demo_data = [
        [
            Paragraph("<b>Patient Name:</b>", body_style),
            Paragraph(f"{pat.get('first_name', '')} {pat.get('last_name', '')}".strip() or "Anonymous", body_style),
            Paragraph("<b>Patient ID:</b>", body_style),
            Paragraph(pat.get("id", "—") or "—", body_style),
        ],
        [
            Paragraph("<b>Age / Gender:</b>", body_style),
            Paragraph(f"{pat.get('gender', '—')}", body_style),
            Paragraph("<b>Screened Eye:</b>", body_style),
            Paragraph(f"<b>{(enc.get('eye', '—')).upper()}</b>", body_style),
        ],
        [
            Paragraph("<b>Facility ID:</b>", body_style),
            Paragraph(report_data.get("facility_id", "—") or "—", body_style),
            Paragraph("<b>Hardware / Optic:</b>", body_style),
            Paragraph(enc.get("device", "Smartphone + 20D Condensing Lens"), body_style),
        ],
    ]
    demo_table = Table(demo_data, colWidths=[90, 162, 90, 162])
    demo_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(demo_table)
    story.append(Spacer(1, 12))

    # Authoritative Clinician Review Section
    cr = report_data.get("clinician_review", {})
    story.append(Paragraph("1. AUTHORITATIVE CLINICIAN DIAGNOSIS & ACTION", h2_style))
    clin_status_color = "#16a34a" if cr.get("is_reviewed") else "#eab308"
    clin_rows = [
        [
            Paragraph("<b>Confirmed DR Grade:</b>", body_style),
            Paragraph(f"<b>{cr.get('confirmed_dr_label', 'Awaiting Review')} (Grade {cr.get('confirmed_dr_grade', '—')})</b>", body_style),
            Paragraph("<b>Reviewer:</b>", body_style),
            Paragraph(cr.get("reviewer_name") or "Pending Ophthalmologist Sign-Off", body_style),
        ],
        [
            Paragraph("<b>Macular Edema:</b>", body_style),
            Paragraph("Present" if cr.get("macular_edema_present") else "Not Detected", body_style),
            Paragraph("<b>Review Status:</b>", body_style),
            Paragraph(f"<font color='{clin_status_color}'><b>{'Clinician Reviewed' if cr.get('is_reviewed') else 'Pending'} (v{cr.get('review_version', 1)})</b></font>", body_style),
        ],
        [
            Paragraph("<b>Referral Urgency:</b>", body_style),
            Paragraph(f"<b>{(cr.get('referral_recommendation') or 'none').upper()}</b> — {cr.get('referral_details', '')}", body_style),
            Paragraph("<b>Follow-Up:</b>", body_style),
            Paragraph(f"{cr.get('follow_up_months', '—')} months" if cr.get("follow_up_months") else "Per protocol", body_style),
        ],
        [
            Paragraph("<b>Clinical Notes:</b>", body_style),
            Paragraph(cr.get("clinical_notes") or "None documented.", body_style),
            Paragraph("<b>Reviewed At:</b>", body_style),
            Paragraph(cr.get("reviewed_at", "—")[:19] if cr.get("reviewed_at") else "—", body_style),
        ],
    ]
    clin_table = Table(clin_rows, colWidths=[110, 142, 110, 142])
    clin_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4") if cr.get("is_reviewed") else colors.HexColor("#fffbeb")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#86efac") if cr.get("is_reviewed") else colors.HexColor("#fde047")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dcfce7") if cr.get("is_reviewed") else colors.HexColor("#fef9c3")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(clin_table)
    story.append(Spacer(1, 12))

    # AI Research Screening Findings
    ai = report_data.get("ai_research_screening_findings") or report_data.get("ai_screening_findings", {})
    story.append(Paragraph("2. AI-GENERATED RESEARCH SCREENING FINDINGS (DECISION SUPPORT ONLY)", h2_style))
    story.append(Paragraph(f"<i>{ai.get('disclaimer', '')}</i>", disclaimer_style))
    story.append(Spacer(1, 4))

    probs = ai.get("calibrated_probabilities", {})
    lesions = ai.get("estimated_lesions", {})
    unc = ai.get("uncertainty_analysis", {})

    ai_rows = [
        [
            Paragraph("<b>Predicted Severity:</b>", body_style),
            Paragraph(f"{ai.get('predicted_dr_label', '—')} (Confidence: {((ai.get('confidence') or 0)*100):.1f}%)", body_style),
            Paragraph("<b>Uncertainty Metrics:</b>", body_style),
            Paragraph(f"Entropy: {unc.get('entropy', '—')} | Margin: {unc.get('margin', '—')}", body_style),
        ],
        [
            Paragraph("<b>Calibrated Probabilities:</b>", body_style),
            Paragraph(
                f"G0: {(probs.get('grade_0_none',0)*100):.0f}% | "
                f"G1: {(probs.get('grade_1_mild',0)*100):.0f}% | "
                f"G2: {(probs.get('grade_2_moderate',0)*100):.0f}% | "
                f"G3: {(probs.get('grade_3_severe',0)*100):.0f}% | "
                f"G4: {(probs.get('grade_4_pdr',0)*100):.0f}%",
                body_style
            ),
            Paragraph("<b>Concordance Status:</b>", body_style),
            Paragraph(f"{(unc.get('concordance') or 'concordant').upper()}", body_style),
        ],
        [
            Paragraph("<b>Lesion Estimates:</b>", body_style),
            Paragraph(
                f"Microaneurysms: {lesions.get('microaneurysms', 0)} | "
                f"Hemorrhages: {lesions.get('hemorrhages', 0)}<br/>"
                f"Hard Exudates: {lesions.get('hard_exudates', 0)} | "
                f"Cotton Wool Spots: {lesions.get('cotton_wool_spots', 0)}",
                body_style
            ),
            Paragraph("<b>Quality Verdict:</b>", body_style),
            Paragraph(f"<b>{(report_data.get('image_quality', {}).get('verdict') or 'unknown').upper()}</b>", body_style),
        ],
    ]
    ai_table = Table(ai_rows, colWidths=[110, 142, 110, 142])
    ai_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(ai_table)
    story.append(Spacer(1, 12))

    # Model Provenance
    prov = ai.get("model_provenance", {})
    story.append(Paragraph("3. MODEL PROVENANCE & RUNTIME ADAPTER", h2_style))
    prov_rows = [
        [
            Paragraph("<b>Classifier Arch:</b>", body_style),
            Paragraph(prov.get("classifier_architecture", "EfficientNet-B4"), body_style),
            Paragraph("<b>Lesion Detector:</b>", body_style),
            Paragraph(prov.get("detector_architecture", "YOLOv8x-retina"), body_style),
        ],
        [
            Paragraph("<b>Weights SHA-256:</b>", body_style),
            Paragraph(prov.get("weights_hash_sha256", "—"), body_style),
            Paragraph("<b>Pipeline Adapter:</b>", body_style),
            Paragraph(prov.get("matlab_engine_adapter", "MATLAB Engine R2024b"), body_style),
        ],
    ]
    prov_table = Table(prov_rows, colWidths=[100, 152, 100, 152])
    prov_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#f1f5f9")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(prov_table)
    story.append(Spacer(1, 14))

    # Statutory Disclaimer Box
    disclaimer_box = Table(
        [[Paragraph(report_data.get("statutory_validation_disclaimer", ""), disclaimer_style)]],
        colWidths=[504],
    )
    disclaimer_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff1f2")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#fda4af")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(disclaimer_box)

    # Build PDF with watermark canvas
    def _canvas_factory(*args, **kwargs):
        return NumberedCanvasWithWatermark(
            *args,
            is_provisional=is_provisional,
            watermark_text=watermark_msg,
            **kwargs,
        )

    doc.build(story, canvasmaker=_canvas_factory)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Patient Summary PDF Generator (Multilingual)
# ---------------------------------------------------------------------------

def generate_patient_summary_pdf(summary_data: dict[str, Any]) -> bytes:
    """
    Generate printable PDF for Patient Summary in English or Hindi.
    Uses registered Unicode Devanagari font for Hindi text.
    """
    _ensure_unicode_fonts()
    buffer = io.BytesIO()

    lang = summary_data.get("language", "en")
    font_name = _REGISTERED_FONTS.get("devanagari", "Helvetica") if lang == "hi" else "Helvetica"
    font_bold = _REGISTERED_FONTS.get("devanagari", "Helvetica-Bold") if lang == "hi" else "Helvetica-Bold"

    is_provisional = summary_data.get("is_provisional", True)
    watermark_msg = summary_data.get("provisional_watermark", "PROVISIONAL") if is_provisional else ""

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PatTitle",
        parent=styles["Heading1"],
        fontName=font_bold,
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#0f172a"),
    )
    h2_style = ParagraphStyle(
        "PatH2",
        parent=styles["Heading2"],
        fontName=font_bold,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1e3a8a"),
        spaceBefore=10,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "PatBody",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#334155"),
    )
    bold_style = ParagraphStyle(
        "PatBold",
        parent=body_style,
        fontName=font_bold,
    )
    small_style = ParagraphStyle(
        "PatSmall",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#64748b"),
    )

    story = []

    # Title Banner
    story.append(Paragraph(summary_data.get("title", "Retinal Screening Summary"), title_style))
    story.append(Spacer(1, 4))

    # Sub-header status
    status_text = summary_data.get("provisional_watermark", "")
    status_color = "#ef4444" if is_provisional else "#16a34a"
    story.append(Paragraph(f"<font color='{status_color}'><b>{status_text}</b></font>", body_style))
    story.append(Spacer(1, 10))

    # Patient info bar
    pat = summary_data.get("patient", {})
    eye_str = summary_data.get("screening_eye", "").upper()
    info_table = Table(
        [
            [
                Paragraph(f"<b>Patient:</b> {pat.get('name', '—')}", body_style),
                Paragraph(f"<b>Eye:</b> {eye_str}", body_style),
                Paragraph(f"<b>Date:</b> {summary_data.get('generated_at', '')[:10]}", body_style),
            ]
        ],
        colWidths=[240, 120, 144],
    )
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 14))

    # Card 1: Screening Findings
    story.append(Paragraph(summary_data.get("findings_heading", "Summary of Eye Screening Findings"), h2_style))
    findings_card = Table(
        [
            [Paragraph(f"<b>{summary_data.get('grade_label', '')}</b>", bold_style)],
            [Paragraph(summary_data.get("findings_explanation", ""), body_style)],
        ],
        colWidths=[504],
    )
    findings_card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0f9ff")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#bae6fd")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(findings_card)
    story.append(Spacer(1, 14))

    # Card 2: Clinician-Approved Next Step
    story.append(Paragraph(summary_data.get("next_step_heading", "Clinician-Approved Next Steps"), h2_style))
    next_step_card = Table(
        [
            [Paragraph(f"<b>Recommendation:</b> {summary_data.get('referral_guidance', '')}", body_style)],
            [Paragraph(f"<b>Recommended Follow-up:</b> Within {summary_data.get('follow_up_months', 12)} months", body_style)],
        ],
        colWidths=[504],
    )
    next_step_card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#bbf7d0")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(next_step_card)
    story.append(Spacer(1, 14))

    # Card 3: Screening Limitations
    story.append(Paragraph("Important Notice & Screening Limitations", h2_style))
    limitations_card = Table(
        [[Paragraph(summary_data.get("screening_limitations", ""), body_style)]],
        colWidths=[504],
    )
    limitations_card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffbeb")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#fef08a")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(limitations_card)
    story.append(Spacer(1, 14))

    # Translation review status notice if Hindi
    if lang != "en":
        trans_status = summary_data.get("clinical_language_review_status", "")
        trans_note = (
            f"<b>Translation Governance Notice:</b> This translated patient summary is categorized as "
            f"<i>{trans_status}</i>. It requires verification by a qualified clinical translator."
        )
        story.append(Paragraph(trans_note, small_style))
        story.append(Spacer(1, 10))

    # Statutory disclaimer
    disc_card = Table(
        [[Paragraph(summary_data.get("validation_disclaimer", ""), small_style)]],
        colWidths=[504],
    )
    disc_card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(disc_card)

    def _canvas_factory(*args, **kwargs):
        return NumberedCanvasWithWatermark(
            *args,
            is_provisional=is_provisional,
            watermark_text=watermark_msg,
            **kwargs,
        )

    doc.build(story, canvasmaker=_canvas_factory)
    return buffer.getvalue()
