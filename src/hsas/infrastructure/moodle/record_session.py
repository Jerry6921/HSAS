"""Persist a secret-free summary of the last verified Moodle session."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hsas.infrastructure.storage.persist_data import read_json, write_json


def load_moodle_session_status(resources_dir: Path) -> dict[str, Any]:
    path = resources_dir / "moodle" / "session.json"
    if not path.is_file():
        return {
            "login_status": "login_required",
            "login_checked_at": None,
            "available_course_count": 0,
        }
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return {
            "login_status": "unknown",
            "login_checked_at": None,
            "available_course_count": 0,
        }
    if not isinstance(value, dict):
        return {
            "login_status": "unknown",
            "login_checked_at": None,
            "available_course_count": 0,
        }
    return {
        "login_status": value.get("status", "unknown"),
        "login_checked_at": value.get("checked_at"),
        "available_course_count": value.get("available_course_count", 0),
    }


def record_moodle_session_status(
    resources_dir: Path,
    status: str,
    *,
    available_course_count: int = 0,
) -> None:
    write_json(
        resources_dir / "moodle" / "session.json",
        {
            "status": status,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "available_course_count": available_course_count,
        },
    ).chmod(0o600)
