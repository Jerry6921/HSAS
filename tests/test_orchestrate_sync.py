from threading import Event

import pytest

from hsas.core import HIQSPortError
from hsas.core.orchestrate_sync import CourseSyncController


def test_sync_controller_starts_and_exposes_job() -> None:
    release = Event()
    started = Event()

    def target(_job_id: str, retry_tasks: list[dict[str, object]] | None) -> None:
        assert retry_tasks is None
        started.set()
        release.wait(timeout=1)

    controller = CourseSyncController()
    job = controller.start(target)

    assert started.wait(timeout=1)
    assert job["state"] == "running"
    assert controller.snapshot(lambda: None)["job_id"] == job["job_id"]
    with pytest.raises(HIQSPortError, match="正在进行"):
        controller.start(target)
    release.set()
    controller.thread.join(timeout=1)  # type: ignore[union-attr]


def test_sync_controller_cancel_and_persisted_idle_result() -> None:
    controller = CourseSyncController()
    assert controller.snapshot(lambda: {"retry_tasks": [{"source": "moodle"}]})[
        "result"
    ] == {"retry_tasks": [{"source": "moodle"}]}

    with pytest.raises(HIQSPortError, match="没有正在运行"):
        controller.cancel()
