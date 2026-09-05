"""Filesystem implementation of the information repository."""

from __future__ import annotations

from pathlib import Path

from hsas.domain.information import InformationStore
from hsas.domain.courses import ArchiveIndex
from hsas.domain.courses.define_change_queue import ChangeCheckpoint
from hsas.domain.courses.detect_changes import CourseChangeSet
from hsas.infrastructure.storage.persist_data import read_json, write_model


LEGACY_CHANGE_KINDS = {"assessment", "weight"}


class JsonInformationRepository:
    """Filesystem adapter for the AI-authored information database."""

    def exists(self, path: Path) -> bool:
        return path.is_file()

    def load(self, path: Path) -> InformationStore:
        return InformationStore.model_validate(read_json(path))

    def save(self, path: Path, store: InformationStore) -> None:
        write_model(path, store)


class JsonChangeQueueRepository:
    """Filesystem adapter for pending Moodle changes and AI checkpoints."""

    def load_archives(self, resources_dir: Path) -> list[ArchiveIndex]:
        return [
            ArchiveIndex.from_json(path)
            for path in sorted((resources_dir / "courses").glob("*/course.json"))
        ]

    def load_change_sets(
        self,
        resources_dir: Path,
        course_id: str,
    ) -> list[CourseChangeSet]:
        root = resources_dir / "courses" / course_id / "changes"
        paths = sorted((root / "history").glob("*.json"))
        latest = root / "latest.json"
        if latest.is_file():
            paths.append(latest)
        values: dict[tuple[str, str], CourseChangeSet] = {}
        for path in paths:
            change_set = CourseChangeSet.model_validate(
                _normalize_legacy_change_kinds(read_json(path))
            )
            if not change_set.changed:
                continue
            key = (
                change_set.change_set_id or "",
                change_set.current_collected_at.isoformat(),
            )
            values[key] = change_set
        return sorted(values.values(), key=lambda value: value.current_collected_at)

    def load_checkpoint(self, path: Path) -> ChangeCheckpoint:
        if not path.is_file():
            return ChangeCheckpoint()
        return ChangeCheckpoint.model_validate(read_json(path))

    def save_checkpoint(self, path: Path, checkpoint: ChangeCheckpoint) -> None:
        write_model(path, checkpoint)


def _normalize_legacy_change_kinds(payload: object) -> object:
    """Adapt pre-2.0 parser history without rewriting the historical JSON."""
    if not isinstance(payload, dict) or not isinstance(payload.get("changes"), list):
        return payload
    normalized = dict(payload)
    normalized_changes = []
    for raw_change in payload["changes"]:
        if not isinstance(raw_change, dict) or raw_change.get("kind") not in LEGACY_CHANGE_KINDS:
            normalized_changes.append(raw_change)
            continue
        change = dict(raw_change)
        change["kind"] = "activity"
        normalized_changes.append(change)
    normalized["changes"] = normalized_changes
    return normalized
