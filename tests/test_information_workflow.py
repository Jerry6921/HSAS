"""Observable guarantees for file review, calendar and actionable-task delivery."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from hsas.application.information_audit import audit_information
from hsas.application.material_search import list_materials
from hsas.application.notion_projection import build_notion_projection, expand_calendar
from hsas.core import HIQSCore
from hsas.core.ports import HIQSPortError
from hsas.domain.courses.documents import PdfAnalysis
from hsas.domain.courses.evidence import LinkedPageEvidence
from hsas.domain.courses.models import StoredFile
from hsas.domain.information import InformationStore
from hsas.domain.information.calendar import build_ics
from hsas.infrastructure.moodle.course_mapper import build_course_archive
from hsas.infrastructure.storage.json_store import write_model


def candidate(items):
    return InformationStore.model_validate({
        "updated_at": "2026-10-27T08:00:00Z",
        "courses": [{"course_id": "1", "code": "DEMO1001", "title": "Demo"}],
        "items": [{"course_id": "1", "category": "assignment", **item} for item in items],
    })


def test_preview_checks_merged_course_references_and_never_writes(tmp_path):
    core = HIQSCore(tmp_path)
    update = {"items": [{"item_id": "orphan", "course_id": "missing",
                         "title": "Orphan", "category": "assignment"}]}
    with pytest.raises(HIQSPortError, match="unknown course"):
        core.validate_information_update({"update": update})
    assert not (tmp_path / "information.json").exists()


def test_preview_audits_preserved_items_and_apply_returns_same_projection(tmp_path):
    core = HIQSCore(tmp_path)
    initial = candidate([{"item_id": "old", "title": "Date pending"}])
    write_model(tmp_path / "information.json", initial)
    update = {"items": [{"course_id": "1", "category": "report", "item_id": "new",
                         "title": "Report", "due_on": "2026-11-01"}]}
    preview = core.validate_information_update({"update": update})
    audit = preview["quality_audit"]
    assert audit["counts"]["actionable_items"] == 2
    assert audit["counts"]["undated_actionable_items"] == 1
    assert audit["source_reading_verified"] is False
    assert not (tmp_path / "ai-state/recent-information-update.json").exists()
    applied = core.apply_information_update({"update": update, "confirmed": True})
    assert applied["quality_audit"] == audit
    assert len(applied["information"]["items"]) == 2


def test_distinct_opening_meeting_and_deadline_survive_both_calendar_formats():
    store = candidate([{"item_id": "submission", "title": "Presentation",
        "starts_at": "2026-11-01T10:00:00+08:00",
        "ends_at": "2026-11-01T11:00:00+08:00",
        "opens_at": "2026-10-30T09:00:00+08:00", "due_on": "2026-11-02",
        "date_status": "tentative"}])
    rows = expand_calendar(store.items[0].model_dump(mode="json"), store.timezone)
    assert {row["identity"] for row in rows} == {
        "submission:2026-11-01", "submission:2026-10-30:opens", "submission:2026-11-02:due"}
    deadline = next(row for row in rows if row["identity"].endswith(":due"))
    assert deadline["start"] == "2026-11-02" and deadline["end"] is None
    content = build_ics(store)
    assert content.count("BEGIN:VEVENT") == 3
    assert content.count("STATUS:TENTATIVE") == 3
    assert "DTSTART;VALUE=DATE:20261102" in content
    uids = [line for line in content.splitlines() if line.startswith("UID:")]
    assert len(set(uids)) == 3


def test_opening_only_fact_is_not_lost_and_equal_start_and_due_do_not_duplicate():
    store = candidate([
        {"item_id": "opening", "title": "Registration opens", "opens_at": "2026-11-01T09:00:00Z"},
        {"item_id": "same", "title": "Quiz", "starts_at": "2026-11-02T09:00:00Z",
         "due_at": "2026-11-02T17:00:00+08:00"}])
    assert build_ics(store).count("BEGIN:VEVENT") == 2
    assert audit_information(store)["counts"]["calendar_occurrences"] == 2


def test_date_only_meeting_and_submission_are_distinct_milestones():
    store = candidate([{"item_id": "both", "title": "Project review",
                        "scheduled_on": "2026-11-01", "due_on": "2026-11-03"}])
    rows = expand_calendar(store.items[0].model_dump(mode="json"), store.timezone)
    assert {row["start"] for row in rows} == {"2026-11-01", "2026-11-03"}
    assert build_ics(store).count("BEGIN:VEVENT") == 2


def test_short_recurrence_does_not_invent_meetings_and_keeps_explicit_makeups():
    item = {"item_id": "short", "title": "Short rule", "recurrence": {
        "valid_from": "2026-11-02", "valid_until": "2026-11-03", "weekdays": [4],
        "start_time": "10:00", "end_time": "11:00"}}
    store = candidate([item])
    assert expand_calendar(store.items[0].model_dump(mode="json"), store.timezone) == []
    assert "BEGIN:VEVENT" not in build_ics(store)
    item["recurrence"]["additional_dates"] = ["2026-11-04"]
    store = candidate([item])
    assert len(expand_calendar(store.items[0].model_dump(mode="json"), store.timezone)) == 1
    assert build_ics(store).count("BEGIN:VEVENT") == 1
    assert "20261104T100000" in build_ics(store)


def test_recurring_meetings_retain_separate_opening_and_deadline():
    store = candidate([{"item_id": "weekly", "title": "Weekly project",
        "opens_at": "2026-11-01T09:00:00+08:00", "due_on": "2026-11-10",
        "recurrence": {"weekdays": [0], "valid_from": "2026-11-02",
            "valid_until": "2026-11-09", "start_time": "10:00", "end_time": "11:00"}}])
    rows = expand_calendar(store.items[0].model_dump(mode="json"), store.timezone)
    assert len(rows) == 4
    assert {row["identity"] for row in rows} == {
        "weekly:2026-11-02", "weekly:2026-11-09", "weekly:2026-11-10:due", "weekly:2026-11-01:opens"}
    assert build_ics(store).count("BEGIN:VEVENT") == 3  # one weekly rule + two milestones


def test_shared_apply_guard_also_protects_recovery_and_inbox_callers(tmp_path):
    from hsas.application.information import apply_information_update, InformationServiceError
    from hsas.infrastructure.storage import JsonInformationRepository

    update = candidate([{"item_id": "bad", "title": "Date mismatch",
        "due_at": "2026-11-01T16:00:00Z", "due_on": "2026-11-01"}]).model_dump(mode="json")
    update.pop("updated_at")
    path = tmp_path / "information.json"
    with pytest.raises(InformationServiceError, match="DEADLINE_DATE_MISMATCH"):
        apply_information_update(path, update, confirmed=True, repository=JsonInformationRepository())
    assert not path.exists()


def test_task_roles_allow_arbitrary_actions_and_keep_undated_tasks_visible():
    store = candidate([
        {"item_id": "overview", "title": "Assessment overview", "task_role": "reference"},
        {"item_id": "register", "title": "Choose a group", "category": "other", "task_role": "action"},
        {"item_id": "reading", "title": "Required reading", "category": "reading", "task_role": "action"},
        {"item_id": "ENGG1000-assignments-overall", "title": "Legacy summary"},
    ])
    projection = build_notion_projection(store, lambda _: pytest.fail("unexpected file"), include_execution=True)
    rows = {row["identity"]: row for row in projection["records"] if row["kind"] == "items"}
    assert rows["register"]["properties"]["Actionable"] == {"checkbox": True}
    assert rows["reading"]["initial_status"] == "To-do"
    assert rows["overview"]["initial_status"] is None
    assert rows["ENGG1000-assignments-overall"]["initial_status"] is None
    assert projection["task_counts"] == {"actionable": 2, "undated_actionable": 2}
    assert projection["counts"]["calendar"] == 0
    assert all("Personal Status" not in row["properties"] for row in rows.values())


def test_audit_reports_duplicate_instants_and_contradictory_deadline_fields():
    one = {"item_id": "a", "title": "Same task", "due_at": "2026-11-01T16:00:00Z",
           "due_on": "2026-11-01", "opens_at": "2026-11-04T00:00:00Z"}
    two = {**deepcopy(one), "item_id": "b", "due_at": "2026-11-02T00:00:00+08:00"}
    audit = audit_information(candidate([one, two]))
    codes = {finding["code"] for finding in audit["findings"]}
    assert {"DEADLINE_DATE_MISMATCH", "OPENS_AFTER_DEADLINE", "POSSIBLE_DUPLICATE_ITEMS"} <= codes
    assert audit["semantic_accuracy_verified"] is False


def test_inconsistent_incoming_dates_cannot_write_or_acknowledge(tmp_path):
    core = HIQSCore(tmp_path)
    update = candidate([{"item_id": "bad", "title": "Report",
        "opens_at": "2026-11-03T00:00:00Z", "due_at": "2026-11-01T00:00:00Z"}]).model_dump(mode="json")
    update.pop("updated_at")
    preview = core.validate_information_update({"update": update})
    assert preview["valid"] and not preview["ready_to_apply"]
    with pytest.raises(HIQSPortError, match="OPENS_AFTER_DEADLINE"):
        core.apply_information_update({"update": update, "confirmed": True})
    assert not (tmp_path / "information.json").exists()
    assert not (tmp_path / "ai-state/change-checkpoint.json").exists()


def test_manifest_accounts_for_unassigned_failed_truncated_and_visual_sources(tmp_path):
    fixture = Path(__file__).parent / "fixtures/course_state.json"
    archive = build_course_archive(json.loads(fixture.read_text()),
        course_title="Demo", raw_state_path="courses/138907/raw/course-state.json")
    activity = archive.sections[0].activities.pop(0)
    archive.unassigned_activities.append(activity)
    activity.download_status = "failed"
    activity.collection_report.truncated = True
    activity.linked_pages = [LinkedPageEvidence(url="https://example.edu/blocked", status="not_accessible")]
    stamp = datetime(2026, 10, 27, tzinfo=timezone.utc)
    activity.files.append(StoredFile(filename="scan.pdf", relative_path="courses/138907/files/scan.pdf",
        source_url="https://example.edu/scan.pdf", content_type="application/pdf", size_bytes=1,
        sha256="0" * 64, downloaded_at=stamp,
        analysis=PdfAnalysis(status="partial", analyzed_at=stamp, page_count=2, pages_with_text=1,
            word_count=1, character_count=1, estimated_reading_minutes=1, ocr_required=True,
            extracted_text_path="courses/138907/analysis/text/scan.txt")))
    write_model(tmp_path / "courses/138907/course.json", archive)
    manifest = list_materials(tmp_path, course_ids={"138907", "missing"})
    codes = {gap["code"] for gap in manifest["coverage"]["gaps"]}
    assert {"ACTIVITY_FAILED", "COLLECTION_TRUNCATED", "LINKED_PAGE_INCOMPLETE",
            "ORIGINAL_UNAVAILABLE", "EXTRACTION_INCOMPLETE", "VISUAL_UNITS_REQUIRE_REVIEW",
            "TEXT_UNAVAILABLE_REQUIRES_FORMAT_READER", "COURSE_ARCHIVE_UNAVAILABLE"} <= codes
    assert any(row["activity_id"] == activity.module_id for row in manifest["activities"])
    assert manifest["documents"][0]["ocr_required"] is True
    assert manifest["documents"][0]["unit_count"] == 2
    assert manifest["coverage"]["source_reading_verified"] is False
