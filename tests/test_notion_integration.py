from copy import deepcopy
from hashlib import sha256
from uuid import uuid4
from zipfile import ZipFile
import json
import plistlib

import pytest

from hsas.application.notion_projection import build_notion_projection as _build_notion_projection, expand_calendar, rich_text
from hsas.domain.information import InformationStore
from hsas.infrastructure.notion.config import load_config, save_config
from hsas.infrastructure.notion.connector import connector_properties
from hsas.infrastructure.notion.export import export_package, plain_property
from hsas.infrastructure.notion.workspace import IDENTITY_PROPERTIES, NotionWorkspaceAdapter
from hsas.infrastructure.notion.client import NotionAPIError
from hsas.infrastructure.notion.worker import worker_plist
from hsas.core import HIQSCore


def build_notion_projection(*args, **kwargs):
    return _build_notion_projection(*args, include_execution=True, **kwargs)


def store():
    return InformationStore.model_validate({"updated_at": "2026-10-09T08:00:00Z",
        "courses": [{"course_id": "1", "code": "DEMO1001", "title": "Demo"}],
        "items": [{"item_id": "task-1", "course_id": "1", "title": "Report",
                   "category": "report", "due_on": "2026-10-20", "date_status": "confirmed"}]})


def test_recurrence_expansion_preserves_exclusions_additions_and_overrides():
    item = {"item_id": "class", "title": "Lecture", "location": "A",
        "recurrence": {"valid_from": "2026-10-05", "valid_until": "2026-10-26",
            "weekdays": [0], "start_time": "10:00:00", "end_time": "11:00:00",
            "excluded_dates": ["2026-10-12"], "additional_dates": ["2026-10-07"],
            "exceptions": [{"date": "2026-10-19", "status": "cancelled"},
                {"date": "2026-10-26", "status": "changed", "start_time": "12:00:00",
                 "end_time": "13:00:00", "title": "Make-up", "location": "B"}]}}
    rows = expand_calendar(item, "Asia/Hong_Kong")
    assert [r["identity"] for r in rows] == ["class:2026-10-05", "class:2026-10-07", "class:2026-10-26"]
    assert rows[-1]["title"] == "Make-up"
    assert rows[-1]["start"] == "2026-10-26T12:00:00+08:00"
    assert rows[-1]["location"] == "B"
    assert expand_calendar({"item_id": "unknown", "title": "Unknown"}, "Asia/Hong_Kong") == []


def test_projection_deduplicates_bytes_and_keeps_exact_source_classifications(tmp_path):
    first, second = tmp_path / "a.pdf", tmp_path / "b.pdf"
    first.write_bytes(b"original")
    second.write_bytes(b"original")
    value = store().model_dump(mode="json")
    value["courses"][0]["material_sections"] = [
        {"title": "Reference copies", "materials": [{"title": "Copy", "relative_path": "b.pdf"}]},
        {"title": "Teacher's slides, week 2", "materials": [{"title": "Original", "relative_path": "a.pdf"}]}]
    projection = build_notion_projection(InformationStore.model_validate(value),
                                         lambda p: (tmp_path / p, "application/pdf"))
    materials = [r for r in projection["records"] if r["kind"] == "materials"]
    assert len(materials) == 1
    assert materials[0]["identity"] == "1:" + sha256(b"original").hexdigest()
    assert materials[0]["file"]["section"] == "Teacher's slides, week 2"
    assert materials[0]["source_paths"] == ["b.pdf", "a.pdf"]
    task = next(r for r in projection["records"] if r["kind"] == "items")
    assert "Personal Status" not in task["properties"]
    assert "Personal Notes" not in task["properties"]


