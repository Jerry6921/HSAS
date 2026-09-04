"""Persistence contract for the canonical information database."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from hsas.domain.information import InformationStore
from hsas.domain.courses import ArchiveIndex
from hsas.domain.courses.define_change_queue import ChangeCheckpoint
from hsas.domain.courses.detect_changes import CourseChangeSet


class InformationRepository(Protocol):
    """Load and atomically persist the canonical information database."""

    def exists(self, path: Path) -> bool: ...

    def load(self, path: Path) -> InformationStore: ...

    def save(self, path: Path, store: InformationStore) -> None: ...


class ChangeQueueRepository(Protocol):
    """Read Moodle snapshots and persist the AI review checkpoint."""

    def load_archives(self, resources_dir: Path) -> list[ArchiveIndex]: ...

    def load_change_sets(
        self,
        resources_dir: Path,
        course_id: str,
    ) -> list[CourseChangeSet]: ...

    def load_checkpoint(self, path: Path) -> ChangeCheckpoint: ...

    def save_checkpoint(self, path: Path, checkpoint: ChangeCheckpoint) -> None: ...
