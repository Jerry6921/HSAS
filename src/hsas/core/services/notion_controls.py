"""Execute explicit Notion requests through existing CORE use cases."""

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
from pathlib import Path
import time
from typing import Any

from hsas.application.notion_controls import controls_snapshot
from hsas.core.ports import HIQSPortError
from hsas.infrastructure.notion.controls import NotionControlsAdapter
from hsas.infrastructure.notion.config import load_config
from hsas.infrastructure.storage.json_store import read_json, write_json


@dataclass(slots=True)
class NotionControlsService:
    resources_dir: Path
    source_status: Callable[[], dict]
    information: Callable[[], dict]
    start: Callable[[dict], dict]
    retry: Callable[[dict], dict]
    cancel: Callable[[dict], dict]
    adapter_factory: Callable[[Path], Any] = field(default=NotionControlsAdapter, repr=False)
    adapter: Any = field(default=None, repr=False)
    clock: Callable[[], float] = field(default=time.time, repr=False)

    def snapshot(self) -> dict:
        config = load_config(self.resources_dir, require_token=False)
        return controls_snapshot(self.source_status(), self.information().get("review_closure", {}),
            connected=bool(config.get("token") and config.get("data_sources", {}).get("controls")))

    def tick(self, *, allow_start: bool = True) -> dict:
        """Claim one explicit button request and publish real stage progress.

        No arbitrary payload, shell command, canonical apply or checkpoint is
        accepted from Notion. The native button records human intent to collect.
        """
        if self.adapter is None:
            self.adapter = self.adapter_factory(self.resources_dir)
        with self._lock():
            state_path = self.resources_dir / "notion" / "controls-state.json"
            state = read_json(state_path) if state_path.exists() else {}
            rows = self.adapter.rows()
            candidates = [r for r in rows if r.get("角色") == "当前状态"
                          and r.get("名称") == "HIQS 同步状态"]
            status_row = candidates[0] if len(candidates) == 1 else None
            if not status_row:
                raise HIQSPortError("Notion controls status row is missing")
            active = next((r for r in rows if r["id"] == state.get("active_request_id")), None)
            job = self.source_status()
            interval = int(load_config(self.resources_dir, require_token=False).get("collect_interval_seconds", 0))
            schedule_path = self.resources_dir / "notion" / "controls-schedule.json"
            now = self.clock()
            try:
                schedule = read_json(schedule_path) if schedule_path.exists() else {}
                last_started = float(schedule.get("last_started_at", 0))
            except (ValueError, OSError, TypeError, AttributeError):
                # A damaged derived timer defers automatic work; it never replays.
                last_started = now
                write_json(schedule_path, {"last_started_at": now})
            automatic_error = False
            if active and job.get("state") == "idle":
                self.adapter.update(active["id"], {"状态": "失败", "详情": "后台已重启，请重试；未重复执行旧请求。"})
                active["状态"] = "失败"
                state = {}
                active = None
                write_json(state_path, state)
            # Only the FIFO request queue can start source collection.
            if active and state.get("job_id") and job.get("job_id") != state["job_id"]:
                self.adapter.update(active["id"], {"状态": "失败", "详情": "后台任务已改变，请重试。"})
                active["状态"] = "失败"
                state = {}
                active = None
                write_json(state_path, state)
            if not active and job.get("state") != "running" and allow_start:
                for row in rows:
                    if row.get("角色") == "请求" and row.get("状态") == "排队" and row.get("取消请求"):
                        self.adapter.update(row["id"], {"状态": "已取消", "详情": "排队时已取消，未启动采集。"})
                        row["状态"] = "已取消"
                pending = sorted([r for r in rows if r.get("角色") == "请求"
                    and r.get("状态") == "排队" and r.get("操作") in {"同步课程", "重试失败"}],
                    key=lambda r: r.get("created_time", ""))
                if pending:
                    active = pending[0]
                    # Save before dispatch. Ambiguous dispatch is never replayed.
                    state = {"active_request_id": active["id"], "dispatch": "claiming"}
                    write_json(state_path, state)
                    self.adapter.update(active["id"], {"状态": "运行中", "阶段": "正在启动"})
                    try:
                        operation = self.retry if active["操作"] == "重试失败" else self.start
                        write_json(schedule_path, {"last_started_at": now})
                        job = operation({"confirmed": True})
                        state["job_id"] = job["job_id"]
                        state["dispatch"] = "started"
                        write_json(state_path, state)
                    except HIQSPortError:
                        self.adapter.update(active["id"], {"状态": "失败", "详情": "无法启动，请检查本机同步状态或登录授权。"})
                        state = {}
                        active = None
                        write_json(state_path, state)
                elif 600 <= interval <= 86400 and now - last_started >= interval:
                    # Timer intent is local configuration. No Notion text can
                    # supply commands, facts or arbitrary collection arguments.
                    write_json(schedule_path, {"last_started_at": now})
                    try:
                        job = self.start({"confirmed": True})
                    except HIQSPortError:
                        automatic_error = True
            if active and active.get("取消请求") and job.get("state") == "running":
                self.cancel({"confirmed": True})
                job = self.source_status()
            if status_row.get("取消请求") and job.get("state") == "running":
                self.cancel({"confirmed": True})
                job = self.source_status()
                self.adapter.update(status_row["id"], {"取消请求": False})
            packet = controls_snapshot(job, self.information().get("review_closure", {}), connected=True)
            if automatic_error:
                packet.update({"状态": "失败", "阶段": "自动采集未启动",
                    "详情": "请检查本机同步状态或登录授权；本周期未重复执行。"})
            self.adapter.publish(status_row["id"], packet, prompt_page=True)
            if active:
                self.adapter.publish(active["id"], packet)
                if job.get("state") in {"completed", "failed", "cancelled"}:
                    state = {}
                    write_json(state_path, state)
            return {"connected": True, "active_request_id": state.get("active_request_id"),
                    "source_running": job.get("state") == "running", "snapshot": packet}

    @contextmanager
    def _lock(self):
        directory = self.resources_dir / "notion"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "controls.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HIQSPortError("Another Notion request consumer is running") from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
