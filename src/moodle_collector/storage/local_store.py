"""Compatibility facade for the shared HSAS atomic storage layer."""

from __future__ import annotations

import re

from hsas_runtime.storage import (
    atomic_write as _atomic_write,
    read_json,
    read_text,
    write_bytes,
    write_json,
    write_model,
    write_text,
)


def safe_filename(value: str) -> str:
    """Return a conservative filename component for local course artifacts."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned[:100] or "course"


__all__ = [
    "_atomic_write",
    "read_json",
    "read_text",
    "safe_filename",
    "write_bytes",
    "write_json",
    "write_model",
    "write_text",
]
