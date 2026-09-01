"""Deterministic rules for timing, effort, difficulty, and priority."""

from __future__ import annotations

import re
from datetime import datetime, time as Time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from moodle_collector.contracts import (
    AssessmentItem,
    ArchiveIndex,
    CourseActivity,
    SourceReference,
)
from .plan_schema import OfficialTiming, PlanSourceReference, PriorityDecision
from .profile_schema import CourseState, StudentProfile


PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "planned": 3}


def source_path(index: ArchiveIndex) -> str:
    if index.source_path is None:
        return f"courses/{index.archive.course.course_id}/course.json"
    path = index.source_path
    parts = path.parts
    if "resources" in parts:
        return Path(*parts[parts.index("resources") + 1:]).as_posix()
    return path.as_posix()


def assessment_item_type(assessment: AssessmentItem) -> str:
    if assessment.assessment_type == "exam":
        return "exam"
    if assessment.assessment_type == "quiz":
        return "quiz"
    if assessment.assessment_type == "project":
        return "project"
    return "assessment"


def activity_item_type(activity: CourseActivity) -> str:
    if activity.category == "quiz":
        return "quiz"
    if activity.category == "assignment":
        return "assessment"
    if activity.category == "forum":
        return "practice"
    if activity.module in {"resource", "book", "page", "folder"}:
        name = activity.name.casefold()
        return (
            "lecture"
            if any(word in name for word in ("lecture", "slide"))
            else "reading"
        )
    return "other"


def assessment_importance(
    assessment: AssessmentItem,
    profile: StudentProfile,
    course_id: str,
) -> tuple[int, str]:
    weight = assessment.weight_percent
    if assessment.bonus_percent is not None:
        level = 2
        reason = f"Optional bonus opportunity worth up to {assessment.bonus_percent:g} points."
    elif weight is None:
        level = 3
        reason = "Assessment weight is unknown; using neutral importance."
    elif weight >= 30:
        level, reason = 5, f"Major assessment worth {weight:g}%."
    elif weight >= 15:
        level, reason = 4, f"High-impact assessment worth {weight:g}%."
    elif weight >= 5:
        level, reason = 3, f"Required assessment worth {weight:g}%."
    else:
        level, reason = 2, f"Low-weight assessment worth {weight:g}%."
    if _course_priority(profile, course_id) in {"high", "critical"}:
        level = min(level + 1, 5)
        reason += " Student Profile marks this course as a priority."
    return level, reason


def activity_importance(
    activity: CourseActivity,
    current_section: bool,
    profile: StudentProfile,
    course_id: str,
) -> int:
    level = {
        "assignment": 4,
        "quiz": 4,
        "forum": 2,
        "resource": 2,
        "other": 1,
    }.get(activity.category, 2)
    if current_section:
        level = min(level + 1, 5)
    if _course_priority(profile, course_id) in {"high", "critical"}:
        level = min(level + 1, 5)
    return level


def _course_priority(profile: StudentProfile, course_id: str) -> str:
    if course_id in profile.academic_goals.priority_course_ids:
        return "high"
    for target in profile.academic_goals.course_targets:
        if target.course_id == course_id:
            return target.priority
    return "medium"


def assessment_difficulty(
    assessment: AssessmentItem,
    weak_match: bool | None,
) -> tuple[int, str]:
    level = {
        "exam": 4,
        "project": 4,
        "essay": 4,
        "report": 4,
        "presentation": 3,
        "argument_analysis": 3,
        "news_report": 3,
        "assignment": 3,
        "quiz": 3,
        "lab": 3,
        "reflection": 2,
        "participation": 2,
        "lecture_response": 2,
        "other": 3,
    }[assessment.assessment_type]
    reasons = [f"Default difficulty for {assessment.assessment_type} work."]
    if assessment.word_limit and assessment.word_limit >= 2000:
        level = min(level + 1, 5)
        reasons.append(f"Long-form requirement: {assessment.word_limit} words.")
    if weak_match:
        level = min(level + 1, 5)
        reasons.append("Matches a Student Profile difficulty.")
    return level, " ".join(reasons)


