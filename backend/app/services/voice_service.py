"""
RetinaShield — Offline Local Voice Playback Service

Privacy & Safety Architecture:
1. OPT-IN CONSENT MANDATORY: Voice playback strictly requires explicit user/patient
   consent (`voice_consent=True`). Requests without consent are rejected.
2. ZERO EXTERNAL NETWORK CALLS: Uses only local offline speech synthesis tools
   (e.g., macOS native `say` + `afconvert`, or system speech).
   Never transmits patient data or screening text to any third-party cloud API.
3. UNSUPPORTED VOICE DETECTION: Dynamically detects whether a compatible local
   voice is installed for the target language (e.g., 'hi' -> 'Lekha', 'en' -> system English).
   If no matching voice is available, cleanly falls back to text with a structured diagnostic.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Preferred offline voice identifiers
PREFERRED_VOICES: dict[str, list[str]] = {
    "hi": ["Lekha", "hi_IN", "Hindi"],
    "en": ["Samantha", "Daniel", "Alex", "Victoria", "en_US", "en_GB"],
}


@dataclass
class VoiceSynthesisResult:
    voice_supported: bool
    fallback_to_text: bool
    voice_name: str | None
    language: str
    audio_base64: str | None
    audio_format: str | None
    spoken_text: str
    status_message: str


def get_available_local_voices() -> dict[str, list[str]]:
    """Query local offline TTS voices available on the operating system."""
    voices: dict[str, list[str]] = {"en": [], "hi": [], "other": []}
    say_bin = shutil.which("say")
    if not say_bin:
        return voices

    try:
        proc = subprocess.run(
            [say_bin, "-v", "?"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    name = parts[0]
                    locale = parts[1].lower()
                    if "hi" in locale:
                        voices["hi"].append(name)
                    elif "en" in locale:
                        voices["en"].append(name)
                    else:
                        voices["other"].append(name)
    except Exception as exc:
        logger.warning("Failed to inspect local voices: %s", exc)

    return voices


def find_compatible_voice(language: str) -> str | None:
    """Find a locally installed voice matching the requested language code."""
    lang = language.lower()
    local_voices = get_available_local_voices()
    available_for_lang = local_voices.get(lang, [])

    preferred = PREFERRED_VOICES.get(lang, [])
    for pref in preferred:
        for av in available_for_lang:
            if pref.lower() in av.lower():
                return av

    # Return any available voice for that language
    if available_for_lang:
        return available_for_lang[0]

    return None


def synthesize_offline_audio(
    spoken_text: str,
    language: str = "en",
    voice_consent: bool = False,
) -> VoiceSynthesisResult:
    """
    Synthesize offline audio using local tools with fallback to text.

    Args:
        spoken_text: Cleaned text to be spoken.
        language: Language code ('en', 'hi', etc.).
        voice_consent: Explicit consent flag for audio playback.

    Returns:
        VoiceSynthesisResult containing audio or text fallback details.
    """
    lang = language.lower()

    # 1. Safeguard: Opt-in consent check
    if not voice_consent:
        return VoiceSynthesisResult(
            voice_supported=False,
            fallback_to_text=True,
            voice_name=None,
            language=lang,
            audio_base64=None,
            audio_format=None,
            spoken_text=spoken_text,
            status_message="Audio playback declined or consent not provided. Displaying text.",
        )

    # 2. Check for local speech synthesis binaries
    say_bin = shutil.which("say")
    if not say_bin:
        return VoiceSynthesisResult(
            voice_supported=False,
            fallback_to_text=True,
            voice_name=None,
            language=lang,
            audio_base64=None,
            audio_format=None,
            spoken_text=spoken_text,
            status_message="Local speech synthesis binary ('say') not available on host system. Fallback to on-screen text.",
        )

    # 3. Detect matching voice for requested language
    voice_name = find_compatible_voice(lang)
    if not voice_name:
        return VoiceSynthesisResult(
            voice_supported=False,
            fallback_to_text=True,
            voice_name=None,
            language=lang,
            audio_base64=None,
            audio_format=None,
            spoken_text=spoken_text,
            status_message=f"No offline voice installed for language '{lang}'. Fallback to on-screen text.",
        )

    # 4. Generate local audio file in secure temp directory
    with tempfile.TemporaryDirectory(prefix="retinashield_tts_") as tmpdir:
        aiff_path = os.path.join(tmpdir, "speech.aiff")
        wav_path = os.path.join(tmpdir, "speech.wav")

        try:
            # Generate AIFF using macOS say
            cmd = [say_bin, "-v", voice_name, spoken_text, "-o", aiff_path]
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                check=False,
            )
            if proc.returncode != 0 or not os.path.isfile(aiff_path):
                raise RuntimeError(f"'say' exited with code {proc.returncode}: {proc.stderr.decode('utf-8', errors='replace')}")

            # Convert to standard PCM WAV via afconvert if available
            afconvert_bin = shutil.which("afconvert")
            final_audio_path = aiff_path
            audio_format = "audio/aiff"

            if afconvert_bin:
                conv_cmd = [afconvert_bin, "-f", "WAVE", "-d", "LEI16", aiff_path, wav_path]
                conv_proc = subprocess.run(
                    conv_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=10,
                    check=False,
                )
                if conv_proc.returncode == 0 and os.path.isfile(wav_path):
                    final_audio_path = wav_path
                    audio_format = "audio/wav"

            with open(final_audio_path, "rb") as f:
                audio_bytes = f.read()

            b64_audio = base64.b64encode(audio_bytes).decode("ascii")

            return VoiceSynthesisResult(
                voice_supported=True,
                fallback_to_text=False,
                voice_name=voice_name,
                language=lang,
                audio_base64=b64_audio,
                audio_format=audio_format,
                spoken_text=spoken_text,
                status_message=f"Offline audio generated using local voice '{voice_name}'.",
            )

        except Exception as exc:
            logger.warning("Local voice synthesis failed: %s; falling back to text", exc)
            return VoiceSynthesisResult(
                voice_supported=False,
                fallback_to_text=True,
                voice_name=voice_name,
                language=lang,
                audio_base64=None,
                audio_format=None,
                spoken_text=spoken_text,
                status_message=f"Local voice synthesis failed: {str(exc)}. Fallback to on-screen text.",
            )
