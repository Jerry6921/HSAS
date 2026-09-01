from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from hsas.domain.courses.index_courses import iter_activities
from hsas.domain.courses.define_courses import CourseActivity, CourseArchive
from .parse_assessment_text import (
    classify_assessment,
    clean_title,
    course_year,
    GENERIC_ASSESSMENT_HEADINGS,
    looks_like_assessment,
    parse_dates,
)
from hsas.domain.courses.define_assessments import AssessmentCandidate, SourceReference


WEIGHTED_LINE = re.compile(
    r"^(?P<title>.+?)\s*(?:--|[-–—:])\s*(?P<weight>\d+(?:\.\d+)?)\s*%\s*$",
    flags=re.IGNORECASE,
)
DETAIL_LINE = re.compile(
    r"^(?P<title>.+?)\s*(?:--|[–—])\s*(?P<detail>.+)$",
    flags=re.IGNORECASE,
)
BONUS_LINE = re.compile(
    r"\+?\s*(?P<bonus>\d+(?:\.\d+)?)\s+bonus\s+(?:percentage\s+)?points?.*?"
    r"(?P<title>class\s+participation|participation)",
    flags=re.IGNORECASE,
)


def _metadata_datetime(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=ZoneInfo("Asia/Hong_Kong"))
            if value.tzinfo is None
            else value
        )
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=ZoneInfo("Asia/Hong_Kong"))
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (
                parsed.replace(tzinfo=ZoneInfo("Asia/Hong_Kong"))
                if parsed.tzinfo is None
                else parsed
            )
        except ValueError:
            return None
    return None


def _structured_dates(metadata: dict[str, Any]) -> dict[str, date | datetime]:
    result: dict[str, date | datetime] = {}
    due = _metadata_datetime(
        metadata.get("due_at")
        or metadata.get("duedate")
        or metadata.get("timeclose")
    )
    opened = _metadata_datetime(
        metadata.get("opens_at")
        or metadata.get("allowsubmissionsfromdate")
        or metadata.get("timeopen")
    )
    scheduled = _metadata_datetime(metadata.get("scheduled_at"))
    if due:
        result["due_at"] = due
    if opened:
        result["opens_on"] = opened.date()
    if scheduled:
        result["scheduled_on"] = scheduled.date()
    return result


def _activity_source(activity: CourseActivity, note: str) -> list[SourceReference]:
    return [
        SourceReference(
            source_type="moodle_activity",
            activity_id=activity.module_id,
            note=note[:500],
        )
    ]


def _content_candidates(
    activity: CourseActivity,
    *,
    year: int,
) -> list[AssessmentCandidate]:
    """Extract generic assessment evidence from rendered labels/text areas."""
    value = activity.metadata.get("content_text")
    if not isinstance(value, str) or not value.strip():
        return []

    candidates: list[AssessmentCandidate] = []
    for raw_line in value.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line:
            continue

        bonus_match = BONUS_LINE.search(line)
        if bonus_match:
            candidates.append(
                AssessmentCandidate(
                    title="Class Participation Bonus",
                    assessment_type="participation",
                    extraction_method="moodle_activity",
                    confidence=0.92,
                    bonus_percent=float(bonus_match.group("bonus")),
                    description=line,
                    visible_in_course=activity.visible and activity.user_visible,
                    sources=_activity_source(activity, line),
                )
            )
            continue

        weight_match = WEIGHTED_LINE.match(line)
        if weight_match:
            title = clean_title(weight_match.group("title"))
            if not looks_like_assessment(title):
                continue
            assessment_type = classify_assessment(title)
            candidates.append(
                AssessmentCandidate(
                    title=title,
                    assessment_type=assessment_type,
                    extraction_method="moodle_activity",
                    confidence=0.92,
                    weight_percent=float(weight_match.group("weight")),
                    description=line,
                    visible_in_course=activity.visible and activity.user_visible,
                    sources=_activity_source(activity, line),
                )
            )
            continue

        detail_match = DETAIL_LINE.match(line)
        if not detail_match:
            continue
        title = clean_title(detail_match.group("title"))
        if not looks_like_assessment(title):
            continue
        assessment_type = classify_assessment(title)
        parsed_dates = parse_dates(
            detail_match.group("detail"),
            year=year,
            assessment_type=assessment_type,
        )
        is_tbd = bool(re.search(r"\bTBD\b|to be determined", line, re.IGNORECASE))
        if not parsed_dates and not is_tbd:
            continue
        candidates.append(
            AssessmentCandidate(
                title=title,
                assessment_type=assessment_type,
                extraction_method="moodle_activity",
                confidence=0.9 if parsed_dates else 0.75,
                description=line,
                requirements=["Official date is TBD"] if is_tbd else [],
                visible_in_course=activity.visible and activity.user_visible,
                sources=_activity_source(activity, line),
                **parsed_dates,
            )
        )
    return candidates


def extract_moodle_candidates(archive: CourseArchive) -> list[AssessmentCandidate]:
    """Extract tentative section items and authoritative activity items."""
    year = course_year(archive)
    candidates: list[AssessmentCandidate] = []

    for section in archive.sections:
        if not looks_like_assessment(section.title):
            continue
        title = clean_title(section.title)
        if title.casefold() in GENERIC_ASSESSMENT_HEADINGS:
            continue
        assessment_type = classify_assessment(title)
        candidates.append(
            AssessmentCandidate(
                title=title,
                assessment_type=assessment_type,
                extraction_method="moodle_section",
                confidence=0.6,
                visible_in_course=section.visible,
                sources=[
                    SourceReference(
                        source_type="moodle_section",
                        section_id=section.section_id,
                        note=section.title,
                    )
                ],
                **parse_dates(
                    section.title,
                    year=year,
                    assessment_type=assessment_type,
                ),
            )
        )

    for activity in iter_activities(archive):
        candidates.extend(_content_candidates(activity, year=year))
        if activity.category not in {"assignment", "quiz"}:
            continue
        title = clean_title(activity.name)
        assessment_type = (
            "quiz" if activity.category == "quiz" else classify_assessment(title)
        )
        if assessment_type == "other":
            assessment_type = "assignment"
        title_dates = parse_dates(
            activity.name,
            year=year,
            assessment_type=assessment_type,
        )
        structured_dates = _structured_dates(activity.metadata)
        assessment_dates = {**title_dates, **structured_dates}
        candidates.append(
            AssessmentCandidate(
                title=title,
                assessment_type=assessment_type,
                extraction_method="moodle_activity",
                confidence=0.95 if structured_dates else 0.82,
                visible_in_course=activity.visible and activity.user_visible,
                sources=[
                    SourceReference(
                        source_type="moodle_activity",
                        activity_id=activity.module_id,
                        note=str(activity.url) if activity.url else activity.name,
                    )
                ],
                **assessment_dates,
            )
        )

    return candidates
