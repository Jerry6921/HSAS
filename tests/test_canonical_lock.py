"""Canonical ``information.json`` writes must be serialized across processes."""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

import pytest

from hsas.core.services import records as records_module
from hsas.core.services.records import CourseRecordService
from hsas.infrastructure.storage import canonical_information_lock
from hsas.infrastructure.storage.locking import CANONICAL_INFORMATION_LOCK

_COURSE_PAYLOAD = {
    "confirmed": True,
    "course": {
        "course_id": "DEMO1001-2026-S1",
        "code": "DEMO1001",
        "title": "Demo Course",
        "moodle_course_id": "12345",
    },
}


def test_lock_creates_dedicated_lock_file(tmp_path: Path) -> None:
    with canonical_information_lock(tmp_path):
        assert (tmp_path / CANONICAL_INFORMATION_LOCK).is_file()
        # The data file is replaced by os.replace, so it must never be the lock.
        assert not (tmp_path / "information.json").exists()


def test_second_writer_blocks_while_lock_held(tmp_path: Path) -> None:
    with canonical_information_lock(tmp_path):
        descriptor = os.open(tmp_path / CANONICAL_INFORMATION_LOCK, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)


def test_lock_is_cross_process(tmp_path: Path) -> None:
    lock_path = tmp_path / CANONICAL_INFORMATION_LOCK
    probe = (
        "import fcntl, os, sys\n"
        "fd = os.open(sys.argv[1], os.O_RDWR)\n"
        "try:\n"
        "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "except BlockingIOError:\n"
        "    sys.exit(7)\n"
        "sys.exit(0)\n"
    )
    with canonical_information_lock(tmp_path):
        result = subprocess.run(
            [sys.executable, "-c", probe, str(lock_path)], timeout=30
        )
        assert result.returncode == 7


def test_add_course_takes_canonical_lock(tmp_path: Path, monkeypatch) -> None:
    entered: list[Path] = []

    @contextmanager
    def spy(resources_dir: Path):
        entered.append(resources_dir)
        yield

    monkeypatch.setattr(records_module, "canonical_information_lock", spy)
    service = CourseRecordService(resources_dir=tmp_path, mutation_lock=Lock())

    created = service.add_course(dict(_COURSE_PAYLOAD))

    assert created["created"] is True
    assert entered == [tmp_path]