def test_export_keeps_original_bytes_and_native_calendar(tmp_path):
    value = store().model_dump(mode="json")
    value["courses"][0]["material_sections"] = [{"title": "Slides", "materials": [
        {"title": "One", "relative_path": "original.pdf"}]}]
    file = tmp_path / "original.pdf"
    file.write_bytes(b"unaltered PDF bytes")
    projection = build_notion_projection(InformationStore.model_validate(value),
                                         lambda p: (tmp_path / p, "application/pdf"))
    result = export_package(projection, b"BEGIN:VCALENDAR\r\nEND:VCALENDAR", tmp_path / "out")
    assert result["original_files"] == 1
    with ZipFile(tmp_path / "out/HIQS-originals.zip") as archive:
        pdf = next(n for n in archive.namelist() if n.endswith("original.pdf"))
        assert archive.read(pdf) == file.read_bytes()
    assert (tmp_path / "out/calendar.csv").exists()


def test_local_connection_never_exposes_token_and_has_private_permissions(tmp_path, monkeypatch):
    monkeypatch.delenv("HIQS_NOTION_TOKEN", raising=False)
    save_config(tmp_path, {"token": "test-secret", "parent_page_id": uuid4().hex})
    path = tmp_path / "notion/connection.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_config(tmp_path)["token"] == "test-secret"


def test_connector_keeps_json_as_text_and_date_only_as_date():
    row = {"kind": "items", "properties": {"Recurrence": rich_text('{"weekdays":[0]}'),
        "Due": {"date": {"start": "2026-10-20", "end": None}}}}
    props = connector_properties(row, {})
    assert props["Recurrence"].startswith("HIQS data:")
    assert props["date:Due:is_datetime"] == 0


class FakeClient:
    def __init__(self, projection):
        self.schemas = {k: {"properties": {IDENTITY_PROPERTIES[k]: {}}} for k in IDENTITY_PROPERTIES}
        self.data = {k: [] for k in IDENTITY_PROPERTIES}
        self.writes = []
        self.blocks = {}
        self.uploads = 0
        for row in projection["records"]:
            self.schemas[row["kind"]]["properties"].update({k: {} for k in row["properties"]})

    def request(self, method, path, payload=None, **kwargs):
        if method == "GET" and path == "/users/me":
            return {"id": "bot"}
        if method == "GET" and path.startswith("/data_sources/"):
            return self.schemas[path.split("/")[2]]
        self.writes.append((method, path, deepcopy(payload)))
        if path.startswith("/data_sources/"):
            self.schemas[path.split("/")[2]]["properties"].update(payload["properties"])
            return {}
        if method == "POST" and path == "/pages":
            row = {"id": str(uuid4()), "properties": deepcopy(payload["properties"])}
            self.data[payload["parent"]["data_source_id"]].append(row)
            return row
        if path.startswith("/pages/"):
            for rows in self.data.values():
                for row in rows:
                    if row["id"] == path.split("/")[2]:
                        row["properties"].update(deepcopy(payload["properties"]))
                        return row
        if path.endswith("/children"):
            block = {"id": str(uuid4()), **payload["children"][0]}
            self.blocks.setdefault(path.split("/")[2], []).append(block)
            return {"results": [block]}
        raise AssertionError((method, path, payload))

    def rows(self, source):
        return deepcopy(self.data[source])

    def children(self, page):
        return deepcopy(self.blocks.get(page, []))

    def upload(self, path):
        self.uploads += 1
        return str(uuid4())


def test_sync_verifies_and_stays_idempotent_with_notion_minute_precision(tmp_path):
    class MinutePrecisionClient(FakeClient):
        def request(self, method, path, payload=None, **kwargs):
            if payload and "Last Synced" in payload.get("properties", {}):
                payload = deepcopy(payload)
                date = payload["properties"]["Last Synced"]["date"]
                from datetime import datetime

                stamp = datetime.fromisoformat(date["start"])
                date["start"] = stamp.replace(second=0, microsecond=0).isoformat()
            return super().request(method, path, payload, **kwargs)

    value = store().model_copy(update={
        "updated_at": store().updated_at.replace(second=40, microsecond=871917)})
    projection = build_notion_projection(value, lambda _: pytest.fail("unexpected file"))
    client = MinutePrecisionClient(projection)
    config = {"include_execution": True, "parent_page_id": "home", "data_sources": {k: k for k in IDENTITY_PROPERTIES}}
    adapter = NotionWorkspaceAdapter(client, config, tmp_path / "state.json")

    first = adapter.synchronize(projection)
    assert first["verification"]["status"] == "verified"
    assert projection["source_updated_at"] == value.updated_at.isoformat()
    second = adapter.synchronize(projection)
    assert second["verification"]["status"] == "verified"
    assert second["created"] == second["updated"] == 0


