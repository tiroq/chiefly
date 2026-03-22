"""
ChieflyNotesCodec — encode/decode Chiefly metadata envelope in Google Task notes.

Format:
    <user notes text>

    --- chiefly:v1 ---
    {"stable_id": "...", "project": "...", ...}
    --- /chiefly ---

Rules:
- Parser tolerates missing/invalid envelope (returns None).
- Writer preserves user text above and below the envelope.
- Envelope replacement: calling format() on notes that already have an envelope replaces it.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

ENVELOPE_START = "--- chiefly:v1 ---"
ENVELOPE_END = "--- /chiefly ---"

_ENVELOPE_PATTERN = re.compile(
    r"\n?--- chiefly:v1 ---\n.*?\n--- /chiefly ---\n?",
    re.DOTALL,
)


def parse(notes: str | None) -> dict[str, Any] | None:
    """
    Extract Chiefly metadata from Google Task notes.

    Returns a dict with at least 'stable_id' (as str) on success, or None
    if no valid envelope is found.
    """
    if not notes:
        return None

    start_idx = notes.find(ENVELOPE_START)
    if start_idx == -1:
        return None

    end_idx = notes.find(ENVELOPE_END, start_idx)
    if end_idx == -1:
        return None

    json_start = start_idx + len(ENVELOPE_START)
    json_str = notes[json_start:end_idx].strip()

    if not json_str:
        return None

    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    if "stable_id" not in data:
        return None

    return data


def format(
    stable_id: UUID,
    metadata: dict[str, Any],
    existing_notes: str | None = None,
) -> str:
    """
    Build Google Task notes with Chiefly metadata envelope.

    If existing_notes already contains an envelope, it is replaced.
    User text outside the envelope is preserved.

    Args:
        stable_id: The task's stable UUID identity.
        metadata: Dict of business metadata (project, kind, confidence, etc.).
        existing_notes: Current notes content (may already contain an envelope).

    Returns:
        Notes string with the envelope appended/replaced.
    """
    payload = {"stable_id": str(stable_id), **metadata}
    envelope = f"\n{ENVELOPE_START}\n{json.dumps(payload, separators=(',', ':'))}\n{ENVELOPE_END}"

    if existing_notes is None:
        return envelope.lstrip("\n")

    cleaned = _ENVELOPE_PATTERN.sub("", existing_notes).rstrip()

    if cleaned:
        return cleaned + "\n" + envelope.lstrip("\n")
    else:
        return envelope.lstrip("\n")


def extract_user_notes(notes: str | None) -> str:
    """
    Return only the user-written portion of the notes, stripping the Chiefly envelope.
    """
    if not notes:
        return ""
    cleaned = _ENVELOPE_PATTERN.sub("", notes)
    return cleaned.strip()
