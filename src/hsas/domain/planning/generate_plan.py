from __future__ import annotations

from datetime import date as Date
from datetime import datetime, time as Time, timedelta, timezone
from zoneinfo import ZoneInfo

from hsas.domain.courses import (
    AssessmentItem,
    ArchiveIndex,
    CourseActivity,
    iter_activities,
)
from .define_execution import ExecutionLog
from .calculate_feedback import FeedbackIndex
from .calculate_priority import (
    PRIORITY_RANK,
    activity_completion_criterion as _activity_completion_criterion,
    activity_difficulty as _activity_difficulty,
    activity_effort as _activity_effort,
    activity_importance as _activity_importance,
    activity_item_type as _activity_item_type,
    activity_readiness as _activity_readiness,
    activity_timing as _activity_timing,
    assessment_difficulty as _assessment_difficulty,
    assessment_effort as _assessment_effort,
    assessment_importance as _assessment_importance,
    assessment_item_type as _assessment_item_type,
    assessment_readiness as _assessment_readiness,
    effective_deadline as _effective_deadline,
    effort_band as _effort_band,
    plan_source_reference as _plan_source_reference,
    priority_decision as _priority_decision,
    source_path as _source_path,
    weak_topic_match as _weak_topic_match,
)
from .define_plan import (
    AcademicImpact,
    CapacitySummary,
    CourseArchiveSnapshot,
    EffortEstimate,
    FeedbackSummary,
    IntegratedPlan,
    LearningDemand,
    Milestone,
    OfficialTiming,
    PlanItem,
    PlanningWindow,
    PlanSourceReference,
    PlanSummary,
    SourceSnapshot,
    WorkloadSummary,
)
from .define_profile import CourseState, StudentProfile


MILESTONE_STRATEGIES: dict[str, tuple[tuple[str, str, float], ...]] = {
    "essay": (
        ("requirements", "Confirm requirements and thesis for {title}", 0.15),
        ("research-outline", "Complete research and outline for {title}", 0.40),
        ("first-draft", "Complete first draft of {title}", 0.70),
        ("revision", "Revise argument, evidence, and references for {title}", 0.90),
        ("submission-ready", "Finalize and verify submission of {title}", 1.00),
    ),
    "exam": (
        ("diagnostic", "Confirm scope and complete diagnostic for {title}", 0.15),
        ("coverage", "Complete first-pass concept review for {title}", 0.45),
        ("practice", "Complete targeted practice for {title}", 0.70),
        ("mock-exam", "Complete timed mock for {title}", 0.88),
        ("final-review", "Finish error review and exam readiness for {title}", 1.00),
    ),
    "project": (
        ("scope", "Confirm scope, deliverables, and roles for {title}", 0.15),
        ("prototype", "Complete initial design or prototype for {title}", 0.40),
        ("core-build", "Complete core implementation for {title}", 0.70),
        ("integration", "Integrate, test, and revise {title}", 0.90),
        ("submission-ready", "Package and verify final delivery of {title}", 1.00),
    ),
    "presentation": (
        ("message-outline", "Confirm message and outline for {title}", 0.20),
        ("draft-deck", "Complete draft slides or materials for {title}", 0.50),
        ("rehearsal", "Complete timed rehearsal and revisions for {title}", 0.80),
        ("delivery-ready", "Finish final rehearsal and technical check for {title}", 1.00),
    ),
    "default": (
        ("ready", "Complete {title} before submission buffer", 1.00),
    ),
}


