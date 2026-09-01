"""Crash-recoverable, course-wide snapshot transactions."""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import shutil
import tempfile
from typing import BinaryIO

from .persist_data import read_json, write_json
from hsas.domain.courses.index_courses import ArchiveIndex


class CourseSnapshotError(RuntimeError):
    """Raised when a course snapshot cannot be prepared or published safely."""


@dataclass(slots=True)
class CourseSnapshotTransaction:
    """Build a complete course outside the live tree and publish it together."""

    resources_dir: Path
    course_id: str
    transaction_root: Path
    staging_resources_dir: Path
    staged_course_dir: Path
    live_course_dir: Path
    _lock_path: Path
    _lock_handle: BinaryIO
    _committed: bool = False

    @classmethod
    def prepare(cls, resources_dir: Path, course_id: str) -> "CourseSnapshotTransaction":
        if not course_id.isdigit():
            raise CourseSnapshotError("course_id must be numeric")
        resources = resources_dir.resolve()
        transactions = resources / ".transactions"
        transactions.mkdir(parents=True, exist_ok=True)
        lock_path = transactions / f"course-{course_id}.lock"
        lock_handle = lock_path.open("a+b")
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock_handle.close()
            raise CourseSnapshotError(
                f"course {course_id} already has a synchronization in progress"
            ) from exc

        transaction_root: Path | None = None
        try:
            _recover_interrupted_publish(resources, course_id)
            transaction_root = Path(
                tempfile.mkdtemp(prefix=f"course-{course_id}-", dir=transactions)
            )
            staging_resources = transaction_root / "resources"
            staged_course = staging_resources / "courses" / course_id
            live_course = resources / "courses" / course_id
            if live_course.is_dir():
                shutil.copytree(live_course, staged_course)
            else:
                staged_course.mkdir(parents=True)
            return cls(
                resources_dir=resources,
                course_id=course_id,
                transaction_root=transaction_root,
                staging_resources_dir=staging_resources,
                staged_course_dir=staged_course,
                live_course_dir=live_course,
                _lock_path=lock_path,
                _lock_handle=lock_handle,
            )
        except Exception:
            if transaction_root is not None:
                _remove_tree(transaction_root, transactions)
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            lock_handle.close()
            raise

    def commit(self) -> Path:
        """Validate and publish the staged directory, restoring the old one on failure."""
        course_json = self.staged_course_dir / "course.json"
        ArchiveIndex.from_json(course_json)
        transactions = self.resources_dir / ".transactions"
        journal = transactions / f"course-{self.course_id}.journal.json"
        backup = self.transaction_root / "previous"
        payload = {
            "schema_version": "1.0",
            "course_id": self.course_id,
            "state": "prepared",
            "transaction_root": str(self.transaction_root),
            "staged_course_dir": str(self.staged_course_dir),
            "live_course_dir": str(self.live_course_dir),
            "backup_dir": str(backup),
        }
        write_json(journal, payload)
        self.live_course_dir.parent.mkdir(parents=True, exist_ok=True)
        old_moved = False
        try:
            if self.live_course_dir.exists():
                os.replace(self.live_course_dir, backup)
                old_moved = True
            payload["state"] = "old_moved"
            write_json(journal, payload)
            os.replace(self.staged_course_dir, self.live_course_dir)
            payload["state"] = "committed"
            write_json(journal, payload)
            self._committed = True
        except Exception as exc:
            if old_moved and backup.exists() and not self.live_course_dir.exists():
                os.replace(backup, self.live_course_dir)
            raise CourseSnapshotError(
                f"course {self.course_id} snapshot publish failed; previous snapshot restored"
            ) from exc
        finally:
            if self._committed:
                _remove_tree(backup, transactions)
                journal.unlink(missing_ok=True)
        return self.live_course_dir / "course.json"

    def close(self) -> None:
        """Discard staging artifacts and release the per-course lock."""
        _remove_tree(self.transaction_root, self.resources_dir / ".transactions")
        if not self._lock_handle.closed:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
            self._lock_handle.close()

    def __enter__(self) -> "CourseSnapshotTransaction":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def _recover_interrupted_publish(resources_dir: Path, course_id: str) -> None:
    transactions = resources_dir / ".transactions"
    journal = transactions / f"course-{course_id}.journal.json"
    if not journal.is_file():
        return
    try:
        payload = read_json(journal)
        root = _validated_child(Path(payload["transaction_root"]), transactions)
        live = _validated_child(Path(payload["live_course_dir"]), resources_dir / "courses")
        backup = _validated_child(Path(payload["backup_dir"]), root)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise CourseSnapshotError(f"invalid recovery journal for course {course_id}") from exc

    if not live.exists() and backup.exists():
        live.parent.mkdir(parents=True, exist_ok=True)
        os.replace(backup, live)
    elif live.exists() and backup.exists():
        try:
            ArchiveIndex.from_json(live / "course.json")
        except Exception as exc:
            raise CourseSnapshotError(
                f"course {course_id} has an invalid live snapshot and a recovery backup"
            ) from exc
        _remove_tree(backup, transactions)
    _remove_tree(root, transactions)
    journal.unlink(missing_ok=True)


def _validated_child(path: Path, parent: Path) -> Path:
    resolved = path.resolve()
    parent_resolved = parent.resolve()
    if resolved == parent_resolved or parent_resolved not in resolved.parents:
        raise ValueError(f"unsafe transaction path: {path}")
    return resolved


def _remove_tree(path: Path, allowed_parent: Path) -> None:
    if not path.exists():
        return
    _validated_child(path, allowed_parent)
    shutil.rmtree(path)
