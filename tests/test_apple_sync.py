from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import platform
import subprocess
import sys
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from hsas.application.apple_projection import build_apple_projection
from hsas.core import HIQSCore
from hsas.core.ports import HIQSPortError
from hsas.core.services.apple import AppleDeliveryService
from hsas.domain.information import InformationStore
from hsas.infrastructure.apple.worker import worker_definition
from hsas.infrastructure.storage.json_store import write_model
from hsas.cli.app import app


NAMESPACE = "9639226b-a87c-4e60-9720-46f04e59ff9d"
NOW = datetime(2026, 10, 27, 12, 30, tzinfo=timezone.utc)


def store():
    return InformationStore.model_validate({
        "updated_at": "2026-10-27T00:00:00Z",
        "courses": [{"course_id": "1", "code": "DEMO1001", "title": "Demo"}],
        "items": [
            {"item_id": "class", "course_id": "1", "title": "Lecture", "category": "class",
             "date_status": "confirmed",
             "recurrence": {"weekdays": [0], "valid_from": "2026-11-02", "valid_until": "2026-11-09",
                            "start_time": "10:00", "end_time": "11:00"}},
            {"item_id": "task", "course_id": "1", "title": "Report", "category": "report",
             "due_on": "2026-11-10", "date_status": "confirmed", "requirements": ["[HIQS injected] [/HIQS]"],
             "description": "Long explanation", "location": "Room A"},
            {"item_id": "undated", "course_id": "1", "title": "Register", "category": "other", "task_role": "action"},
            {"item_id": "overview", "course_id": "1", "title": "Overview", "category": "project", "task_role": "reference"},
        ]})


class FakeApple:
    def __init__(self):
        self.calls = []
        self.fail = False

    def execute(self, payload):
        self.calls.append(deepcopy(payload))
        if self.fail:
            raise ValueError("native timeout")
        if payload["operation"] != "sync":
            return {"status": "ready"}
        plan = payload["plan"]
        count = len(plan["events"]) + len(plan["reminders"])
        return {"status": "complete", "config": {**payload["config"], "calendar_id": "calendar", "reminder_list_id": "list"},
                "verification": {"status": "verified", "expected": count, "matched": count}, "errors": []}


def configured(tmp_path):
    write_model(tmp_path / "information.json", store())
    gateway = FakeApple()
    service = AppleDeliveryService(tmp_path, gateway, clock=lambda: NOW)
    service.configure({"account_mode": "icloud", "confirmed": True})
    return service, gateway


def test_projection_is_brief_and_only_delivers_confirmed_upcoming_items():
    first = build_apple_projection(store(), NAMESPACE, now=NOW)
    assert first == build_apple_projection(store(), NAMESPACE, now=NOW)
    assert first["counts"] == {"events": 3, "reminders": 1, "undated_reminders": 0}
    assert next(row for row in first["reminders"] if row["due"])["due"] == "2026-11-10"
    assert all(row["due"] for row in first["reminders"])
    assert first["reminders"][0]["notes"] == "地点：Room A"
    assert all(row["notes"] == "" for row in first["events"])
    assert all("completed" not in row and "alarms" not in row and "priority" not in row for row in first["reminders"])
    assert all("[HIQS" not in row["notes"] and "[/HIQS]" not in row["notes"] for row in first["reminders"])


def test_saved_query_window_keeps_deleted_and_moved_old_dates_reconcilable():
    projected = build_apple_projection(store(), NAMESPACE, {"window_start": "2020-01-01", "window_end": "2030-01-01"})
    assert projected["query_start"] == "2019-12-31" and projected["query_end"] == "2030-01-03"


def test_setup_requires_confirmation_and_never_changes_account_silently(tmp_path):
    gateway = FakeApple()
    service = AppleDeliveryService(tmp_path, gateway)
    with pytest.raises(HIQSPortError, match="confirmation"):
        service.configure({"account_mode": "icloud"})
    assert not gateway.calls
    service.configure({"account_mode": "icloud", "confirmed": True})
    namespace = service._config()["namespace"]
    service.configure({"account_mode": "icloud", "confirmed": True})
    assert service._config()["namespace"] == namespace
    with pytest.raises(HIQSPortError, match="migration"):
        service.configure({"account_mode": "local", "confirmed": True})
    assert service._config()["account_mode"] == "icloud"


