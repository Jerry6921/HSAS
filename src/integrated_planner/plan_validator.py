from __future__ import annotations

from collections import defaultdict
from datetime import date as Date
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from moodle_collector.contracts import ArchiveIndex, StrictModel
from .execution_schema import ExecutionLog
from .plan_rules import effective_deadline
from .plan_schema import IntegratedPlan, PlanItem, TimetableBlock
from .profile_schema import FixedCommitment, StudentProfile


class ValidationIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    paths: list[str] = Field(default_factory=list)


class PlanValidationReport(StrictModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)


def validate_integrated_plan(
    plan: IntegratedPlan,
    profile: StudentProfile,
    archives: list[ArchiveIndex],
    execution_log: ExecutionLog | None = None,
) -> PlanValidationReport:
    """Validate references, key-workload totals, and deadline-safe milestones."""
    issues: list[ValidationIssue] = []
    archive_by_course: dict[str, ArchiveIndex] = {}
    for index in archives:
        course_id = index.archive.course.course_id
        if course_id in archive_by_course:
            issues.append(
                _issue(
                    "error",
                    "reference.duplicate_course_archive",
                    f"Multiple archives use course_id {course_id}.",
                    "source_snapshot.course_archives",
                )
            )
        archive_by_course[course_id] = index

    item_by_id = {item.plan_item_id: item for item in plan.items}
    _validate_profile_references(profile, archive_by_course, issues)
    _validate_source_snapshot(plan, archive_by_course, issues)

    for position, item in enumerate(plan.items):
        _validate_item_references(
            item,
            position,
            item_by_id,
            archive_by_course,
            issues,
        )
    _validate_dependency_cycles(plan.items, issues)
    if plan.planning_mode == "legacy_timetable":
        _validate_timetable(plan, profile, item_by_id, issues)
        _validate_capacity_summary(plan, issues)
    _validate_milestones(plan, item_by_id, issues)
    _validate_workload_summary(plan, issues)
    _validate_execution_log(execution_log, item_by_id, issues)

    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    return PlanValidationReport(valid=not errors, errors=errors, warnings=warnings)


def _validate_profile_references(
    profile: StudentProfile,
    archives: dict[str, ArchiveIndex],
    issues: list[ValidationIssue],
) -> None:
    target_ids = {
        target.course_id for target in profile.academic_goals.course_targets
    }
    for course_id in sorted(
        target_ids
        | set(profile.academic_goals.priority_course_ids)
        | {state.course_id for state in profile.course_states}
    ):
        if course_id not in archives:
            issues.append(
                _issue(
                    "warning",
                    "reference.profile_course_missing",
                    f"Student Profile references unsynchronized course {course_id}.",
                    "student_profile.json",
                )
            )

    for state_index, state in enumerate(profile.course_states):
        archive = archives.get(state.course_id)
        if archive is None:
            continue
        for activity_id in state.completed_activity_ids:
            if archive.get_activity(activity_id) is None:
                issues.append(
                    _issue(
                        "warning",
                        "reference.profile_activity_missing",
                        f"Profile activity {activity_id} is absent from course "
                        f"{state.course_id}.",
                        f"profile.course_states[{state_index}]",
                    )
                )
        for result in state.known_assessment_results:
            if archive.get_assessment(result.assessment_id) is None:
                issues.append(
                    _issue(
                        "warning",
                        "reference.profile_assessment_missing",
                        f"Profile assessment {result.assessment_id} is absent from "
                        f"course {state.course_id}.",
                        f"profile.course_states[{state_index}]",
                    )
                )


def _validate_source_snapshot(
    plan: IntegratedPlan,
    archives: dict[str, ArchiveIndex],
    issues: list[ValidationIssue],
) -> None:
    snapshot_ids = [entry.course_id for entry in plan.source_snapshot.course_archives]
    if len(snapshot_ids) != len(set(snapshot_ids)):
        issues.append(
            _issue(
                "error",
                "reference.duplicate_source_snapshot",
                "source_snapshot contains duplicate course IDs.",
                "source_snapshot.course_archives",
            )
        )
    for entry in plan.source_snapshot.course_archives:
        archive = archives.get(entry.course_id)
        if archive is None:
            issues.append(
                _issue(
                    "error",
                    "reference.snapshot_course_missing",
                    f"Snapshot references missing course {entry.course_id}.",
                    "source_snapshot.course_archives",
                )
            )
        elif entry.collected_at != archive.archive.collected_at:
            issues.append(
                _issue(
                    "warning",
                    "freshness.course_archive_changed",
                    f"Course {entry.course_id} changed after this plan snapshot.",
                    "source_snapshot.course_archives",
                )
            )