def test_sync_is_idempotent_preserves_user_status_and_notes_and_reconciles_removals(tmp_path):
    projection = build_notion_projection(store(), lambda _: pytest.fail("unexpected file"))
    client = FakeClient(projection)
    config = {"include_execution": True, "parent_page_id": "home", "data_sources": {k: k for k in IDENTITY_PROPERTIES}}
    adapter = NotionWorkspaceAdapter(client, config, tmp_path / "state.json")
    first = adapter.synchronize(projection)
    assert first["created"] == 3
    task = client.data["items"][0]
    task["properties"]["Personal Status"] = {"select": {"name": "In review"}}
    task["properties"]["Personal Notes"] = rich_text("My own notes")
    client.data["items"].append({"id": "draft", "properties": {"Item": {"title": []}}})
    client.writes.clear()
    second = adapter.synchronize(projection)
    assert second["created"] == second["updated"] == 0
    assert task["properties"]["Personal Status"]["select"]["name"] == "In review"
    assert plain_property(task["properties"]["Personal Notes"]) == "My own notes"
    assert not any(path == "/pages/draft" for _, path, _ in client.writes)
    removed = deepcopy(projection)
    removed["records"] = [r for r in removed["records"] if r["kind"] != "calendar"]
    adapter.synchronize(removed)
    assert plain_property(client.data["calendar"][0]["properties"]["Sync State"]) == "removed"


def test_sync_upload_cap_reports_partial_and_retry_uploads_once(tmp_path):
    file = tmp_path / "original.pdf"
    file.write_bytes(b"original bytes")
    value = store().model_dump(mode="json")
    value["courses"][0]["material_sections"] = [{"title": "Slides", "materials": [
        {"title": "One", "relative_path": "original.pdf"}]}]
    projection = build_notion_projection(InformationStore.model_validate(value),
                                         lambda p: (tmp_path / p, "application/pdf"))
    client = FakeClient(projection)
    config = {"include_execution": True, "parent_page_id": "home", "data_sources": {k: k for k in IDENTITY_PROPERTIES},
              "upload_limit_bytes": 1}
    adapter = NotionWorkspaceAdapter(client, config, tmp_path / "state.json")
    assert adapter.synchronize(projection)["status"] == "partial"
    assert client.uploads == 0
    config["upload_limit_bytes"] = 1000
    assert adapter.synchronize(projection)["uploaded"] == 1
    reloaded = NotionWorkspaceAdapter(client, config, tmp_path / "state.json")
    assert reloaded.synchronize(projection)["uploaded"] == 0
    assert client.uploads == 1


def test_sync_readback_rejects_success_response_with_missing_properties(tmp_path):
    projection = build_notion_projection(store(), lambda _: pytest.fail("unexpected file"))

    class SilentLossClient(FakeClient):
        def request(self, method, path, payload=None, **kwargs):
            result = super().request(method, path, payload, **kwargs)
            if method == "POST" and path == "/pages" and payload["parent"]["data_source_id"] == "items":
                # Simulate a write acknowledged but not actually reflected by GET.
                result["properties"].pop("Actionable", None)
                result["properties"].pop("Course", None)
            return result

    client = SilentLossClient(projection)
    config = {"include_execution": True, "parent_page_id": "home", "data_sources": {k: k for k in IDENTITY_PROPERTIES}}
    report = NotionWorkspaceAdapter(client, config, tmp_path / "state.json").synchronize(projection)
    assert report["status"] == "partial"
    assert report["verification"]["status"] == "failed"
    assert report["verification"]["matched"] < report["verification"]["expected"]
    failure = next(row for row in report["verification"]["failures"] if row["kind"] == "items")
    assert {"Actionable", "Course"} <= set(failure["properties"])