def activity_difficulty(
    activity: CourseActivity,
    total_minutes: int,
    weak_match: bool | None,
) -> int:
    level = 3 if activity.category in {"assignment", "quiz"} else 2
    if total_minutes > 240:
        level = max(level, 4)
    elif total_minutes > 90:
        level = max(level, 3)
    if weak_match:
        level = min(level + 1, 5)
    return level


def assessment_effort(
    assessment: AssessmentItem,
    profile: StudentProfile,
) -> tuple[int, list[str]]:
    defaults = {
        "participation": 60,
        "lecture_response": 120,
        "argument_analysis": 240,
        "quiz": 120,
        "news_report": 240,
        "essay": 480,
        "assignment": 240,
        "exam": 600,
        "presentation": 360,
        "project": 720,
        "report": 480,
        "reflection": 180,
        "lab": 180,
        "other": 180,
    }
    total = defaults[assessment.assessment_type]
    basis = [f"Default estimate for {assessment.assessment_type} work."]
    if assessment.word_limit:
        speed = profile.study_capacity.writing_speed_words_per_hour or 250
        writing_minutes = round(assessment.word_limit / speed * 60 * 2.5)
        total = max(total, writing_minutes)
        basis = [
            f"{assessment.word_limit} words at {speed} words/hour with 2.5x "
            "research, drafting, and revision allowance."
        ]
    return total, basis


def activity_effort(
    activity: CourseActivity,
    profile: StudentProfile,
) -> tuple[int, list[str]]:
    analyses = [file.analysis for file in activity.files if file.analysis]
    if analyses:
        profile_wpm = profile.study_capacity.reading_speed_words_per_minute
        if profile_wpm:
            words = sum(analysis.word_count for analysis in analyses)
            minutes = max(round(words / profile_wpm), 1)
            return minutes, [
                f"{words} extracted words at {profile_wpm} words/minute."
            ]
        minutes = sum(analysis.estimated_reading_minutes for analysis in analyses)
        return max(minutes, 1), ["PDF analysis estimate at 200 words/minute."]
    defaults = {
        "assignment": 240,
        "quiz": 120,
        "forum": 45,
        "resource": 60,
        "other": 45,
    }
    return defaults.get(activity.category, 60), [
        f"Default estimate for {activity.category} activity; no measured text workload."
    ]


def assessment_readiness(
    assessment: AssessmentItem,
    activity_id: str | None,
    index: ArchiveIndex,
    current: datetime,
) -> str:
    if assessment.opens_on and current.date() < assessment.opens_on:
        return "not_open"
    if activity_id:
        activity = index.get_activity(activity_id)
        if activity:
            if not (
                activity.visible
                and activity.user_visible
                and activity.access_visible
            ):
                return "not_open"
            if activity.download_status == "failed":
                return "missing_material"
            if activity.has_restrictions:
                return "uncertain"
    return "ready"


def activity_readiness(
    activity: CourseActivity,
    timing: OfficialTiming,
    current: datetime,
) -> str:
    if not (activity.visible and activity.user_visible and activity.access_visible):
        return "not_open"
    if timing.opens_at and current < timing.opens_at.astimezone(current.tzinfo):
        return "not_open"
    if activity.download_status == "failed":
        return "missing_material"
    if activity.has_restrictions:
        return "uncertain"
    return "ready"