def _validate_item_references(
    item: PlanItem,
    position: int,
    item_by_id: dict[str, PlanItem],
    archives: dict[str, ArchiveIndex],
    issues: list[ValidationIssue],
) -> None:
    path = f"items[{position}]"
    archive = archives.get(item.course_id)
    if archive is None:
        issues.append(
            _issue(
                "error",
                "reference.course_missing",
                f"Plan item references missing course {item.course_id}.",
                path,
            )
        )
        return

    if item.course_title != archive.archive.course.title:
        issues.append(
            _issue(
                "warning",
                "reference.course_title_changed",
                f"Plan title differs from current title for course {item.course_id}.",
                path,
            )
        )
    if (
        item.source_section_id is not None
        and archive.get_section(item.source_section_id) is None
    ):
        issues.append(
            _issue(
                "error",
                "reference.section_missing",
                f"Unknown section {item.source_section_id} in course {item.course_id}.",
                path,
            )
        )
    if item.source_activity_id is not None:
        activity = archive.get_activity(item.source_activity_id)
        if activity is None:
            issues.append(
                _issue(
                    "error",
                    "reference.activity_missing",
                    f"Unknown activity {item.source_activity_id} in course "
                    f"{item.course_id}.",
                    path,
                )
            )
        elif (
            item.source_section_id is not None
            and archive.get_activity_section_id(item.source_activity_id)
            != item.source_section_id
        ):
            issues.append(
                _issue(
                    "error",
                    "reference.activity_section_mismatch",
                    f"Activity {item.source_activity_id} does not belong to section "
                    f"{item.source_section_id}.",
                    path,
                )
            )
    if (
        item.source_assessment_id is not None
        and archive.get_assessment(item.source_assessment_id) is None
    ):
        issues.append(
            _issue(
                "error",
                "reference.assessment_missing",
                f"Unknown assessment {item.source_assessment_id} in course "
                f"{item.course_id}.",
                path,
            )
        )
    group_id = item.academic_impact.assessment_group_id
    if group_id is not None and archive.get_group(group_id) is None:
        issues.append(
            _issue(
                "error",
                "reference.assessment_group_missing",
                f"Unknown assessment group {group_id} in course {item.course_id}.",
                path,
            )
        )
    for dependency_id in item.learning_demand.prerequisite_item_ids:
        if dependency_id not in item_by_id:
            issues.append(
                _issue(
                    "error",
                    "reference.dependency_missing",
                    f"Unknown prerequisite item {dependency_id}.",
                    path,
                )
            )
        elif dependency_id == item.plan_item_id:
            issues.append(
                _issue(
                    "error",
                    "reference.self_dependency",
                    f"Item {item.plan_item_id} depends on itself.",
                    path,
                )
            )


def _validate_dependency_cycles(
    items: list[PlanItem],
    issues: list[ValidationIssue],
) -> None:
    graph = {
        item.plan_item_id: item.learning_demand.prerequisite_item_ids
        for item in items
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item_id: str, trail: list[str]) -> None:
        if item_id in visiting:
            cycle = trail[trail.index(item_id):]
            issues.append(
                _issue(
                    "error",
                    "reference.dependency_cycle",
                    "Dependency cycle: " + " -> ".join(cycle),
                    "items",
                )
            )
            return
        if item_id in visited:
            return
        visiting.add(item_id)
        for dependency in graph.get(item_id, []):
            if dependency in graph:
                visit(dependency, trail + [dependency])
        visiting.remove(item_id)
        visited.add(item_id)

    for item_id in graph:
        visit(item_id, [item_id])


