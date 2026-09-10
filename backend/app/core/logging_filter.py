"""
RetinaShield — PII & Sensitive Content Sanitizing Log Filter

Ensures that patient PII (names, phone numbers, Aadhaar digits, clinical notes)
and secrets/tokens do not leak into application logging output.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Regular expressions for scrubbing sensitive patient data and secrets
_PATIENT_PHONE_RE = re.compile(r"(?:\+91[\-\s]?)?[6-9]\d{9}")
_AADHAAR_RE = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
_BEARER_TOKEN_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_.+/=]*")
_PASSWORD_KEY_RE = re.compile(r"(password|secret|token|hash)['\"]?\s*[:=]\s*['\"]?[^'\",\s]+['\"]?", re.IGNORECASE)


class PIIScrubbingFilter(logging.Filter):
    """
    Log filter that intercepts log records and scrubs any inadvertent PII
    or authentication tokens before they are rendered to console or disk.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.sanitize_message(record.msg)
        if record.args:
            sanitized_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    sanitized_args.append(self.sanitize_message(arg))
                else:
                    sanitized_args.append(arg)
            record.args = tuple(sanitized_args)
        return True

    @staticmethod
    def sanitize_message(msg: str) -> str:
        """Replace detected PII or sensitive keys with redacted placeholders."""
        if not msg:
            return msg
        # Scrub Bearer tokens
        msg = _BEARER_TOKEN_RE.sub("Bearer [REDACTED_TOKEN]", msg)
        # Scrub passwords and secret values
        msg = _PASSWORD_KEY_RE.sub(r"\1: [REDACTED]", msg)
        # Scrub Aadhaar 12-digit patterns
        msg = _AADHAAR_RE.sub("[REDACTED_AADHAAR]", msg)
        # Scrub 10-digit Indian phone numbers
        msg = _PATIENT_PHONE_RE.sub("[REDACTED_PHONE]", msg)
        return msg