def test_sync_receipt_verifies_all_rows_and_readback_failure_is_partial(tmp_path):
    projection = build_notion_projection(store(), lambda _: pytest.fail("unexpected file"))
    config = {"include_execution": True, "parent_page_id": "home", "data_sources": {k: k for k in IDENTITY_PROPERTIES}}
    client = FakeClient(projection)
    adapter = NotionWorkspaceAdapter(client, config, tmp_path / "state.json")
    report = adapter.synchronize(projection)
    assert report["verification"] == {"status": "verified", "expected": 3, "matched": 3, "failures": []}
    calls = 0
    original = client.rows

    def fail_readback(source):
        nonlocal calls
        calls += 1
        if calls > 4:
            raise OSError("readback unavailable")
        return original(source)

    client.rows = fail_readback
    retry = adapter.synchronize(projection)
    assert retry["status"] == "partial"
    assert retry["verification"]["failures"][0]["reason"] == "readback_failed"


def test_attachment_timeout_is_reconciled_without_uploading_again(tmp_path):
    file = tmp_path / "original.pdf"
    file.write_bytes(b"unchanged")
    value = store().model_dump(mode="json")
    value["courses"][0]["material_sections"] = [{"title": "Slides", "materials": [
        {"title": "One", "relative_path": "original.pdf"}]}]
    projection = build_notion_projection(InformationStore.model_validate(value),
                                         lambda p: (tmp_path / p, "application/pdf"))
    client = FakeClient(projection)
    original_request = client.request
    failed = False
    def timeout_after_append(method, path, payload=None, **kwargs):
        nonlocal failed
        result = original_request(method, path, payload, **kwargs)
        if path.endswith("/children") and not failed:
            failed = True
            raise NotionAPIError(0, "network_error")
        return result
    client.request = timeout_after_append
    config = {"include_execution": True, "parent_page_id": "home", "data_sources": {k: k for k in IDENTITY_PROPERTIES}}
    adapter = NotionWorkspaceAdapter(client, config, tmp_path / "state.json")
    assert adapter.synchronize(projection)["status"] == "partial"
    assert adapter.synchronize(projection)["status"] == "complete"
    assert client.uploads == 1
    assert sum(len(v) for v in client.blocks.values()) == 1


def test_worker_definition_does_not_contain_credentials(tmp_path):
    destination = tmp_path / "worker.plist"
    worker_plist(tmp_path / "resources", destination)
    value = plistlib.loads(destination.read_bytes())
    assert value["KeepAlive"] is True
    assert value["ProgramArguments"][-4:] == ["notion", "work", "--interval", "300"]
    assert "HIQS_NOTION_TOKEN" not in value["EnvironmentVariables"]


def test_core_notion_status_is_secret_free_and_source_is_read_only(tmp_path, monkeypatch):
    monkeypatch.delenv("HIQS_NOTION_TOKEN", raising=False)
    path = tmp_path / "information.json"
    path.write_text(store().model_dump_json())
    original_bytes = path.read_bytes()
    save_config(tmp_path, {"token": "private-do-not-return", "parent_page_id": uuid4().hex})
    core = HIQSCore(tmp_path)
    assert "private-do-not-return" not in json.dumps(core.notion_status())
    projection = core.notion_projection()
    assert projection["counts"]["calendar"] == 0
    assert projection["scope"] == "library"
    assert path.read_bytes() == original_bytes


