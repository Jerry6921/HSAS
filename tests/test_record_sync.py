from pathlib import Path

from hsas.infrastructure.storage.persist_data import read_json
from hsas.infrastructure.moodle.record_sync import record_sync_operation, sync_warnings


def test_sync_report_preserves_per_course_status_across_scopes(tmp_path: Path) -> None:
    record_sync_operation(
        tmp_path,
        scope="all",
        discovered_course_count=2,
        course_results=[
            {"course_id": "1", "course": "One", "succeeded": True},
            {"course_id": "2", "course": "Two", "succeeded": False, "error": "timeout"},
        ],
    )
    record_sync_operation(
        tmp_path,
        scope="single",
        discovered_course_count=1,
        course_results=[
            {"course_id": "2", "course": "Two", "succeeded": True, "change_count": 3}
        ],
    )

    report = read_json(tmp_path / "sync-report.json")
    assert report["courses"]["1"]["succeeded"] is True
    assert report["courses"]["2"]["succeeded"] is True
    assert sync_warnings(tmp_path, {"1", "2"}) == []
