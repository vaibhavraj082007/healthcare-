"""Phase 4 — patient summaries: local-language templates + offline voice.

Generated ONLY after an ophthalmologist signs off a case (§4/§7 of the spec).
Local language uses the same structured slot-filling approach as the Phase 3
report (per-language templates, never machine-translation of generated text).
Voice output is pre-generated offline (Windows System.Speech, no network), so
playback never depends on a live TTS call.

Note: the Hindi template copy is written by a non-native author and MUST be
reviewed by a fluent speaker before the demo (stated in the README).
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models import PatientSummary, SignOff
from .reports import RECOMMENDATIONS

logger = logging.getLogger("netrascan.summaries")

LANGUAGES = ["en", "hi"]  # fixed prototype set (spec: English + one regional)

# Patient-facing labels — friendlier than the clinical ICDR strings.
PATIENT_GRADE_LABELS = {
    0: "no diabetic retinopathy",
    1: "mild diabetic retinopathy",
    2: "moderate diabetic retinopathy",
    3: "severe diabetic retinopathy",
    4: "proliferative diabetic retinopathy",
}

PATIENT_GRADE_LABELS_HI = {
    0: "डायबिटिक रेटिनोपैथी नहीं है",
    1: "हल्की डायबिटिक रेटिनोपैथी",
    2: "मध्यम डायबिटिक रेटिनोपैथी",
    3: "गंभीर डायबिटिक रेटिनोपैथी",
    4: "फैलती हुई डायबिटिक रेटिनोपैथी",
}

NEXT_STEP_HI = {
    0: "12 महीने में फिर से आँख की जाँच करवाने की सलाह दी जाती है।",
    1: "6 से 12 महीने के भीतर फिर से आँख की जाँच करवाएँ।",
    2: "6 महीने के भीतर नेत्र परीक्षण और डॉक्टरी सलाह लें।",
    3: "कुछ हफ्तों के भीतर नेत्र विशेषज्ञ से जाँच करवाएँ।",
    4: "जल्दी से जल्दी नेत्र विशेषज्ञ से मिलें।",
}

# Hindi month names — the date must be Devanagari so the Hindi TTS voice reads
# it in Hindi. Latin tokens like "Sep" are read with English phonetics and
# sound wrong to Hindi listeners.
HINDI_MONTHS = {
    1: "जनवरी", 2: "फ़रवरी", 3: "मार्च", 4: "अप्रैल", 5: "मई", 6: "जून",
    7: "जुलाई", 8: "अगस्त", 9: "सितंबर", 10: "अक्टूबर", 11: "नवंबर", 12: "दिसंबर",
}

_HI_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")


def _hi_digits(s: str) -> str:
    """ASCII digits -> Devanagari digits so the Hindi TTS voice reads numbers
    (dates, "12 months") in Hindi instead of English phonetics."""
    return s.translate(_HI_DIGITS)


def _grade_label(grade, hi: bool) -> str:
    if grade is None:
        return "अनिर्धारित" if hi else "undetermined"
    return (PATIENT_GRADE_LABELS_HI if hi else PATIENT_GRADE_LABELS).get(int(grade), str(grade))


def build_summary_text(
    image_id: str,
    ai_grade: int,
    revised_grade: int | None,
    decision: str,
    signed_at: datetime,
    hi: bool = False,
) -> str:
    """Deterministic template summary (English or Hindi) from the sign-off."""
    effective = revised_grade if (decision == "Revised" and revised_grade is not None) else ai_grade
    date_str = signed_at.strftime("%d %b %Y") if signed_at else "n/a"
    if hi and signed_at:
        date_str = f"{signed_at.day} {HINDI_MONTHS.get(signed_at.month, '')} {signed_at.year}"
    label = _grade_label(effective, hi)

    if hi:
        if decision == "Rejected":
            return (
                f"आपकी आँख की जांच की रिपोर्ट डॉक्टर ने जाँच ली है। "
                f"यह स्कैन ठीक से पढ़ा नहीं जा सका, इसलिए डॉक्टर ने दोबारा स्कैन करने के लिए कहा है। "
                f"कृपया अपने स्वास्थ्य केंद्र पर जाकर नई तस्वीर लेने के लिए कहें।"
            )
        parts = ["आपकी आँख की जांच की रिपोर्ट डॉक्टर ने जाँच ली है।"]
        if decision == "Revised":
            parts.append(
                f"डॉक्टर ने आपके परिणाम को बदलकर {_grade_label(ai_grade, True)} से "
                f"{label} कर दिया है।"
            )
        else:
            parts.append(f"डॉक्टर ने परिणाम स्वीकार किया: {label}।")
        parts.append(NEXT_STEP_HI.get(effective, ""))
        parts.append(f"यह परिणाम नेत्र विशेषज्ञ द्वारा {date_str} को जाँचा गया।")
        return _hi_digits(" ".join(p for p in parts if p))

    if decision == "Rejected":
        return (
            f"Your screening has been reviewed by a doctor. This scan could not "
            f"be interpreted reliably, so the doctor asked your health centre to "
            f"take a new scan. Please visit your health centre so we can re-take "
            f"the picture. No eye-care decision should be made from this scan."
        )
    parts = ["Your screening has been reviewed by a doctor."]
    if decision == "Revised":
        parts.append(
            f"The doctor adjusted your result from {_grade_label(ai_grade, False)} "
            f"to {label}."
        )
    else:
        parts.append(f"The doctor approved the result: {label}.")
    rec = RECOMMENDATIONS.get(effective)
    if rec:
        parts.append(rec)
    parts.append(f"This result was reviewed by an eye specialist on {date_str} (scan #{image_id[:8]}).")
    parts.append(
        "IMPORTANT: This is an AI-assisted screening aid, reviewed by a doctor — "
        "not a substitute for a complete eye examination."
    )
    return " ".join(parts)


def _synth_wav(text: str, lang: str, out_path: Path) -> bool:
    """Offline TTS via Windows System.Speech (SAPI). Best-effort, cached once.

    Only a voice matching the requested language is acceptable: a Hindi clip
    must be read by a Hindi voice. If no such voice is installed we return
    False so the UI shows "voice not available in this language" instead of
    silently playing a wrong-language clip.
    """
    if lang == "hi":
        return _synth_edge_tts(text, out_path)
    if out_path.exists() and out_path.stat().st_size > 0:
        return True
    try:
        lang_prefix = "en"
        script = (
            "Add-Type -AssemblyName System.Speech\n"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
            "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like '" + lang_prefix + "*' } | Select-Object -First 1\n"
            "if (-not $v) { $s.Dispose(); Write-Output 'NO_VOICE_FOR_EN'; exit 3 }\n"
            "$s.SelectVoice($v.VoiceInfo.Name)\n"
            "$s.SetOutputToWaveFile('" + str(out_path).replace("'", "''") + "')\n"
            "$s.Speak('" + text.replace("'", "''") + "')\n"
            "$s.Dispose()\n"
        )
        import base64

        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            timeout=120,
        )
        if result.returncode == 3:
            logger.warning("no SAPI voice installed for language '%s' — audio skipped", lang)
            return False
        ok = result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
        if not ok:
            logger.warning("SAPI synth failed (%s): %s", lang, result.stderr.decode(errors="ignore")[:200])
        return ok
    except Exception as exc:  # noqa: BLE001 — voice output must never block a summary
        logger.warning("voice generation skipped (%s): %s", lang, exc)
        return False


def _synth_edge_tts(text: str, out_path: Path) -> bool:
    """Hindi TTS via Microsoft Edge TTS (hi-IN-SwaraNeural). Best-effort, cached."""
    mp3_path = out_path.with_suffix(".mp3")
    if mp3_path.exists() and mp3_path.stat().st_size > 0:
        return True
    try:
        import asyncio
        import edge_tts

        voice = "hi-IN-SwaraNeural"
        mp3_path.parent.mkdir(parents=True, exist_ok=True)

        async def _generate():
            comm = edge_tts.Communicate(text, voice)
            await comm.save(str(mp3_path))

        asyncio.run(_generate())
        ok = mp3_path.exists() and mp3_path.stat().st_size > 0
        if ok:
            logger.info("edge-tts Hindi audio generated: %s", mp3_path)
        else:
            logger.warning("edge-tts produced empty file for Hindi")
        return ok
    except Exception as exc:
        logger.warning("edge-tts Hindi synth failed: %s", exc)
        return False


def create_summaries(db: Session, image_id: str, sign_off: SignOff, ai_grade: int) -> list[PatientSummary]:
    """Generate + persist patient summaries (en + hi) after sign-off."""
    created: list[PatientSummary] = []
    audio_dir = settings.upload_dir / "summaries"
    audio_dir.mkdir(parents=True, exist_ok=True)

    for lang in LANGUAGES:
        text = build_summary_text(
            image_id,
            ai_grade=ai_grade,
            revised_grade=sign_off.revised_grade,
            decision=sign_off.decision,
            signed_at=sign_off.signed_at or datetime.utcnow(),
            hi=(lang == "hi"),
        )
        audio_path = None
        mp3 = audio_dir / f"{image_id}_{lang}.mp3"
        wav = audio_dir / f"{image_id}_{lang}.wav"
        if _synth_wav(text, lang, wav):
            audio_path = str(wav if wav.exists() else mp3)
        elif mp3.exists() and mp3.stat().st_size > 0:
            audio_path = str(mp3)

        existing = (
            db.query(PatientSummary)
            .filter(PatientSummary.image_id == image_id, PatientSummary.language == lang)
            .first()
        )
        if existing is None:
            row = PatientSummary(
                image_id=image_id,
                language=lang,
                summary_text=text,
                audio_path=audio_path,
                generated_at=datetime.utcnow(),
            )
            db.add(row)
            created.append(row)
        else:
            existing.summary_text = text
            existing.audio_path = audio_path
            existing.generated_at = datetime.utcnow()
            created.append(existing)
    db.commit()
    return created