def test_new_downloads_enter_notion_inbox_without_inventing_facts_and_reuse_classified_ids(tmp_path):
    original = tmp_path / "new.pdf"
    duplicate = tmp_path / "copy.pdf"
    original.write_bytes(b"new lecture")
    duplicate.write_bytes(original.read_bytes())
    value = store().model_dump(mode="json")
    value["courses"][0]["additional_moodle_course_ids"] = ["2"]
    docs = [{"course_id": "2", "relative_path": n,
             "sha256": sha256(original.read_bytes()).hexdigest()} for n in ("new.pdf", "copy.pdf")]
    resolver = lambda p: (tmp_path / p, "application/pdf")
    first = build_notion_projection(InformationStore.model_validate(value), resolver, source_documents=docs)
    materials = [r for r in first["records"] if r["kind"] == "materials"]
    assert len(materials) == 1
    assert materials[0]["unreviewed"] is True
    assert materials[0]["file"]["section"] == "待整理"
    assert first["counts"]["items"] == 1
    assert first["counts"]["calendar"] == 1
    value["courses"][0]["material_sections"] = [{"title": "Week 2", "materials": [
        {"title": "New", "relative_path": "new.pdf"}]}]
    classified = build_notion_projection(InformationStore.model_validate(value), resolver, source_documents=docs)
    final = next(r for r in classified["records"] if r["kind"] == "materials")
    assert final["identity"] == materials[0]["identity"]
    assert final["file"]["section"] == "Week 2"
    bad = build_notion_projection(store(), resolver, source_documents=[
        {"course_id": "1", "relative_path": "new.pdf", "sha256": "mismatched"}])
    assert bad["counts"]["materials"] == 0
    assert bad["warnings"][0]["reason"] == "source_content_changed"


def test_library_sync_ignores_retired_sources_and_preserves_course_body(tmp_path):
    projection = _build_notion_projection(store(), lambda _: pytest.fail('unexpected file'))
    assert projection['scope'] == 'library'
    assert {r['kind'] for r in projection['records']} == {'courses'}
    assert projection['counts']['items'] == projection['counts']['calendar'] == 0

    class LibraryClient(FakeClient):
        def request(self, method, path, payload=None, **kwargs):
            assert '/data_sources/retired-' not in path
            return super().request(method, path, payload, **kwargs)
        def rows(self, source):
            assert not source.startswith('retired-')
            return super().rows(source)

    client = LibraryClient(projection)
    config = {'parent_page_id': 'home', 'data_sources': {
        'courses': 'courses', 'materials': 'materials',
        'items': 'retired-items', 'calendar': 'retired-calendar'}}
    adapter = NotionWorkspaceAdapter(client, config, tmp_path / 'state.json')
    report = adapter.synchronize(projection)
    assert report['verification']['matched'] == report['verification']['expected'] == 1
    course = client.data['courses'][0]
    client.blocks[course['id']] = [{'id': 'personal-note', 'type': 'paragraph'}]
    assert adapter.synchronize(projection)['unchanged'] == 1
    assert client.blocks[course['id']][0]['id'] == 'personal-note'
    with pytest.raises(ValueError, match='execution records'):
        adapter.synchronize(build_notion_projection(store(), lambda _: pytest.fail('unexpected file')))


def test_library_requires_only_course_and_material_sources_and_exports_no_execution(tmp_path):
    projection = _build_notion_projection(store(), lambda _: pytest.fail('unexpected file'))
    client = FakeClient(projection)
    config = {'parent_page_id': 'home', 'data_sources': {'courses': 'courses', 'materials': 'materials'}}
    assert NotionWorkspaceAdapter(client, config, tmp_path / 'state.json').check_connection()['connected']
    destination = tmp_path / 'library'
    destination.mkdir()
    for retired in ('HIQS-calendar.ics', 'items.csv', 'calendar.csv'):
        (destination / retired).write_text('retired execution export')
    export_package(projection, b'legacy calendar', destination)
    assert (destination / 'courses.csv').exists()
    assert (destination / 'materials.csv').exists()
    assert not (destination / 'items.csv').exists()
    assert not (destination / 'calendar.csv').exists()
    assert not (destination / 'HIQS-calendar.ics').exists()
    with ZipFile(destination / 'HIQS-originals.zip') as archive:
        assert not any(name.endswith('.ics') or name in {'items.csv', 'calendar.csv'} for name in archive.namelist())
