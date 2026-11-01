"""sync-report.json is shared by concurrently synced courses: no entry may be lost."""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from hsas.infrastructure.moodle.sync_store import record_sync_operation
from hsas.infrastructure.storage.json_store import read_json
from hsas.infrastructure.storage.locking import exclusive_file_lock

_LOCK = Path(".transactions") / "sync-report.lock"


def _record(resources: Path, course_id: str) -> Path:
    return record_sync_operation(
        resources,
        scope="single",
        discovered_course_count=1,
        course_results=[
            {
                "course_id": course_id,
                "course": course_id,
                "succeeded": True,
                "change_count": 0,
                "error": "",
            }
        ],
    )


def test_second_writer_blocks_while_report_lock_is_held(tmp_path: Path) -> None:
    with exclusive_file_lock(tmp_path / _LOCK):
        descriptor = os.open(tmp_path / _LOCK, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(descriptor)


def test_report_lock_is_cross_process(tmp_path: Path) -> None:
    probe = (
        "import fcntl, os, sys\n"
        "fd = os.open(sys.argv[1], os.O_RDWR)\n"
        "try:\n"
        "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "except BlockingIOError:\n"
        "    sys.exit(7)\n"
        "sys.exit(0)\n"
    )
    with exclusive_file_lock(tmp_path / _LOCK):
        result = subprocess.run(
            [sys.executable, "-c", probe, str(tmp_path / _LOCK)], timeout=30
        )
        assert result.returncode == 7


def test_concurrent_course_syncs_keep_every_entry(tmp_path: Path) -> None:
    course_ids = [f"course-{index}" for index in range(8)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda course_id: _record(tmp_path, course_id), course_ids))

    report = read_json(tmp_path / "sync-report.json")
    assert set(report["courses"]) == set(course_ids)
