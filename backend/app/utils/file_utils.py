"""
Small, dependency-light helpers for safe file handling.
"""
from __future__ import annotations

import os
import re
import uuid

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.\-]+")


def sanitize_filename(filename: str) -> str:
    """Strip path components and unsafe characters from a user-supplied filename."""
    base = os.path.basename(filename or "")
    base = base.strip()
    if not base:
        base = f"upload_{uuid.uuid4().hex}"
    return _SAFE_NAME_RE.sub("_", base)


def get_extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def unique_storage_path(upload_dir: str, filename: str) -> str:
    """
    Build a collision-free path on disk to store the raw upload, while the
    business key exposed via the API remains the (sanitized) original
    filename stored in the database.
    """
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = sanitize_filename(filename)
    unique_prefix = uuid.uuid4().hex[:8]
    return os.path.join(upload_dir, f"{unique_prefix}_{safe_name}")


def parse_bracketed_number(raw: str) -> float | None:
    """
    Financial statements commonly show negative values in parentheses, e.g.
    "(1,234.50)". Convert such strings (or plain numeric strings) to float.
    Returns None if the string cannot be parsed as a number.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    text = text.replace(",", "").replace("₹", "").replace("$", "").replace("€", "")
    text = text.replace("USD", "").replace("INR", "").strip()
    if text in {"-", "—", "–", "NIL", "Nil", "nil", ""}:
        return 0.0 if text != "" else None
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value
