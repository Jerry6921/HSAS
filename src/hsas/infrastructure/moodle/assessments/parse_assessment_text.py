from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from hsas.domain.courses.define_courses import CourseArchive
from hsas.domain.courses.define_assessments import AssessmentType


MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3,
    "march": 3, "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9,
    "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11,
    "november": 11, "dec": 12, "december": 12,
}
MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))
ASSESSMENT_MARKERS = (
    "analysis", "assignment", "assessment", "attendance", "essay", "exam", "final",
    "lab", "midterm", "participation", "portfolio", "presentation",
    "project", "quiz", "reflection", "report", "response", "test",
    "作業", "测验", "測驗", "考試", "考试", "報告", "报告", "演示",
)
GENERIC_ASSESSMENT_HEADINGS = {
    "assessment",
    "assessments",
    "coursework",
    "grading",
    "grade",
}


def course_year(archive: CourseArchive) -> int:
    match = re.search(r"\b(20\d{2})\b", archive.course.title)
    return int(match.group(1)) if match else archive.collected_at.year


def classify_assessment(title: str) -> AssessmentType:
    lowered = title.casefold()
    if "participation" in lowered or "attendance" in lowered:
        return "participation"
    if "lecture response" in lowered:
        return "lecture_response"
    if "argument analysis" in lowered:
        return "argument_analysis"
    if "news report" in lowered:
        return "news_report"
    if "quiz" in lowered or "測驗" in title or "测验" in title:
        return "quiz"
    if (
        "exam" in lowered
        or "examination" in lowered
        or "midterm" in lowered
        or re.search(r"\btest\b", lowered)
        or "考試" in title
        or "考试" in title
    ):
        return "exam"
    if "presentation" in lowered or "演示" in title:
        return "presentation"
    if "project" in lowered:
        return "project"
    if "reflection" in lowered or "reflective" in lowered:
        return "reflection"
    if "lab" in lowered:
        return "lab"
    if "essay" in lowered or re.search(r"\bpaper\b", lowered):
        return "essay"
    if "report" in lowered or "報告" in title or "报告" in title:
        return "report"
    if "assignment" in lowered or "作業" in title:
        return "assignment"
    return "other"


def looks_like_assessment(title: str) -> bool:
    lowered = title.casefold()
    return any(marker in lowered or marker in title for marker in ASSESSMENT_MARKERS)


def clean_title(title: str) -> str:
    title = re.sub(r"^\s*\d+\s*[.)]\s*", "", title).strip()
    title = re.sub(
        r"\s*\((?:[^)]*(?:%|due|submission|\d{1,2}\s+(?:"
        + MONTH_PATTERN
        + r"))[^)]*)\)\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    title = re.sub(
        r"\b\d+\s+(assignments?|quizzes?|tests?|essays?|papers?|reports?|"
        r"presentations?|projects?)\b",
        r"\1",
        title,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", title).strip(" :-–")


def normalized_title(title: str) -> str:
    value = clean_title(title).casefold()
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _make_date(year: int, day: str, month: str) -> date | None:
    try:
        return date(year, MONTHS[month.casefold()], int(day))
    except (KeyError, ValueError):
        return None


def parse_dates(
    value: str,
    *,
    year: int,
    assessment_type: AssessmentType,
) -> dict[str, date | datetime]:
    result: dict[str, date | datetime] = {}
    range_match = re.search(
        rf"(\d{{1,2}})\s+({MONTH_PATTERN})\s*[-–—]\s*(\d{{1,2}})\s+({MONTH_PATTERN})",
        value,
        flags=re.IGNORECASE,
    )
    if range_match:
        opened = _make_date(year, range_match.group(1), range_match.group(2))
        due = _make_date(year, range_match.group(3), range_match.group(4))
        if opened:
            result["opens_on"] = opened
        if due:
            result["due_on"] = due
        return result

    timed = re.search(
        rf"(\d{{1,2}})\s+({MONTH_PATTERN})(?:\s+20\d{{2}})?(?:\s+at)?\s+(\d{{1,2}})[:.]([0-5]\d)",
        value,
        flags=re.IGNORECASE,
    )
    if timed:
        day = _make_date(year, timed.group(1), timed.group(2))
        if day:
            timestamp = datetime(
                day.year,
                day.month,
                day.day,
                int(timed.group(3)),
                int(timed.group(4)),
                tzinfo=ZoneInfo("Asia/Hong_Kong"),
            )
            if assessment_type in {"quiz", "exam"}:
                result["scheduled_on"] = day
            else:
                result["due_at"] = timestamp
        return result

    month_first_timed = re.search(
        rf"({MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?"
        rf"(?:,?\s+20\d{{2}})?(?:\s+at)?\s+(\d{{1,2}})[:.]([0-5]\d)",
        value,
        flags=re.IGNORECASE,
    )
    if month_first_timed:
        day = _make_date(year, month_first_timed.group(2), month_first_timed.group(1))
        if day:
            timestamp = datetime(
                day.year,
                day.month,
                day.day,
                int(month_first_timed.group(3)),
                int(month_first_timed.group(4)),
                tzinfo=ZoneInfo("Asia/Hong_Kong"),
            )
            if assessment_type in {"quiz", "exam"}:
                result["scheduled_on"] = day
            else:
                result["due_at"] = timestamp
        return result

    dated = re.search(
        rf"(\d{{1,2}})\s+({MONTH_PATTERN})(?:\s+20\d{{2}})?",
        value,
        flags=re.IGNORECASE,
    )
    if dated:
        day = _make_date(year, dated.group(1), dated.group(2))
        if day:
            key = "scheduled_on" if assessment_type in {"quiz", "exam"} else "due_on"
            result[key] = day
        return result

    month_first = re.search(
        rf"({MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+20\d{{2}})?",
        value,
        flags=re.IGNORECASE,
    )
    if month_first:
        day = _make_date(year, month_first.group(2), month_first.group(1))
        if day:
            key = "scheduled_on" if assessment_type in {"quiz", "exam"} else "due_on"
            result[key] = day
    return result


def page_map(text: str) -> dict[int, str]:
    matches = list(re.finditer(r"--- Page (\d+) ---\n", text))
    if not matches:
        return {1: text}
    pages: dict[int, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages[int(match.group(1))] = text[start:end]
    return pages


def pages_containing(pages: dict[int, str], *terms: str) -> list[int]:
    lowered_terms = [term.casefold() for term in terms if term]
    return [
        number
        for number, text in pages.items()
        if any(term in text.casefold() for term in lowered_terms)
    ]
