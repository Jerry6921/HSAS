from copy import deepcopy
import json
import pytest

from hsas.application.notion_controls import controls_snapshot
from hsas.core.services.notion_controls import NotionControlsService
from hsas.infrastructure.storage.json_store import write_json
from hsas.infrastructure.notion.worker import worker_lock
from hsas.infrastructure.notion.config import save_config


def test_progress_is_a_real_stage_ratio_and_unknown_totals_stay_unknown():
    packet = controls_snapshot({"state": "running", "stage": "moodle", "completed": 2,
        "total": 5, "job_id": "job"}, {"pending_total": 4, "agent_prompt": "Read verified sources"}, connected=True)
    assert packet["阶段进度"] == 0.4
    assert packet["状态"] == "运行中"
    assert "sync_notion" in packet["AI 整理提示词"]
    unknown = controls_snapshot({"state": "running", "stage": "starting", "total": 0}, {}, connected=True)
    assert unknown["阶段进度"] is None
    done = controls_snapshot({"state": "completed"}, {"pending_total": 4}, connected=True)
    assert done["状态"] == "待 AI 整理"
    disconnected = controls_snapshot({"state": "idle"}, {}, connected=False)
    assert disconnected["状态"] == "等待连接"


class FakeControls:
    def __init__(self, rows):
        self.data = rows
        self.published = []

    def rows(self):
        return deepcopy(self.data)

    def update(self, page_id, values):
        next(r for r in self.data if r["id"] == page_id).update(values)

    def publish(self, page_id, values, **kwargs):
        self.published.append((page_id, values))
        self.update(page_id, values)


def service(tmp_path, rows):
    for row in rows:
        if row.get("角色") == "当前状态":
            row.setdefault("名称", "HIQS 同步状态")
    gateway = FakeControls(rows)
    job = {"state": "idle", "job_id": None, "total": 0, "completed": 0}
    calls = []
    def start(payload):
        calls.append(payload)
        job.update(state="running", job_id="new-job", total=5, completed=1)
        return dict(job)
    def cancel(payload):
        job.update(state="cancelled")
        return dict(job)
    result = NotionControlsService(tmp_path, lambda: dict(job),
        lambda: {"review_closure": {"pending_total": 2, "agent_prompt": "Source prompt"}},
        start, start, cancel, adapter_factory=lambda _: gateway)
    return result, job, calls, gateway


def test_button_requests_dispatch_once_and_updates_do_not_restart_collection(tmp_path):
    svc, job, calls, gateway = service(tmp_path, [
        {"id": "status", "角色": "当前状态"},
        {"id": "request", "角色": "请求", "状态": "排队", "操作": "同步课程", "created_time": "2026-10-15"},
        {"id": "ignored", "角色": "请求", "状态": "排队", "操作": "arbitrary shell command"}])
    svc.tick()
    svc.tick()
    assert calls == [{"confirmed": True}]
    assert next(r for r in gateway.data if r["id"] == "request")["阶段进度"] == 0.2
    job.update(state="completed", completed=5)
    svc.tick()
    assert next(r for r in gateway.data if r["id"] == "request")["状态"] == "待 AI 整理"
    assert not json.loads((tmp_path / "notion/controls-state.json").read_text())


def test_restart_does_not_replay_an_ambiguous_claim(tmp_path):
    write_json(tmp_path / "notion/controls-state.json", {
        "active_request_id": "request", "dispatch": "claiming"})
    svc, _, calls, gateway = service(tmp_path, [
        {"id": "status", "角色": "当前状态"},
        {"id": "request", "角色": "请求", "状态": "排队", "操作": "同步课程"}])
    svc.tick()
    assert calls == []
    assert next(r for r in gateway.data if r["id"] == "request")["状态"] == "失败"


def test_cancel_request_uses_existing_core_cancellation(tmp_path):
    svc, job, calls, gateway = service(tmp_path, [
        {"id": "status", "角色": "当前状态"},
        {"id": "request", "角色": "请求", "状态": "排队", "操作": "同步课程"}])
    svc.tick()
    next(r for r in gateway.data if r["id"] == "request")["取消请求"] = True
    svc.tick()
    assert job["state"] == "cancelled"
    assert len(calls) == 1


def test_cancelled_queued_request_never_starts_collection_and_blank_drafts_are_preserved(tmp_path):
    svc, _, calls, gateway = service(tmp_path, [
        {"id": "status", "角色": "当前状态"},
        {"id": "draft", "角色": "当前状态", "名称": ""},
        {"id": "request", "角色": "请求", "状态": "排队", "操作": "同步课程", "取消请求": True}])
    svc.tick()
    assert calls == []
    assert next(r for r in gateway.data if r["id"] == "request")["状态"] == "已取消"
    assert next(r for r in gateway.data if r["id"] == "draft")["名称"] == ""


def test_only_one_worker_can_own_the_source_controller_and_lock_releases(tmp_path):
    with worker_lock(tmp_path):
        with pytest.raises(ValueError, match="already running"):
            with worker_lock(tmp_path):
                raise AssertionError("second worker acquired lock")
    with worker_lock(tmp_path):
        pass


def test_hourly_collection_uses_core_and_manual_requests_reset_the_timer(tmp_path):
    save_config(tmp_path, {"collect_interval_seconds": 3600})
    svc, job, calls, gateway = service(tmp_path, [{"id": "status", "角色": "当前状态"}])
    clock = [10000.0]
    svc.clock = lambda: clock[0]
    svc.tick(allow_start=False)  # Publishing originals holds the source-start barrier.
    assert calls == []
    svc.tick()
    assert len(calls) == 1
    job.update(state="completed")
    clock[0] += 3599
    svc.tick()
    assert len(calls) == 1
    gateway.data.append({"id": "manual", "角色": "请求", "状态": "排队", "操作": "同步课程"})
    svc.tick()
    assert len(calls) == 2
    job.update(state="completed")
    svc.tick()
    clock[0] += 1
    svc.tick()
    assert len(calls) == 2
    clock[0] += 3600
    svc.tick()
    assert len(calls) == 3
    assert all(p == {"confirmed": True} for p in calls)


def test_damaged_timer_defers_automatic_collection_and_status_row_cancels_it(tmp_path):
    save_config(tmp_path, {"collect_interval_seconds": 3600})
    svc, job, calls, gateway = service(tmp_path, [{"id": "status", "角色": "当前状态"}])
    path = tmp_path / "notion/controls-schedule.json"
    path.write_text("broken JSON")
    clock = [10000.0]
    svc.clock = lambda: clock[0]
    svc.tick()
    assert calls == []
    clock[0] += 3600
    svc.tick()
    gateway.data[0]["取消请求"] = True
    svc.tick()
    assert job["state"] == "cancelled"
    assert gateway.data[0]["取消请求"] is False
