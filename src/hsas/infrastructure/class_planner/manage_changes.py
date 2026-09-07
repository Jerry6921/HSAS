"""Persist the review queue and checkpoint for Class Planner snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from hsas.infrastructure.storage.persist_data import read_json, write_json
from hsas.infrastructure.class_planner.define_review_fields import meaningful_detail


class ClassPlannerReviewError(ValueError):
    """A safe Class Planner review queue failure."""


def initialize_class_planner_checkpoint(
    resources_dir: Path,
    snapshot: dict[str, Any],
) -> None:
    """Adopt a pre-feature snapshot as the baseline before the next sync."""
    target = resources_dir / "class-planner" / "review-checkpoint.json"
    through = snapshot.get("synced_at")
    if target.is_file() or not isinstance(through, str) or not through:
        return
    write_json(
        target,
        {
            "schema_version": "1.0",
            "acknowledged_through": through,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "batch_id": None,
            "reason": "existing_snapshot_baseline",
        },
    )


def collect_class_planner_changes(resources_dir: Path) -> dict[str, Any]:
    root = resources_dir / "class-planner"
    checkpoint = _read_checkpoint(root)
    acknowledged_through = checkpoint.get("acknowledged_through")
    snapshots = _history_snapshots(root)
    if acknowledged_through is None and snapshots:
        snapshots = snapshots[-1:]
    candidate_snapshots = [
        value
        for value in snapshots
        if value.get("synced_at")
        and (acknowledged_through is None or value["synced_at"] > acknowledged_through)
        and bool((value.get("changes") or {}).get("changed"))
    ]
    changes = []
    pending_snapshot_times: set[str] = set()
    for snapshot in candidate_snapshots:
        diff = snapshot.get("changes") or {}
        details = diff.get("details") or _legacy_details(diff)
        for detail in details:
            normalized = meaningful_detail(detail)
            if normalized is not None:
                changes.append({"synced_at": snapshot["synced_at"], **normalized})
                pending_snapshot_times.add(snapshot["synced_at"])
    through = (
        candidate_snapshots[-1]["synced_at"]
        if candidate_snapshots
        else acknowledged_through
    )
    fingerprint_payload = {
        "acknowledged_through": acknowledged_through,
        "acknowledge_through": through,
        "changes": changes,
    }
    batch_id = sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": batch_id,
        "acknowledged_through": acknowledged_through,
        "acknowledge_through": through,
        "pending_snapshot_count": len(pending_snapshot_times),
        "pending_change_count": len(changes),
        "changes": changes,
    }


def validate_class_planner_batch(resources_dir: Path, batch: dict[str, Any]) -> None:
    current = collect_class_planner_changes(resources_dir)
    if batch.get("batch_id") != current["batch_id"]:
        raise ClassPlannerReviewError(
            "Class Planner review batch is stale; export the current changes again"
        )
    if batch.get("acknowledge_through") != current["acknowledge_through"]:
        raise ClassPlannerReviewError("Class Planner review boundary does not match")


def acknowledge_class_planner_changes(
    resources_dir: Path,
    batch: dict[str, Any],
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise ClassPlannerReviewError("confirmation is required")
    validate_class_planner_batch(resources_dir, batch)
    through = batch.get("acknowledge_through")
    if not through:
        raise ClassPlannerReviewError("there are no Class Planner changes to acknowledge")
    checkpoint = {
        "schema_version": "1.0",
        "acknowledged_through": through,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": batch["batch_id"],
    }
    write_json(resources_dir / "class-planner" / "review-checkpoint.json", checkpoint)
    return checkpoint


def _read_checkpoint(root: Path) -> dict[str, Any]:
    path = root / "review-checkpoint.json"
    if not path.is_file():
        return {}
    value = read_json(path)
    if not isinstance(value, dict):
        raise ClassPlannerReviewError("Class Planner checkpoint has an invalid shape")
    return value


def _history_snapshots(root: Path) -> list[dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "history").glob("*.json")):
        value = read_json(path)
        if isinstance(value, dict) and isinstance(value.get("synced_at"), str):
            values[value["synced_at"]] = value
    latest_path = root / "latest.json"
    if latest_path.is_file():
        latest = read_json(latest_path)
        if isinstance(latest, dict) and isinstance(latest.get("synced_at"), str):
            values[latest["synced_at"]] = latest
    return [values[key] for key in sorted(values)]


def _legacy_details(diff: dict[str, Any]) -> list[dict[str, Any]]:
    details = []
    for action in ("added", "modified", "removed"):
        details.extend(
            {"action": action, "course_key": value, "fields": []}
            for value in diff.get(action, [])
        )
    return details
