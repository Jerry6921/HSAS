"""Persist review batches and checkpoints for HKU SIS course pages."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from hsas.infrastructure.storage.persist_data import read_json, write_json


class SisCourseInfoReviewError(ValueError):
    """A safe HKU SIS course-information review queue failure."""


def collect_sis_course_info_changes(resources_dir: Path) -> dict[str, Any]:
    root = resources_dir / "sis-course-info"
    checkpoint = _read_checkpoint(root)
    acknowledged = checkpoint.get("acknowledged_through")
    snapshots = _history_snapshots(root)
    candidates = [
        value
        for value in snapshots
        if isinstance(value.get("synced_at"), str)
        and (acknowledged is None or value["synced_at"] > acknowledged)
        and value.get("changes")
    ]
    latest_by_course: dict[str, dict[str, Any]] = {}
    for snapshot in candidates:
        for change in snapshot.get("changes", []):
            if not isinstance(change, dict) or not change.get("course_code"):
                continue
            latest_by_course[str(change["course_code"])] = {
                "synced_at": snapshot["synced_at"],
                **change,
            }
    changes = [latest_by_course[key] for key in sorted(latest_by_course)]
    through = candidates[-1]["synced_at"] if candidates else acknowledged
    identity = {
        "acknowledged_through": acknowledged,
        "acknowledge_through": through,
        "changes": changes,
    }
    batch_id = sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": "1.0",
        "source": "HKU SIS Course Information",
        "authority": "highest",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": batch_id,
        "acknowledged_through": acknowledged,
        "acknowledge_through": through,
        "pending_snapshot_count": len(candidates),
        "pending_change_count": len(changes),
        "changes": changes,
    }


def validate_sis_course_info_batch(resources_dir: Path, batch: dict[str, Any]) -> None:
    current = collect_sis_course_info_changes(resources_dir)
    if batch.get("batch_id") != current["batch_id"]:
        raise SisCourseInfoReviewError(
            "HKU SIS course-information review batch is stale; export it again"
        )
    if batch.get("acknowledge_through") != current["acknowledge_through"]:
        raise SisCourseInfoReviewError("HKU SIS review boundary does not match")


def acknowledge_sis_course_info_changes(
    resources_dir: Path,
    batch: dict[str, Any],
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise SisCourseInfoReviewError("confirmation is required")
    validate_sis_course_info_batch(resources_dir, batch)
    through = batch.get("acknowledge_through")
    if not through:
        raise SisCourseInfoReviewError("there are no HKU SIS changes to acknowledge")
    checkpoint = {
        "schema_version": "1.0",
        "acknowledged_through": through,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": batch["batch_id"],
    }
    write_json(root := resources_dir / "sis-course-info" / "review-checkpoint.json", checkpoint)
    root.chmod(0o600)
    return checkpoint


def _read_checkpoint(root: Path) -> dict[str, Any]:
    path = root / "review-checkpoint.json"
    if not path.is_file():
        return {}
    value = read_json(path)
    if not isinstance(value, dict):
        raise SisCourseInfoReviewError("HKU SIS checkpoint has an invalid shape")
    return value


def _history_snapshots(root: Path) -> list[dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "history").glob("*.json")):
        value = read_json(path)
        if isinstance(value, dict) and isinstance(value.get("synced_at"), str):
            values[value["synced_at"]] = value
    latest = root / "latest.json"
    if latest.is_file():
        value = read_json(latest)
        if isinstance(value, dict) and isinstance(value.get("synced_at"), str):
            values[value["synced_at"]] = value
    return [values[key] for key in sorted(values)]
