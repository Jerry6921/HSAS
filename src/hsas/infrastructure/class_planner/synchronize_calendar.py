"""Persist privacy-filtered snapshots from the HKU Class Planner SPA."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from hsas.application.ports.define_gateways import (
    ClassPlannerSessionResult,
    ClassPlannerSyncResult,
)
from hsas.infrastructure.storage.persist_data import read_json, write_json

from .fetch_calendar import ClassPlannerAuthenticationError, capture_calendar_response


SENSITIVE_KEYS = {
    "access_token",
    "accesstoken",
    "authorization",
    "email",
    "id_token",
    "idtoken",
    "refresh_token",
    "refreshtoken",
    "token",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if str(key).casefold() not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"Class Planner field {key!r} must be a list")
    return [item for item in value if isinstance(item, dict)]


def _course_key(row: dict[str, Any]) -> str:
    return str(
        row.get("id")
        or "-".join(
            str(row.get(key) or "")
            for key in ("STRM", "CRSE_ID", "CLASS_NBR")
        )
    ).strip("-")


def _course_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    patterns_by_course: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    patterns_by_catalog: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for pattern in _rows(payload, "patterns"):
        identity = (
            str(pattern.get("STRM") or pattern.get("strm") or ""),
            str(pattern.get("CRSE_ID") or pattern.get("crse_id") or ""),
            str(pattern.get("CLASS_NBR") or pattern.get("class_nbr") or ""),
        )
        patterns_by_course.setdefault(identity, []).append(pattern)
        patterns_by_catalog.setdefault(identity[:2], []).append(pattern)

    result: dict[str, dict[str, Any]] = {}
    for row in _rows(payload, "mainTable"):
        key = _course_key(row)
        if not key:
            continue
        identity = (
            str(row.get("STRM") or row.get("strm") or ""),
            str(row.get("CRSE_ID") or row.get("crse_id") or ""),
            str(row.get("CLASS_NBR") or row.get("class_nbr") or ""),
        )
        result[key] = {
            "course": row,
            "patterns": sorted(
                patterns_by_course.get(identity)
                or patterns_by_catalog.get(identity[:2], []),
                key=lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False),
            ),
        }
    return result


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    courses = _rows(payload, "mainTable")
    patterns = _rows(payload, "patterns")
    terms = sorted(
        {
            str(row.get("STRM") or row.get("strm") or "").strip()
            for row in courses + patterns
            if str(row.get("STRM") or row.get("strm") or "").strip()
        }
    )
    return {
        "course_count": len(courses),
        "meeting_count": len(patterns),
        "term_ids": terms,
    }


def _diff(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if previous is None:
        current_ids = sorted(_course_map(current))
        return {"changed": True, "added": current_ids, "modified": [], "removed": []}
    old = _course_map(previous)
    new = _course_map(current)
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    modified = sorted(
        key
        for key in set(old) & set(new)
        if json.dumps(old[key], sort_keys=True, ensure_ascii=False)
        != json.dumps(new[key], sort_keys=True, ensure_ascii=False)
    )
    return {
        "changed": bool(added or modified or removed),
        "added": added,
        "modified": modified,
        "removed": removed,
    }


def class_planner_status(resources_dir: Path) -> dict[str, Any]:
    session = _read_session_status(resources_dir)
    path = resources_dir / "class-planner" / "latest.json"
    if not path.is_file():
        return {
            "available": False,
            "synced_at": None,
            "course_count": 0,
            "meeting_count": 0,
            "term_ids": [],
            "changes": {"changed": False, "added": [], "modified": [], "removed": []},
            **session,
        }
    envelope = read_json(path)
    if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
        raise ValueError("Class Planner latest.json has an invalid shape")
    summary = _summary(envelope["payload"])
    return {
        "available": True,
        "synced_at": envelope.get("synced_at"),
        **summary,
        "changes": envelope.get("changes") or {},
        "source": "HKU Class Planner",
        **session,
    }


def _read_session_status(resources_dir: Path) -> dict[str, Any]:
    path = resources_dir / "class-planner" / "session.json"
    if not path.is_file():
        return {"login_status": "login_required", "login_checked_at": None}
    value = read_json(path)
    if not isinstance(value, dict):
        return {"login_status": "unknown", "login_checked_at": None}
    return {
        "login_status": value.get("status", "unknown"),
        "login_checked_at": value.get("checked_at"),
    }


def _write_session_status(resources_dir: Path, status: str) -> None:
    write_json(
        resources_dir / "class-planner" / "session.json",
        {
            "status": status,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        },
    ).chmod(0o600)


class ClassPlannerBrowserGateway:
    def __init__(self, resources_dir: Path) -> None:
        self.resources_dir = resources_dir.expanduser().resolve()
        self.profile_dir = self.resources_dir.parent / "class-planner-browser-profile"

    def login_until_ready(
        self, *, timeout_seconds: int = 300
    ) -> ClassPlannerSessionResult:
        try:
            payload = asyncio.run(
                capture_calendar_response(
                    self.profile_dir,
                    headless=False,
                    timeout_seconds=timeout_seconds,
                )
            )
        except Exception:
            _write_session_status(self.resources_dir, "login_required")
            raise
        summary = _summary(payload)
        _write_session_status(self.resources_dir, "logged_in")
        return ClassPlannerSessionResult(
            status="logged_in",
            checked_at=datetime.now(timezone.utc).isoformat(),
            course_count=summary["course_count"],
            term_ids=tuple(summary["term_ids"]),
        )

    def sync(self, *, timeout_seconds: int = 90) -> ClassPlannerSyncResult:
        try:
            payload = _sanitize(
                asyncio.run(
                    capture_calendar_response(
                        self.profile_dir,
                        headless=True,
                        timeout_seconds=timeout_seconds,
                    )
                )
            )
        except ClassPlannerAuthenticationError:
            _write_session_status(self.resources_dir, "expired")
            raise
        if not isinstance(payload, dict):
            raise ValueError("Class Planner payload has an invalid shape")
        summary = _summary(payload)
        target = self.resources_dir / "class-planner" / "latest.json"
        previous_payload: dict[str, Any] | None = None
        if target.is_file():
            previous = read_json(target)
            if isinstance(previous, dict) and isinstance(previous.get("payload"), dict):
                previous_payload = previous["payload"]
        changes = _diff(previous_payload, payload)
        synced_at = datetime.now(timezone.utc).isoformat()
        _write_session_status(self.resources_dir, "logged_in")
        envelope = {
            "schema_version": "1.0",
            "source": "HKU Class Planner",
            "source_url": "https://class-planner.hku.hk/api/calendar",
            "synced_at": synced_at,
            "summary": summary,
            "changes": changes,
            "payload": payload,
        }
        write_json(target, envelope).chmod(0o600)
        if changes["changed"]:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            write_json(target.parent / "history" / f"{stamp}.json", envelope).chmod(0o600)
        return ClassPlannerSyncResult(
            status="synced",
            synced_at=synced_at,
            course_count=summary["course_count"],
            meeting_count=summary["meeting_count"],
            term_ids=tuple(summary["term_ids"]),
            changed=changes["changed"],
            added_course_ids=tuple(changes["added"]),
            modified_course_ids=tuple(changes["modified"]),
            removed_course_ids=tuple(changes["removed"]),
            output_path=target,
        )