class PlannerEngine:
    """Build or refresh a deterministic cross-course plan."""

    def generate(
        self,
        profile: StudentProfile,
        archives: list[ArchiveIndex],
        *,
        existing_plan: IntegratedPlan | None = None,
        execution_log: ExecutionLog | None = None,
        start_date: Date | None = None,
        horizon_days: int | None = None,
        now: datetime | None = None,
    ) -> IntegratedPlan:
        zone = ZoneInfo(profile.timezone)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=zone)
        current = current.astimezone(zone)
        start = start_date or current.date()
        days = horizon_days or profile.planning_preferences.default_planning_horizon_days
        end = start + timedelta(days=days - 1)
        old_items = {
            item.plan_item_id: item
            for item in (existing_plan.items if existing_plan else [])
        }
        feedback = FeedbackIndex(execution_log)
        profile_states = {state.course_id: state for state in profile.course_states}
        items: list[PlanItem] = []
        source_snapshots: list[CourseArchiveSnapshot] = []
        warnings: list[str] = []

        for index in sorted(
            archives,
            key=lambda value: value.archive.course.course_id,
        ):
            archive = index.archive
            course_id = archive.course.course_id
            source_snapshots.append(
                CourseArchiveSnapshot(
                    course_id=course_id,
                    path=_source_path(index),
                    collected_at=archive.collected_at,
                    schema_version=archive.schema_version,
                )
            )
            state = profile_states.get(course_id)
            assessment_activity_ids: set[str] = set()
            for assessment in archive.assessments.items:
                item = self._assessment_item(
                    index,
                    assessment,
                    profile,
                    state,
                    old_items,
                    feedback,
                    current,
                )
                items.append(item)
                if item.source_activity_id:
                    assessment_activity_ids.add(item.source_activity_id)

            for activity in iter_activities(archive):
                if activity.module_id in assessment_activity_ids:
                    continue
                section_id = index.get_activity_section_id(activity.module_id)
                section = index.get_section(section_id) if section_id else None
                item = self._activity_item(
                    index,
                    activity,
                    section_id=section_id,
                    is_current_section=bool(section and section.current),
                    profile=profile,
                    state=state,
                    old_items=old_items,
                    feedback=feedback,
                    current=current,
                )
                if item is not None:
                    items.append(item)

        items = self._select_key_items(items)
        generated_ids = {item.plan_item_id for item in items}
        removed = sorted(set(old_items) - generated_ids)
        if removed:
            warnings.append(
                "Items that are no longer key priorities were omitted during refresh: "
                + ", ".join(removed)
            )

        items.sort(key=lambda item: self._item_sort_key(item, current))
        workload = self._build_workload_summary(items)
        milestones = self._build_milestones(
            items,
            existing_plan,
            current,
            profile.planning_preferences.deadline_buffer_hours,
        )
        summary = self._build_summary(items, current)
        if profile.profile_status == "incomplete":
            warnings.append(
                "Student Profile is incomplete; priorities use confirmed course "
                "facts and available defaults."
            )
        generated_at = (
            existing_plan.generated_at
            if existing_plan and existing_plan.generated_at
            else current
        )
        return IntegratedPlan(
            plan_id=existing_plan.plan_id if existing_plan else "default",
            planning_mode="priority_backlog",
            generated_at=generated_at,
            updated_at=current,
            timezone=profile.timezone,
            plan_status=(
                "active"
                if profile.profile_status == "active" and items
                else "draft"
            ),
            planning_window=PlanningWindow(start_date=start, end_date=end),
            source_snapshot=SourceSnapshot(
                student_profile_updated_at=profile.updated_at,
                execution_log_updated_at=(execution_log.updated_at if execution_log else None),
                course_archives=source_snapshots,
                warnings=[],
            ),
            capacity_summary=CapacitySummary(
                required_minutes=workload.total_remaining_minutes,
            ),
            workload_summary=workload,
            feedback_summary=FeedbackSummary(
                execution_record_count=feedback.record_count,
                total_actual_minutes=feedback.total_actual_minutes,
                calibration_factors=feedback.calibration_factors,
            ),
            plan_summary=summary,
            items=items,
            timetable=[],
            milestones=milestones,
            review_points=[],
            plan_warnings=list(dict.fromkeys(warnings)),
        )

    def _assessment_item(
        self,
        index: ArchiveIndex,
        assessment: AssessmentItem,
        profile: StudentProfile,
        state: CourseState | None,
        old_items: dict[str, PlanItem],
        feedback: FeedbackIndex,
        current: datetime,
    ) -> PlanItem:
        archive = index.archive
        item_id = f"assessment:{archive.course.course_id}:{assessment.assessment_id}"
        old = old_items.get(item_id)
        activity_id = next(
            (
                source.activity_id
                for source in assessment.sources
                if source.activity_id
                and (activity := index.get_activity(source.activity_id)) is not None
                and activity.category in {"assignment", "quiz"}
            ),
            None,
        )
        section_id = (
            index.get_activity_section_id(activity_id)
            if activity_id
            else next(
                (
                    source.section_id
                    for source in assessment.sources
                    if source.section_id
                ),
                None,
            )
        )
        timing = OfficialTiming(
            opens_on=assessment.opens_on,
            due_on=assessment.due_on,
            scheduled_on=assessment.scheduled_on,
            due_at=assessment.due_at,
            timezone=assessment.timezone,
            is_confirmed=assessment.status == "confirmed",
        )
        importance, importance_reason = _assessment_importance(
            assessment,
            profile,
            archive.course.course_id,
        )
        weak_match = _weak_topic_match(assessment.title, state)
        difficulty, difficulty_reason = _assessment_difficulty(
            assessment,
            weak_match,
        )
        item_type = _assessment_item_type(assessment)
        base_total, basis = _assessment_effort(assessment, profile)
        total, factor, extended = feedback.estimate_for_item(
            item_type,
            item_id,
            base_total,
        )
        if factor != 1.0:
            basis.append(f"Execution history calibration factor: {factor:.2f}x.")
        if extended:
            basis.append(
                "Previous estimate was consumed before completion; added a 25% "
                "continuation allowance."
            )
        completed = max(
            old.effort.completed_minutes if old else 0,
            feedback.progress_minutes(item_id),
        )
        status = old.status if old else "not_started"
        if feedback.progress_minutes(item_id) > 0 and status == "not_started":
            status = "in_progress"
        if feedback.item_completed(item_id):
            status = "completed"
        if state and any(
            result.assessment_id == assessment.assessment_id
            for result in state.known_assessment_results
        ):
            status = "completed"
            completed = max(completed, total)
        if status == "completed":
            completed = max(completed, total)
        readiness = _assessment_readiness(assessment, activity_id, index, current)
        if old is None and readiness in {"missing_material", "prerequisite_missing"}:
            status = "blocked"
        priority = _priority_decision(
            timing,
            importance,
            difficulty,
            max(total - completed, 0),
            readiness,
            current,
            has_warning=bool(index.archive.assessments.warnings),
        )
        warnings = list(index.archive.assessments.warnings)
        if assessment.status == "tentative":
            warnings.append("Assessment data is tentative.")
        if _effective_deadline(timing, current.tzinfo) is None:
            warnings.append("Official deadline is missing.")
        return PlanItem(
            plan_item_id=item_id,
            course_id=archive.course.course_id,
            course_title=archive.course.title,
            source_section_id=section_id,
            source_activity_id=activity_id,
            source_assessment_id=assessment.assessment_id,
            source_assessment_type=assessment.assessment_type,
            item_type=item_type,
            title=assessment.title,
            description=assessment.description,
            official_timing=timing,
            academic_impact=AcademicImpact(
                weight_percent=assessment.weight_percent,
                assessment_group_id=assessment.group_id,
                importance_level=importance,
                importance_rationale=importance_reason,
            ),
            learning_demand=LearningDemand(
                difficulty_level=difficulty,
                difficulty_rationale=difficulty_reason,
                prerequisite_item_ids=(
                    old.learning_demand.prerequisite_item_ids if old else []
                ),
                weak_topic_match=weak_match,
            ),
            effort=EffortEstimate(
                estimated_total_minutes=total,
                completed_minutes=completed,
                remaining_minutes=max(total - completed, 0),
                effort_band=_effort_band(total),
                actual_minutes_spent=feedback.actual_minutes(item_id),
                calibration_factor=factor,
                estimation_basis=basis,
            ),
            priority=priority,
            status=status,
            readiness=readiness,
            completion_criteria=(
                assessment.requirements
                or [f"Complete and verify {assessment.title} requirements"]
            ),
            source_references=[
                _plan_source_reference(source) for source in assessment.sources
            ]
            or [
                PlanSourceReference(
                    source_type="course_archive",
                    relative_path=_source_path(index),
                    assessment_id=assessment.assessment_id,
                )
            ],
            warnings=list(dict.fromkeys(warnings)),
            created_at=old.created_at if old else current,
            updated_at=current,
        )

    def _activity_item(
        self,
        index: ArchiveIndex,
        activity: CourseActivity,
        *,
        section_id: str | None,
        is_current_section: bool,
        profile: StudentProfile,
        state: CourseState | None,
        old_items: dict[str, PlanItem],
        feedback: FeedbackIndex,
        current: datetime,
    ) -> PlanItem | None:
        if activity.category in {"announcement", "url"}:
            return None
        if activity.category == "other" and not activity.files:
            return None
        archive = index.archive
        item_id = f"activity:{archive.course.course_id}:{activity.module_id}"
        old = old_items.get(item_id)
        timing = _activity_timing(activity, profile.timezone)
        item_type = _activity_item_type(activity)
        importance = _activity_importance(activity, is_current_section, profile, archive.course.course_id)
        importance_reason = (
            "Current teaching section."
            if is_current_section
            else f"{activity.category} course activity."
        )
        weak_match = _weak_topic_match(activity.name, state)
        base_total, basis = _activity_effort(activity, profile)
        total, factor, extended = feedback.estimate_for_item(
            item_type,
            item_id,
            base_total,
        )
        if factor != 1.0:
            basis.append(f"Execution history calibration factor: {factor:.2f}x.")
        if extended:
            basis.append(
                "Previous estimate was consumed before completion; added a 25% "
                "continuation allowance."
            )
        completed = max(
            old.effort.completed_minutes if old else 0,
            feedback.progress_minutes(item_id),
        )
        status = old.status if old else "not_started"
        if feedback.progress_minutes(item_id) > 0 and status == "not_started":
            status = "in_progress"
        if feedback.item_completed(item_id):
            status = "completed"
        if state and activity.module_id in state.completed_activity_ids:
            status = "completed"
            completed = max(completed, total)
        if status == "completed":
            completed = max(completed, total)
        difficulty = _activity_difficulty(activity, total, weak_match)
        readiness = _activity_readiness(activity, timing, current)
        if old is None and readiness in {"missing_material", "prerequisite_missing"}:
            status = "blocked"
        priority = _priority_decision(
            timing,
            importance,
            difficulty,
            max(total - completed, 0),
            readiness,
            current,
            has_warning=activity.download_status == "failed",
            current_section=is_current_section,
        )
        warnings: list[str] = []
        if activity.download_error:
            warnings.append(activity.download_error)
        for stored_file in activity.files:
            if stored_file.analysis:
                warnings.extend(stored_file.analysis.warnings)
                if stored_file.analysis.ocr_required:
                    warnings.append(f"OCR required for {stored_file.filename}.")
        if _effective_deadline(timing, current.tzinfo) is None and activity.category in {
            "assignment",
            "quiz",
        }:
            warnings.append("Official deadline is missing.")
        return PlanItem(
            plan_item_id=item_id,
            course_id=archive.course.course_id,
            course_title=archive.course.title,
            source_section_id=section_id,
            source_activity_id=activity.module_id,
            item_type=item_type,
            title=activity.name,
            official_timing=timing,
            academic_impact=AcademicImpact(
                importance_level=importance,
                importance_rationale=importance_reason,
            ),
            learning_demand=LearningDemand(
                difficulty_level=difficulty,
                difficulty_rationale=(
                    "Difficulty inferred from activity type, material volume, "
                    "and Student Profile weak-topic matches."
                ),
                prerequisite_item_ids=(
                    old.learning_demand.prerequisite_item_ids if old else []
                ),
                weak_topic_match=weak_match,
            ),
            effort=EffortEstimate(
                estimated_total_minutes=total,
                completed_minutes=completed,
                remaining_minutes=max(total - completed, 0),
                effort_band=_effort_band(total),
                actual_minutes_spent=feedback.actual_minutes(item_id),
                calibration_factor=factor,
                estimation_basis=basis,
            ),
            priority=priority,
            status=status,
            readiness=readiness,
            completion_criteria=[_activity_completion_criterion(activity)],
            source_references=[
                PlanSourceReference(
                    source_type="moodle_activity",
                    relative_path=_source_path(index),
                    section_id=section_id,
                    activity_id=activity.module_id,
                )
            ],
            warnings=list(dict.fromkeys(warnings)),
            created_at=old.created_at if old else current,
            updated_at=current,
        )

    def _item_sort_key(self, item: PlanItem, current: datetime):
        deadline = _effective_deadline(item.official_timing, current.tzinfo)
        return (
            PRIORITY_RANK[item.priority.level],
            deadline or datetime.max.replace(tzinfo=current.tzinfo),
            -item.academic_impact.importance_level,
            -item.learning_demand.difficulty_level,
            item.course_id,
            item.title.casefold(),
        )

    def _select_key_items(self, items: list[PlanItem]) -> list[PlanItem]:
        """Keep current assessments and actionable supporting work only."""
        selected = [
            item
            for item in items
            if item.status not in {"completed", "cancelled"}
            and (
                item.source_assessment_id is not None
                or item.priority.level != "planned"
                or item.status == "blocked"
            )
        ]
        selected_ids = {item.plan_item_id for item in selected}
        dependencies = {
            dependency
            for item in selected
            for dependency in item.learning_demand.prerequisite_item_ids
        }
        if dependencies - selected_ids:
            selected.extend(
                item
                for item in items
                if item.plan_item_id in dependencies - selected_ids
                and item.status not in {"completed", "cancelled"}
            )
        return selected

    def _build_workload_summary(self, items: list[PlanItem]) -> WorkloadSummary:
        estimated = [
            item
            for item in items
            if item.effort.remaining_minutes is not None
        ]

        def minutes(level: str) -> int:
            return sum(
                item.effort.remaining_minutes or 0
                for item in estimated
                if item.priority.level == level
            )

        return WorkloadSummary(
            key_item_count=len(items),
            estimated_item_count=len(estimated),
            unestimated_item_count=len(items) - len(estimated),
            total_remaining_minutes=sum(
                item.effort.remaining_minutes or 0 for item in estimated
            ),
            critical_minutes=minutes("critical"),
            high_priority_minutes=minutes("high"),
            medium_priority_minutes=minutes("medium"),
            planned_minutes=minutes("planned"),
        )

    def _build_milestones(
        self,
        items: list[PlanItem],
        existing: IntegratedPlan | None,
        current: datetime,
        buffer_hours: int,
    ) -> list[Milestone]:
        current_item_ids = {item.plan_item_id for item in items}
        completed = {
            milestone.milestone_id: milestone
            for milestone in (existing.milestones if existing else [])
            if milestone.status == "completed"
            and milestone.plan_item_id in current_item_ids
        }
        milestones: list[Milestone] = list(completed.values())
        for item in items:
            if (
                item.item_type not in {"assessment", "exam", "quiz", "project"}
                or item.status in {"completed", "cancelled"}
            ):
                continue
            due = _effective_deadline(item.official_timing, current.tzinfo)
            if due is None or due <= current:
                continue
            final_target = due - timedelta(hours=buffer_hours)
            if final_target <= current:
                continue
            opening = item.official_timing.opens_at
            if opening is None and item.official_timing.opens_on is not None:
                opening = datetime.combine(
                    item.official_timing.opens_on,
                    Time.min,
                    tzinfo=current.tzinfo,
                )
            elif opening is not None:
                opening = (
                    opening.replace(tzinfo=current.tzinfo)
                    if opening.tzinfo is None
                    else opening.astimezone(current.tzinfo)
                )
            created_at = (
                item.created_at.replace(tzinfo=current.tzinfo)
                if item.created_at.tzinfo is None
                else item.created_at.astimezone(current.tzinfo)
            )
            start = min(max(opening or created_at, created_at), final_target)
            strategy_name = {
                "report": "essay",
                "argument_analysis": "essay",
                "news_report": "essay",
            }.get(item.source_assessment_type or "", item.source_assessment_type or "")
            if strategy_name not in MILESTONE_STRATEGIES:
                strategy_name = "default"
            strategy = MILESTONE_STRATEGIES[strategy_name]
            duration = final_target - start
            for sequence, (phase, title, fraction) in enumerate(strategy, start=1):
                milestone_id = f"milestone:{item.plan_item_id}:{phase}"
                if milestone_id in completed:
                    continue
                target = start + duration * fraction
                milestones.append(
                    Milestone(
                        milestone_id=milestone_id,
                        plan_item_id=item.plan_item_id,
                        title=title.format(title=item.title),
                        target_at=target,
                        phase=phase,
                        sequence=sequence,
                        total_stages=len(strategy),
                    )
                )
        milestones.sort(key=lambda milestone: milestone.target_at)
        return milestones

    def _build_summary(
        self,
        items: list[PlanItem],
        current: datetime,
    ) -> PlanSummary:
        active = [item for item in items if item.status not in {"completed", "cancelled"}]
        overdue = [
            item
            for item in active
            if (deadline := _effective_deadline(item.official_timing, current.tzinfo))
            and deadline < current
        ]
        ready = [item for item in active if item.readiness == "ready"]
        next_item = (ready or active)[0].plan_item_id if active else None
        return PlanSummary(
            critical_item_count=sum(item.priority.level == "critical" for item in active),
            high_priority_item_count=sum(item.priority.level == "high" for item in active),
            overdue_item_count=len(overdue),
            blocked_item_count=sum(item.status == "blocked" for item in active),
            items_missing_deadline=sum(
                _effective_deadline(item.official_timing, current.tzinfo) is None
                for item in active
                if item.item_type in {"assessment", "exam", "quiz", "project"}
            ),
            items_missing_effort_estimate=sum(
                item.effort.estimated_total_minutes is None for item in active
            ),
            next_action_item_id=next_item,
            summary=(
                f"{len(active)} active item(s); {len(overdue)} overdue; "
                f"{sum(item.priority.level == 'critical' for item in active)} critical."
            ),
        )
