import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from AI_interface.retrieval import search_for_plan_item, search_materials
from integrated_planner.plan_schema import (
    AcademicImpact,
    EffortEstimate,
    IntegratedPlan,
    LearningDemand,
    OfficialTiming,
    PlanItem,
    PriorityDecision,
)
from moodle_collector.storage.local_store import write_model, write_text
from moodle_collector.transformation.common.course_mapper import build_course_archive
from moodle_collector.transformation.common.course_schema import StoredFile
from moodle_collector.transformation.course_materials.pdf_schema import PdfAnalysis


ROOT = Path(__file__).parents[1]
ZONE = ZoneInfo("Asia/Hong_Kong")


def _resources(tmp_path: Path) -> tuple[Path, Path, str]:
    resources = tmp_path / "resources"
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Neuroscience Demo",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    activity = archive.sections[0].activities[0]
    activity.name = "Thalamic Bridge Reading"
    text_relative = "courses/138907/analysis/text/bridge.txt"
    stamp = datetime(2026, 9, 1, 8, 0, tzinfo=ZONE)
    activity.files.append(
        StoredFile(
            filename="bridge.pdf",
            relative_path="courses/138907/files/bridge.pdf",
            source_url="https://moodle.example.edu/pluginfile.php/bridge.pdf",
            content_type="application/pdf",
            size_bytes=100,
            sha256="0" * 64,
            downloaded_at=stamp,
            analysis=PdfAnalysis(
                status="complete",
                analyzed_at=stamp,
                page_count=2,
                pages_with_text=2,
                word_count=40,
                character_count=240,
                estimated_reading_minutes=1,
                extracted_text_path=text_relative,
                extracted_text_sha256="1" * 64,
            ),
        )
    )
    write_model(resources / "courses/138907/course.json", archive)
    write_text(
        resources / text_relative,
        "--- Page 1 ---\nThe lecture introduces ordinary neural signalling.\n\n"
        "--- Page 2 ---\nA thalamic bridge may transmit sensory information "
        "between the conjoined twins and raises questions about consciousness.",
    )

    item_id = "activity:138907:bridge"
    item = PlanItem(
        plan_item_id=item_id,
        course_id="138907",
        course_title="Neuroscience Demo",
        item_type="reading",
        title="Understand sensory sharing through the thalamic bridge",
        official_timing=OfficialTiming(),
        academic_impact=AcademicImpact(
            importance_level=4,
            importance_rationale="Current core reading.",
        ),
        learning_demand=LearningDemand(
            difficulty_level=3,
            difficulty_rationale="Conceptual reading.",
        ),
        effort=EffortEstimate(
            estimated_total_minutes=45,
            completed_minutes=0,
            remaining_minutes=45,
            effort_band="s",
        ),
        priority=PriorityDecision(level="high", rationale="Current key topic."),
        completion_criteria=["Explain the proposed sensory pathway"],
        created_at=stamp,
        updated_at=stamp,
    )
    plan_path = resources / "integrated_plan.json"
    write_model(plan_path, IntegratedPlan(items=[item]))
    return resources, plan_path, item_id


def test_local_rag_returns_page_and_activity_provenance(tmp_path: Path) -> None:
    resources, _, _ = _resources(tmp_path)

    result = search_materials(
        resources,
        "thalamic bridge sensory consciousness",
        course_ids={"138907"},
        limit=3,
    )

    assert result.indexed_document_count == 1
    assert result.hits
    assert result.hits[0].course_id == "138907"
    assert result.hits[0].activity_name == "Thalamic Bridge Reading"
    assert result.hits[0].filename == "bridge.pdf"
    assert result.hits[0].page_start == 2
    assert "sensory information" in result.hits[0].text


def test_rag_for_plan_item_builds_grounded_course_scoped_query(tmp_path: Path) -> None:
    resources, plan_path, item_id = _resources(tmp_path)

    item, result = search_for_plan_item(resources, plan_path, item_id, limit=2)

    assert item.plan_item_id == item_id
    assert "Neuroscience Demo" in result.query
    assert result.course_ids == ["138907"]
    assert result.hits
    assert all(hit.course_id == item.course_id for hit in result.hits)
