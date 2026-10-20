"""Phase 4 Part A — constrained natural-language search for the doctor queue.

The vendor path (Anthropic) is used ONLY when ``ANTHROPIC_API_KEY`` is set in
the environment; otherwise a deterministic keyword parser is used so the demo
works fully offline. Either path yields the SAME small structured filter object
— never free SQL and never a general Q&A response. Unparseable queries return
``matched=False`` with a human message.

Accepted filter dimensions (all optional, validated against this schema):

    severity_band  -> Low | Medium | High
    status         -> New | Claimed | Contacted | Reviewed
    consistency    -> flag | consistent
    phc            -> an exact village/district catchment name in the DB
    from_date      -> YYYY-MM-DD (scan uploaded on/after)
    to_date        -> YYYY-MM-DD (scan uploaded on/before)
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib import request as urlrequest
from urllib.error import URLError

from sqlalchemy import distinct
from sqlalchemy.orm import Session

from .models import Patient

KNOWN_FILTER_KEYS = {"severity_band", "status", "consistency", "phc", "from_date", "to_date"}


def _validate_filter(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only the allowed dimensions with safe, canonical values."""
    out: dict[str, Any] = {}

    band = raw.get("severity_band")
    if isinstance(band, str):
        normalized = band.strip().title()
        if normalized in ("Low", "Medium", "High"):
            out["severity_band"] = normalized

    status = raw.get("status")
    if isinstance(status, str):
        normalized = status.strip().title()
        if normalized in ("New", "Claimed", "Contacted", "Reviewed"):
            out["status"] = normalized

    consistency = raw.get("consistency")
    if isinstance(consistency, str):
        c = consistency.strip().lower()
        if c in ("flag", "flagged"):
            out["consistency"] = "flag"
        elif c in ("consistent", "ok"):
            out["consistency"] = "consistent"

    phc = raw.get("phc")
    if isinstance(phc, str) and phc.strip():
        out["phc"] = phc.strip()

    for key in ("from_date", "to_date"):
        value = raw.get(key)
        if isinstance(value, str):
            try:
                datetime.strptime(value, "%Y-%m-%d")
                out[key] = value
            except ValueError:
                pass

    return out


def _message_for(filters: dict[str, Any], query: str) -> str:
    if not filters:
        return (
            "I couldn't turn that into a case filter. Try phrases like "
            '"high severity cases", "new cases in Ramanagara" or '
            '"flagged scans from this week".'
        )
    parts: list[str] = []
    if "severity_band" in filters:
        parts.append(f"severity {filters['severity_band']}")
    if "status" in filters:
        parts.append(f"status {filters['status']}")
    if "consistency" in filters:
        parts.append(f"{filters['consistency']} consistency")
    if "phc" in filters:
        parts.append(f'PHC/village "{filters["phc"]}"')
    if "from_date" in filters or "to_date" in filters:
        window = f"from {filters.get('from_date')}" if "from_date" in filters else ""
        window += f" to {filters.get('to_date')}" if "to_date" in filters else ""
        parts.append(window.strip())
    return "Matched " + ", ".join(parts) + f" for: {query.strip()!r}"


# ---------------------------------------------------------------------------
# Vendor path (Anthropic) — only when a key exists
# ---------------------------------------------------------------------------

_ANTHROPIC_SCHEMA = {
    "severity_band": "Low|Medium|High|null",
    "status": "New|Claimed|Contacted|Reviewed|null",
    "consistency": "flag|consistent|null",
    "phc": "exact village or PHC catchment name from the provided list|null",
    "from_date": "YYYY-MM-DD or null",
    "to_date": "YYYY-MM-DD or null",
}

_SYSTEM_PROMPT = (
    "You convert a clinician's free-text request into a JSON filter object for a "
    "diabetic-retinopathy screening queue. Respond with ONLY a single JSON object "
    f"using these keys: {json.dumps(_ANTHROPIC_SCHEMA)}. "
    "Null out every dimension you cannot confidently determine. Never invent a PHC "
    "name: only pick one from the provided candidate list. Never answer general "
    "questions — if you cannot map the request onto this schema, return an empty "
    'object {}.'
)


