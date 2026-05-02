"""Tiny shared helpers used by app.py and the route blueprints.

Keeping these here (rather than in app.py) avoids the circular-import
trap when blueprint modules need them — blueprint modules can't safely
import from app.py because app.py imports the blueprint registrations.
"""
from __future__ import annotations
import re
import unicodedata


def sanitize_filename(title: str, ext: str) -> str:
    """Produce a safe download_name. Falls back to a placeholder when empty.

    NFC-normalize, drop control chars and bad filename chars (matches the
    Win/Mac/Linux intersection of disallowed bytes), trim to 150 chars.
    """
    if not title:
        return f"trove-download{ext}"
    s = unicodedata.normalize("NFC", title)
    s = "".join(ch for ch in s if ch.isprintable())
    s = re.sub(r'[\\/:*?"<>|]+', "", s)
    s = s.strip().strip(".")
    s = s[:150].strip()
    return f"{s}{ext}" if s else f"trove-download{ext}"
