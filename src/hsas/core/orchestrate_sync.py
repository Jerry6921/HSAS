"""Own background synchronization job lifecycle independently of HIQS use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from typing import Any, Callable
from uuid import uuid4

from hsas.core.define_port import HIQSPortError


SyncTarget = Callable[[str, list[dict[str, Any]] | None], None]


def _idle_job() -> dict[str, Any]:
    return {
        "job_id": None,
        "state": "idle",
        "stage": None,
        "detail": None,
        "completed": 0,
        "total": 0,
        "cancel_requested": False,
        "result": None,
        "error": None,
        "cards": [],
        "phase_summaries": {},
    }


@dataclass(slots=True)
class CourseSyncController:
    """Start, expose and cancel one background synchronization job at a time."""

    lock: Lock = field(default_factory=Lock, repr=False)
    cancel_event: Event = field(default_factory=Event, repr=False)
    thread: Thread | None = field(default=None, repr=False)
    job: dict[str, Any] = field(default_factory=_idle_job, repr=False)

    def start(
        self,
        target: SyncTarget,
        *,
        retry_tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                raise HIQSPortError("已有课程同步工作流正在进行。")
            job_id = uuid4().hex
            self.cancel_event = Event()
            is_retry = retry_tasks is not None
            task_count = len(retry_tasks or [])
            self.job = {
                **_idle_job(),
                "job_id": job_id,
                "state": "running",
                "stage": "starting",
                "detail": (
                    f"正在准备重试 {task_count} 个失败项目"
                    if is_retry
                    else "正在启动课程同步工作流"
                ),
                "total": task_count,
                "result": {"retry_tasks": retry_tasks} if is_retry else None,
            }
            self.thread = Thread(
                target=target,
                args=(job_id, retry_tasks),
                name=f"hiqs-{'retry' if is_retry else 'sync'}-{job_id[:8]}",
                daemon=True,
            )
            self.thread.start()
            return dict(self.job)

    def snapshot(
        self,
        persisted_result: Callable[[], dict[str, Any] | None],
    ) -> dict[str, Any]:
        with self.lock:
            value = dict(self.job)
            if value.get("state") == "idle":
                result = persisted_result()
                if result:
                    value["result"] = result
            return value

    def cancel(self) -> dict[str, Any]:
        with self.lock:
            if self.job.get("state") != "running":
                raise HIQSPortError("当前没有正在运行的课程同步工作流。")
            self.cancel_event.set()
            self.job["cancel_requested"] = True
            self.job["detail"] = "正在取消"
            return dict(self.job)


__all__ = ["CourseSyncController"]