def priority_decision(
    timing: OfficialTiming,
    importance: int,
    difficulty: int,
    remaining_minutes: int,
    readiness: str,
    current: datetime,
    *,
    has_warning: bool,
    current_section: bool = False,
) -> PriorityDecision:
    deadline = effective_deadline(timing, current.tzinfo)
    reasons: list[str] = []
    derived = ["importance", "difficulty", "remaining_effort", "readiness"]
    if deadline:
        days = (deadline - current).total_seconds() / 86_400
        derived.append("official_deadline")
        if days < 0:
            level = "critical"
            reasons.append("Official deadline has passed.")
        elif days <= 2:
            level = "critical"
            reasons.append("Official deadline is within 48 hours.")
        elif days <= 7:
            level = "high"
            reasons.append("Official deadline is within 7 days.")
        elif days <= 14:
            level = "medium"
            reasons.append("Official deadline is within 14 days.")
        else:
            level = "planned"
            reasons.append("Official deadline is beyond 14 days.")
    elif current_section:
        level = "medium"
        reasons.append("Activity belongs to the current teaching section.")
    elif importance >= 4 and remaining_minutes:
        level = "medium"
        reasons.append("High-impact task has no confirmed deadline.")
    else:
        level = "planned"
        reasons.append("No confirmed near-term deadline.")

    if importance == 5 and level == "planned":
        level = "high"
        reasons.append("Importance level 5 requires early preparation.")
    elif importance >= 4 and difficulty >= 4 and level == "medium":
        level = "high"
        reasons.append("High impact and difficulty justify early work.")
    if readiness != "ready":
        derived.append("readiness_risk")
        reasons.append(f"Readiness is {readiness}.")
        if (
            readiness in {"missing_material", "prerequisite_missing"}
            and level == "planned"
        ):
            level = "high"
    if has_warning:
        derived.append("data_warning")
        reasons.append("Source data has warnings or missing material.")
    return PriorityDecision(
        level=level,
        rationale=" ".join(reasons),
        derived_from=derived,
    )


def activity_timing(activity: CourseActivity, timezone_name: str) -> OfficialTiming:
    metadata = activity.metadata
    opens = _first_datetime(
        metadata,
        "opens_at",
        "allowsubmissionsfromdate",
        "timeopen",
        timezone_name=timezone_name,
    )
    due = _first_datetime(
        metadata,
        "due_at",
        "duedate",
        "timeclose",
        timezone_name=timezone_name,
    )
    scheduled = _first_datetime(
        metadata,
        "scheduled_at",
        timezone_name=timezone_name,
    )
    return OfficialTiming(
        opens_at=opens,
        due_at=due,
        scheduled_at=scheduled,
        timezone=timezone_name,
        is_confirmed=bool(due or scheduled or opens),
    )


def _first_datetime(
    metadata: dict[str, Any],
    *keys: str,
    timezone_name: str,
) -> datetime | None:
    for key in keys:
        parsed = _parse_datetime(metadata.get(key), timezone_name)
        if parsed is not None:
            return parsed
    return None


def _parse_datetime(value: Any, timezone_name: str) -> datetime | None:
    if value in {None, "", 0, "0"}:
        return None
    zone = ZoneInfo(timezone_name)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).astimezone(zone)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        if re.fullmatch(r"\d{9,}", text):
            return datetime.fromtimestamp(
                int(text), tz=timezone.utc
            ).astimezone(zone)
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=zone)
        return parsed.astimezone(zone)
    return None


def effective_deadline(timing: OfficialTiming, tzinfo) -> datetime | None:
    if timing.due_at:
        return timing.due_at.astimezone(tzinfo)
    if timing.scheduled_at:
        return timing.scheduled_at.astimezone(tzinfo)
    if timing.due_on:
        return datetime.combine(timing.due_on, Time(23, 59), tzinfo=tzinfo)
    if timing.scheduled_on:
        return datetime.combine(timing.scheduled_on, Time(23, 59), tzinfo=tzinfo)
    return None


def weak_topic_match(title: str, state: CourseState | None) -> bool | None:
    if state is None or not state.current_difficulties:
        return None
    lowered = title.casefold()
    return any(
        difficulty.casefold() in lowered
        for difficulty in state.current_difficulties
    )


def plan_source_reference(source: SourceReference) -> PlanSourceReference:
    return PlanSourceReference(
        source_type=source.source_type,
        relative_path=source.relative_path,
        section_id=source.section_id,
        activity_id=source.activity_id,
        page_numbers=source.page_numbers,
        note=source.note,
    )


def effort_band(minutes: int) -> str:
    if minutes <= 30:
        return "xs"
    if minutes <= 90:
        return "s"
    if minutes <= 240:
        return "m"
    if minutes <= 480:
        return "l"
    return "xl"


def activity_completion_criterion(activity: CourseActivity) -> str:
    if activity.category == "quiz":
        return f"Complete {activity.name} and review errors"
    if activity.category == "assignment":
        return f"Complete {activity.name} requirements and submission check"
    if activity.category == "forum":
        return f"Complete the required contribution for {activity.name}"
    return f"Study {activity.name} and record key concepts/questions"
