import json
from pathlib import Path

from hsas.infrastructure.moodle.course_mapper import build_course_archive
from hsas.infrastructure.storage.json_store import write_model
from scripts.benchmark_material_search import benchmark


ROOT = Path(__file__).parents[1]


def test_agent_evidence_search_meets_release_smoke_budget(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Performance Demo",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    template = archive.sections[0].activities[0]
    archive.sections[0].activities = []
    for index in range(200):
        activity = template.model_copy(deep=True)
        activity.module_id = f"perf-{index}"
        activity.name = f"Performance evidence {index}"
        activity.content_text = (
            f"neural calculus performance marker {index} " + "supporting evidence " * 80
        )
        archive.sections[0].activities.append(activity)
    write_model(resources / "courses/138907/course.json", archive)

    result = benchmark(
        resources,
        ["neural calculus", "performance marker", "supporting evidence"],
        iterations=30,
    )

    assert result["indexed_document_count"] == 200
    assert result["cold_index_and_query_ms"] < 10_000
    assert result["warm_query_p95_ms"] < 500
    assert result["first_evidence_p95_ms"] < 500