def _validate_timetable(
    plan: IntegratedPlan,
    profile: StudentProfile,
    item_by_id: dict[str, PlanItem],
    issues: list[ValidationIssue],
) -> None:
    active_blocks = [
        block
        for block in plan.timetable
        if block.status not in {"missed", "rescheduled"}
    ]
    by_date: dict[Date, list[tuple[int, TimetableBlock]]] = defaultdict(list)
    for index, block in enumerate(active_blocks):
        by_date[block.date].append((index, block))
        item = item_by_id[block.plan_item_id]
        block_start, block_end = _block_datetimes(block, plan.timezone)
        due = effective_deadline(
            item.official_timing,
            ZoneInfo(plan.timezone),
        )
        if due and block_end > due:
            issues.append(
                _issue(
                    "error",
                    "schedule.after_official_deadline",
                    f"Block {block.block_id} ends after the official deadline.",
                    f"timetable[{index}]",
                )
            )
        opens = _effective_opening(item, ZoneInfo(plan.timezone))
        if opens and block_start < opens:
            issues.append(
                _issue(
                    "warning",
                    "schedule.before_open",
                    f"Block {block.block_id} starts before the item opens.",
                    f"timetable[{index}]",
                )
            )

        availability = _availability_for_date(profile, block.date)
        has_availability_rules = bool(
            profile.availability.weekly_pattern
            or profile.availability.date_exceptions
        )
        if has_availability_rules and not any(
            block.start_time >= available.start and block.end_time <= available.end
            for available in availability
        ):
            issues.append(
                _issue(
                    "warning",
                    "schedule.outside_availability",
                    f"Block {block.block_id} is outside the student's availability.",
                    f"timetable[{index}]",
                )
            )
        for commitment in _commitments_for_date(profile, block.date):
            if _times_overlap(
                block.start_time,
                block.end_time,
                commitment.start,
                commitment.end,
            ):
                issues.append(
                    _issue(
                        "error",
                        "schedule.fixed_commitment_conflict",
                        f"Block {block.block_id} overlaps {commitment.title}.",
                        f"timetable[{index}]",
                    )
                )

    for day, entries in by_date.items():
        ordered = sorted(entries, key=lambda entry: entry[1].start_time)
        for (left_index, left), (right_index, right) in zip(ordered, ordered[1:]):
            if right.start_time < left.end_time:
                issues.append(
                    _issue(
                        "error",
                        "schedule.block_overlap",
                        f"Blocks {left.block_id} and {right.block_id} overlap on {day}.",
                        f"timetable[{left_index}]",
                        f"timetable[{right_index}]",
                    )
                )
        maximum = profile.availability.maximum_study_minutes_per_day
        total = sum(block.planned_minutes for _, block in entries)
        if maximum is not None and total > maximum:
            issues.append(
                _issue(
                    "error",
                    "schedule.daily_capacity_exceeded",
                    f"Scheduled {total} minutes on {day}; profile maximum is "
                    f"{maximum}.",
                    "timetable",
                )
            )


def _validate_milestones(
    plan: IntegratedPlan,
    item_by_id: dict[str, PlanItem],
    issues: list[ValidationIssue],
) -> None:
    for index, milestone in enumerate(plan.milestones):
        item = item_by_id[milestone.plan_item_id]
        zone = ZoneInfo(plan.timezone)
        due = effective_deadline(item.official_timing, zone)
        target = milestone.target_at
        target = (
            target.replace(tzinfo=zone)
            if target.tzinfo is None
            else target.astimezone(zone)
        )
        if due and target > due:
            issues.append(
                _issue(
                    "error",
                    "deadline.milestone_after_official_deadline",
                    f"Milestone {milestone.milestone_id} is after the official "
                    "deadline.",
                    f"milestones[{index}]",
                )
            )


