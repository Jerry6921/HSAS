from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from hsas.domain.planning.define_execution import ExecutionLog
from hsas.application.record_execution import (
    ExecutionServiceError,
    add_execution_record,
    correct_execution_record,
    load_execution_log,
)
from hsas.domain.planning.define_plan import (
    AcademicImpact,
    EffortEstimate,
    IntegratedPlan,
    LearningDemand,
    OfficialTiming,
    PlanItem,
    PriorityDecision,
)
from hsas.infrastructure.storage.persist_data import write_model


ZONE = ZoneInfo("Asia/Hong_Kong")


def _paths(tmp_path: Path) -> tuple[Path, Path]:
    stamp = datetime(2026, 9, 1, 8, 0, tzinfo=ZONE)
    item = PlanItem(
        plan_item_id="assessment:1:essay",
        course_id="1",
        course_title="Demo",
        item_type="assessment",
        title="Essay",
        official_timing=OfficialTiming(),
        academic_impact=AcademicImpact(
            importance_level=4,
            importance_rationale="Major work.",
        ),
        learning_demand=LearningDemand(
            difficulty_level=3,
            difficulty_rationale="Writing.",
        ),
        effort=EffortEstimate(
            estimated_total_minutes=180,
            completed_minutes=0,
            remaining_minutes=180,
            effort_band="m",
        ),
        priority=PriorityDecision(level="high", rationale="Due soon."),
        created_at=stamp,
        updated_at=stamp,
    )
    plan_path = tmp_path / "integrated_plan.json"
    log_path = tmp_path / "execution_log.json"
    write_model(plan_path, IntegratedPlan(items=[item]))
    write_model(log_path, ExecutionLog())
    return plan_path, log_path


def test_add_execution_derives_item_type_and_is_idempotent(tmp_path: Path) -> None:
    plan_path, log_path = _paths(tmp_path)
    stamp = datetime(2026, 9, 1, 10, 5, tzinfo=ZONE)
    arguments = {
        "plan_item_id": "assessment:1:essay",
        "actual_minutes": 75,
        "progress_minutes": 60,
        "planned_minutes": 60,
        "record_id": "execution:test:1",
        "recorded_at": stamp,
    }

    log, record, created = add_execution_record(log_path, plan_path, **arguments)
    retried_log, retried_record, retried = add_execution_record(
        log_path,
        plan_path,
        **arguments,
    )

    assert created is True
    assert retried is False
    assert record == retried_record
    assert record.item_type == "assessment"
    assert record.planned_minutes == 60
    assert len(log.records) == len(retried_log.records) == 1
    assert len(load_execution_log(log_path).records) == 1


def test_execution_duplicate_conflict_and_unknown_reference_do_not_write(
    tmp_path: Path,
) -> None:
    plan_path, log_path = _paths(tmp_path)
    stamp = datetime(2026, 9, 1, 10, 5, tzinfo=ZONE)
    add_execution_record(
        log_path,
        plan_path,
        plan_item_id="assessment:1:essay",
        actual_minutes=60,
        progress_minutes=60,
        planned_minutes=60,
        record_id="execution:test:1",
        recorded_at=stamp,
    )
    before = log_path.read_text(encoding="utf-8")

    with pytest.raises(ExecutionServiceError, match="different data"):
        add_execution_record(
            log_path,
            plan_path,
            plan_item_id="assessment:1:essay",
            actual_minutes=90,
            progress_minutes=60,
            planned_minutes=60,
            record_id="execution:test:1",
            recorded_at=stamp,
        )
    with pytest.raises(ExecutionServiceError, match="unknown plan_item_id"):
        add_execution_record(
            log_path,
            plan_path,
            plan_item_id="missing",
            actual_minutes=30,
            progress_minutes=30,
            planned_minutes=30,
        )

    assert log_path.read_text(encoding="utf-8") == before


def test_correct_execution_preserves_identity_and_revalidates_reference(
    tmp_path: Path,
) -> None:
    plan_path, log_path = _paths(tmp_path)
    add_execution_record(
        log_path,
        plan_path,
        plan_item_id="assessment:1:essay",
        actual_minutes=45,
        progress_minutes=40,
        planned_minutes=60,
        record_id="execution:test:1",
    )

    log, corrected = correct_execution_record(
        log_path,
        plan_path,
        "execution:test:1",
        actual_minutes=55,
        progress_minutes=50,
        item_completed=True,
        notes="Student-confirmed correction",
    )

    assert corrected.record_id == "execution:test:1"
    assert corrected.actual_minutes == 55
    assert corrected.progress_minutes == 50
    assert corrected.item_completed is True
    assert len(log.records) == 1