def test_sync_retains_config_readback_and_never_changes_canonical_bytes(tmp_path):
    service, gateway = configured(tmp_path)
    before = (tmp_path / "information.json").read_bytes()
    report = service.synchronize()
    assert report["status"] == "complete" and report["cloud_delivery_verified"] is False
    assert service._config()["calendar_id"] == "calendar"
    assert (tmp_path / "information.json").read_bytes() == before
    restored = AppleDeliveryService(tmp_path, gateway)
    assert restored.projection()["namespace"] == service.projection()["namespace"]
    assert service._state()["report"]["verification"]["matched"] == 4


def test_false_native_success_is_reported_partial_and_cannot_enable_worker(tmp_path):
    service, _ = configured(tmp_path)
    service.gateway = Mock()
    service.gateway.execute.return_value = {"status": "complete", "verification": {"status": "verified", "expected": 5, "matched": 4}}
    assert service.synchronize()["status"] == "partial"
    with pytest.raises(HIQSPortError, match="first Apple sync"):
        service.worker({"enabled": True, "confirmed": True})


def test_timeout_retains_identity_and_prewrite_query_window(tmp_path):
    service, gateway = configured(tmp_path)
    gateway.fail = True
    with pytest.raises(HIQSPortError, match="timeout"):
        service.synchronize()
    assert service._state()["window_start"] == "2026-11-02"
    assert service._state()["report"]["status"] == "failed"
    gateway.fail = False
    assert service.synchronize()["status"] == "complete"