def _try_anthropic(query: str, candidate_phcs: list[str]) -> Optional[dict[str, Any]]:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_KEY")
    if not api_key:
        return None

    user_content = (
        f"User request: {query}\n"
        f"Candidate PHC/village names: {json.dumps(candidate_phcs)}\n"
        "Today's date is " + datetime.utcnow().date().isoformat() + "."
    )
    payload = json.dumps(
        {
            "model": "claude-3-5-haiku-latest",
            "max_tokens": 300,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_content}],
        }
    ).encode("utf-8")

    req = urlrequest.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None

    text = ""
    for block in body.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
    if not text.strip():
        return None

    match = re.search(r"\{[^{}]*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    return _validate_filter(raw)


# ---------------------------------------------------------------------------
# Local deterministic parser — offline fallback
# ---------------------------------------------------------------------------

_BAND_TERMS = {
    "High": ("severe", "high", "urgent", "critical"),
    "Medium": ("moderate", "medium", "middle"),
    "Low": ("low", "mild", "minor", "no dr", "no retinopathy", "no diabetic"),
}

_STATUS_TERMS = {
    "New": ("new", "fresh", "unclaimed", "pending"),
    "Claimed": ("claimed",),
    "Contacted": ("contacted", "follow up", "follow-up", "following"),
    "Reviewed": ("reviewed", "signed", "done", "complete"),
}

_TIME_TERMS = {
    "today": (re.compile(r"\btoday\b"), 0),
    "week": (re.compile(r"\b(this|past|last) week\b"), 7),
    "month": (re.compile(r"\b(this|past|last) month\b"), 30),
}


def _local_parser(query: str, candidate_phcs: list[str]) -> dict[str, Any]:
    """Keyword/date matching over the fixed filter schema."""
    lowered = query.lower().strip()
    filters: dict[str, Any] = {}

    for band, terms in _BAND_TERMS.items():
        if any(term in lowered for term in terms):
            filters["severity_band"] = band
            break

    for status, terms in _STATUS_TERMS.items():
        if any(term in lowered for term in terms):
            filters["status"] = status
            break

    if "flag" in lowered or "inconsist" in lowered:
        filters["consistency"] = "flag"
    elif "consistent" in lowered:
        filters["consistency"] = "consistent"

    for term in candidate_phcs:
        if term and term.lower() in lowered:
            filters["phc"] = term
            break

    today = datetime.utcnow().date()
    for key, (pattern, days) in _TIME_TERMS.items():
        if pattern.search(lowered):
            if days == 0:
                filters["from_date"] = today.isoformat()
                filters["to_date"] = today.isoformat()
            else:
                filters["from_date"] = (today - timedelta(days=days)).isoformat()
            break

    return filters


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def parse_nl_filter(query: str, db: Session) -> dict[str, Any]:
    """Return ``{matched, filter, message}`` from a free-text query."""
    searchable = query.strip()
    if not searchable:
        return {"matched": False, "filter": {}, "message": "Type a search, e.g. “high severity cases”."}

    candidate_phcs = [
        str(name)
        for name in sorted(
            set(
                list(
                    db.query(distinct(Patient.village))
                    .filter(Patient.village.isnot(None))
                    .all()
                )
                + list(
                    db.query(distinct(Patient.district))
                    .filter(Patient.district.isnot(None))
                    .all()
                )
            )
        )
        if name
    ]

    filters = _try_anthropic(searchable, candidate_phcs)
    if filters is None:
        filters = _local_parser(searchable, candidate_phcs)
        filters = _validate_filter(filters)

    if not filters:
        return {
            "matched": False,
            "filter": {},
            "message": _message_for({}, searchable),
        }
    filters = {key: value for key, value in filters.items() if value not in (None, "", [])}
    return {
        "matched": True,
        "filter": filters,
        "message": _message_for(filters, searchable),
    }