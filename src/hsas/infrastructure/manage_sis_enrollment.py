"""Build and checkpoint AI review batches for SIS enrolment snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from hsas.infrastructure.storage.persist_data import read_json, write_json


class SisEnrollmentReviewError(ValueError):
    """A safe Student Center enrolment review queue failure."""


def collect_sis_enrollment_changes(resources_dir: Path) -> dict[str, Any]:
    root = resources_dir / "sis-enrollment"
    latest_path = root / "latest.json"
    latest = read_json(latest_path) if latest_path.is_file() else {}
    checkpoint_path = root / "review-checkpoint.json"
    checkpoint = read_json(checkpoint_path) if checkpoint_path.is_file() else {}
    if not isinstance(latest, dict) or not isinstance(checkpoint, dict):
        raise SisEnrollmentReviewError("Student Center review state has an invalid shape")

    current_courses = _courses(latest.get("courses"))
    previous_courses = _courses(checkpoint.get("courses"))
    current_hash = latest.get("content_sha256")
    acknowledged_hash = checkpoint.get("content_sha256")
    changed = bool(current_hash and current_hash != acknowledged_hash)
    current_by_code = {course["course_code"]: course for course in current_courses}
    previous_by_code = {course["course_code"]: course for course in previous_courses}
    changes: list[dict[str, Any]] = []
    if changed:
        for code in sorted(current_by_code.keys() - previous_by_code.keys()):
            changes.append({"kind": "added", "course": current_by_code[code]})
        for code in sorted(previous_by_code.keys() - current_by_code.keys()):
            changes.append({"kind": "removed", "course": previous_by_code[code]})
        for code in sorted(current_by_code.keys() & previous_by_code.keys()):
            if current_by_code[code] != previous_by_code[code]:
                changes.append(
                    {
                        "kind": "modified",
                        "before": previous_by_code[code],
                        "course": current_by_code[code],
                    }
                )
        if not changes:
            changes.append({"kind": "snapshot_updated", "term": latest.get("term")})

    identity = {
        "acknowledged_content_sha256": acknowledged_hash,
        "content_sha256": current_hash,
        "courses": current_courses,
        "changes": changes,
    }
    batch_id = sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": "1.0",
        "source": "HKU SIS Student Center Enrollment Status",
        "authority": "highest",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": batch_id,
        "term": latest.get("term"),
        "observed_at": latest.get("observed_at"),
        "acknowledged_content_sha256": acknowledged_hash,
        "content_sha256": current_hash,
        "pending_change_count": len(changes),
        "courses": current_courses,
        "changes": changes,
    }


def validate_sis_enrollment_batch(resources_dir: Path, batch: dict[str, Any]) -> None:
    current = collect_sis_enrollment_changes(resources_dir)
    if batch.get("batch_id") != current["batch_id"]:
        raise SisEnrollmentReviewError("Student Center review batch is stale; export it again")


def acknowledge_sis_enrollment_changes(
    resources_dir: Path,
    batch: dict[str, Any],
    *,
    confirmed: bool,
) -> dict[str, Any]:
    if not confirmed:
        raise SisEnrollmentReviewError("confirmation is required")
    validate_sis_enrollment_batch(resources_dir, batch)
    content_hash = batch.get("content_sha256")
    if not content_hash:
        raise SisEnrollmentReviewError("Student Center snapshot is unavailable")
    checkpoint = {
        "schema_version": "1.0",
        "content_sha256": content_hash,
        "observed_at": batch.get("observed_at"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": batch["batch_id"],
        "courses": _courses(batch.get("courses")),
    }
    path = resources_dir / "sis-enrollment" / "review-checkpoint.json"
    write_json(path, checkpoint)
    path.chmod(0o600)
    return checkpoint


def _courses(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    courses = []
    for course in value:
        if not isinstance(course, dict) or not course.get("course_code"):
            continue
        courses.append(
            {
                key: str(course.get(key, ""))
                for key in ("course_code", "subject_area", "catalogue_number", "title")
            }
        )
    return sorted(courses, key=lambda course: course["course_code"])