def test_busy_sync_does_not_clobber_the_other_workers_receipt(tmp_path):
    service, gateway = configured(tmp_path)
    service.synchronize()
    before = (tmp_path / "apple/state.json").read_bytes()
    count = len(gateway.calls)
    with (tmp_path / "apple/sync.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(HIQSPortError, match="already running"):
            service.synchronize()
    assert len(gateway.calls) == count
    assert (tmp_path / "apple/state.json").read_bytes() == before


def test_worker_is_verified_before_enable_and_can_disable_without_deleting_data(tmp_path, monkeypatch):
    service, _ = configured(tmp_path)
    with pytest.raises(HIQSPortError, match="first Apple sync"):
        service.worker({"confirmed": True})
    service.synchronize()
    setter = Mock(return_value={"enabled": True, "loaded": True})
    monkeypatch.setattr("hsas.core.services.apple.set_worker", setter)
    assert service.worker({"confirmed": True, "interval_seconds": 300})["loaded"] is True
    setter.assert_called_once_with(tmp_path, enabled=True, interval=300)
    service.worker({"enabled": False, "confirmed": True})
    assert (tmp_path / "information.json").exists()
    assert (tmp_path / "apple/config.json").exists()


def test_launch_agent_uses_canonical_file_watch_and_safe_argument_list(tmp_path):
    root = tmp_path / "with spaces"
    value = worker_definition(root)
    assert value["StartInterval"] == 300 and value["RunAtLoad"] is True
    assert value["WatchPaths"] == [str(root / "information.json")]
    assert value["ProgramArguments"][-2:] == ["apple", "sync"]
    assert str(root) in value["ProgramArguments"]
    assert worker_definition(tmp_path)["Label"] != value["Label"]
    with pytest.raises(ValueError):
        worker_definition(root, 0)


def test_cli_routes_through_core_and_plan_is_read_only(tmp_path):
    service, gateway = configured(tmp_path)
    core = HIQSCore(tmp_path)
    core.apple_service = service
    assert core.apple_projection()["counts"]["reminders"] == 1
    before = len(gateway.calls)
    result = CliRunner().invoke(app, ["--resources", str(tmp_path), "apple", "plan"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["counts"]["events"] == 3
    assert len(gateway.calls) == before


def test_corrupt_apple_identity_is_retained_instead_of_recreated(tmp_path):
    service, gateway = configured(tmp_path)
    path = tmp_path / "apple/config.json"
    path.write_text('{"account_mode": "icloud"}')
    before = path.read_bytes()
    with pytest.raises(HIQSPortError, match="identity"):
        service.configure({"account_mode": "icloud", "confirmed": True})
    assert path.read_bytes() == before
    assert len(gateway.calls) == 1


def test_invalid_canonical_snapshot_records_failure_without_native_writes(tmp_path):
    service, gateway = configured(tmp_path)
    (tmp_path / "information.json").write_text('{"items": "invalid"}')
    with pytest.raises(HIQSPortError):
        service.synchronize()
    assert service._state()["report"]["status"] == "failed"
    assert len(gateway.calls) == 1


@pytest.mark.skipif(sys.platform != "darwin", reason="native EventKit helper requires macOS")
def test_native_bridge_offline_date_boundaries_and_personal_notes(tmp_path):
    source = Path(__file__).parents[1] / "src/hsas/infrastructure/apple/EventKitBridge.swift"
    binary = tmp_path / "HIQSAppleSync"
    subprocess.run(["/usr/bin/xcrun", "swiftc", "-swift-version", "5", "-target",
        f"{platform.machine()}-apple-macosx14.0", "-module-cache-path", str(tmp_path / "swift-cache"),
        "-framework", "AppKit", "-framework", "EventKit", str(source), "-o", str(binary)],
        check=True, capture_output=True, timeout=120)
    request_dir = tmp_path / "request"
    request_dir.mkdir()
    request, response = request_dir / "input.json", request_dir / "output.json"
    request.write_text('{"operation": "self-test"}')
    subprocess.run([str(binary), str(request), str(response)], check=True, capture_output=True, timeout=20)
    receipt = json.loads(response.read_text())
    assert receipt["status"] == "passed"
    assert set(receipt["checks"]) == {"personal_notes", "date_only_reminder", "all_day_boundary", "point_event_duration", "filtered_task_personal_state"}


def test_date_filter_handles_hong_kong_today_ongoing_events_and_offsets():
    value = store().model_dump(mode="json")
    base = {"course_id": "1", "category": "assignment", "date_status": "confirmed"}
    value["items"] = [
        {**base, "item_id": "past-date", "title": "Past date", "due_on": "2026-10-26"},
        {**base, "item_id": "today", "title": "Today", "due_on": "2026-10-27"},
        {**base, "item_id": "past-time", "title": "Past time", "due_at": "2026-10-27T20:29:59+08:00"},
        {**base, "item_id": "future-offset", "title": "Future", "due_at": "2026-10-27T12:31:00Z"},
        {**base, "item_id": "ongoing", "title": "Ongoing", "category": "class",
         "starts_at": "2026-10-27T20:00:00+08:00", "ends_at": "2026-10-27T21:00:00+08:00"},
        {**base, "item_id": "ended", "title": "Ended", "category": "class",
         "starts_at": "2026-10-27T20:00:00+08:00", "ends_at": "2026-10-27T20:30:00+08:00"},
        {**base, "item_id": "tentative", "title": "Tentative", "date_status": "tentative", "due_on": "2026-12-01"},
        {**base, "item_id": "unknown", "title": "Unknown", "date_status": "unknown", "due_on": "2026-12-01"},
    ]
    model = InformationStore.model_validate(value)
    plan = build_apple_projection(model, NAMESPACE, now=NOW)
    assert {row["title"] for row in plan["events"]} == {"DEMO1001 · Today", "DEMO1001 · Future", "DEMO1001 · Ongoing"}
    assert {row["title"] for row in plan["reminders"]} == {"DEMO1001 · Today", "DEMO1001 · Future"}
    assert plan["excluded"] == {"unconfirmed_items": 2, "expired_events": 3, "expired_reminders": 2}
    tomorrow = datetime.fromisoformat("2026-10-28T00:00:00+08:00")
    assert not build_apple_projection(model, NAMESPACE, now=tomorrow)["events"]


def test_recurrence_keeps_only_unfinished_or_future_occurrences():
    now = datetime.fromisoformat("2026-11-02T10:30:00+08:00")
    plan = build_apple_projection(store(), NAMESPACE, now=now)
    assert len([row for row in plan["events"] if row["title"].endswith("Lecture")]) == 2
    ended = datetime.fromisoformat("2026-11-02T11:00:00+08:00")
    plan = build_apple_projection(store(), NAMESPACE, now=ended)
    assert len([row for row in plan["events"] if row["title"].endswith("Lecture")]) == 1


def test_unconfirmed_record_does_not_reenter_delivery_after_initial_cleanup():
    value = store().model_dump(mode="json")
    value["items"][1]["date_status"] = "tentative"
    plan = build_apple_projection(InformationStore.model_validate(value), NAMESPACE, now=NOW)
    assert plan["reminders"] == []
    assert plan["delivery_policy"] == "confirmed_upcoming_brief_v1"