def _validate_capacity_summary(
    plan: IntegratedPlan,
    issues: list[ValidationIssue],
) -> None:
    scheduled = sum(
        block.planned_minutes
        for block in plan.timetable
        if block.status not in {"missed", "rescheduled"}
    )
    if scheduled != plan.capacity_summary.scheduled_minutes:
        issues.append(
            _issue(
                "warning",
                "capacity.scheduled_minutes_mismatch",
                f"capacity_summary says {plan.capacity_summary.scheduled_minutes} "
                f"minutes, but timetable contains {scheduled}.",
                "capacity_summary.scheduled_minutes",
            )
        )
    available = plan.capacity_summary.available_minutes
    if available is not None:
        expected_over = plan.capacity_summary.unscheduled_workload_minutes > 0
        if expected_over != plan.capacity_summary.over_capacity:
            issues.append(
                _issue(
                    "warning",
                    "capacity.over_capacity_mismatch",
                    "capacity_summary.over_capacity is inconsistent.",
                    "capacity_summary.over_capacity",
                )
            )
    if plan.capacity_summary.over_capacity:
        issues.append(
            _issue(
                "warning",
                "capacity.workload_exceeds_capacity",
                f"{plan.capacity_summary.unscheduled_workload_minutes} minute(s) "
                "of required work could not be scheduled in the planning window.",
                "capacity_summary.unscheduled_workload_minutes",
            )
        )


def _validate_workload_summary(
    plan: IntegratedPlan,
    issues: list[ValidationIssue],
) -> None:
    estimated = [
        item for item in plan.items if item.effort.remaining_minutes is not None
    ]
    expected = {
        "key_item_count": len(plan.items),
        "estimated_item_count": len(estimated),
        "unestimated_item_count": len(plan.items) - len(estimated),
        "total_remaining_minutes": sum(
            item.effort.remaining_minutes or 0 for item in estimated
        ),
    }
    for level, field in {
        "critical": "critical_minutes",
        "high": "high_priority_minutes",
        "medium": "medium_priority_minutes",
        "planned": "planned_minutes",
    }.items():
        expected[field] = sum(
            item.effort.remaining_minutes or 0
            for item in estimated
            if item.priority.level == level
        )
    for field, value in expected.items():
        if getattr(plan.workload_summary, field) != value:
            issues.append(
                _issue(
                    "error",
                    "workload.summary_mismatch",
                    f"workload_summary.{field} must equal {value}.",
                    f"workload_summary.{field}",
                )
            )


def _validate_execution_log(
    execution_log: ExecutionLog | None,
    item_by_id: dict[str, PlanItem],
    issues: list[ValidationIssue],
) -> None:
    if execution_log is None:
        return
    for index, record in enumerate(execution_log.records):
        item = item_by_id.get(record.plan_item_id)
        if item is None:
            issues.append(
                _issue(
                    "warning",
                    "reference.execution_item_missing",
                    f"Execution record {record.record_id} references a missing plan item.",
                    f"execution_log.records[{index}]",
                )
            )
        elif record.item_type != item.item_type:
            issues.append(
                _issue(
                    "warning",
                    "reference.execution_item_type_changed",
                    f"Execution record {record.record_id} uses item_type "
                    f"{record.item_type}, current plan item uses {item.item_type}.",
                    f"execution_log.records[{index}]",
                )
            )


def _effective_opening(item: PlanItem, zone: ZoneInfo) -> datetime | None:
    timing = item.official_timing
    if timing.opens_at:
        return timing.opens_at.astimezone(zone)
    if timing.opens_on:
        return datetime.combine(timing.opens_on, datetime.min.time(), tzinfo=zone)
    return None


def _availability_for_date(profile: StudentProfile, day: Date):
    for exception in profile.availability.date_exceptions:
        if exception.date == day:
            return exception.available_blocks
    day_name = day.strftime("%A").casefold()
    for weekly in profile.availability.weekly_pattern:
        if weekly.day_of_week == day_name:
            return weekly.available_blocks
    return []


def _commitments_for_date(
    profile: StudentProfile,
    day: Date,
) -> list[FixedCommitment]:
    day_name = day.strftime("%A").casefold()
    return [
        commitment
        for commitment in profile.availability.fixed_commitments
        if commitment.date == day or commitment.day_of_week == day_name
    ]


def _block_datetimes(
    block: TimetableBlock,
    timezone_name: str,
) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(timezone_name)
    return (
        datetime.combine(block.date, block.start_time, tzinfo=timezone),
        datetime.combine(block.date, block.end_time, tzinfo=timezone),
    )


def _times_overlap(start_a, end_a, start_b, end_b) -> bool:
    return start_a < end_b and start_b < end_a


def _issue(
    severity: Literal["error", "warning"],
    code: str,
    message: str,
    *paths: str,
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity,
        code=code,
        message=message,
        paths=list(paths),
    )
