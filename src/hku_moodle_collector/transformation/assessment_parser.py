from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .archive_index import ArchiveIndex
from .models import (
    AssessmentGroup,
    AssessmentItem,
    AssessmentOverview,
    CourseArchive,
    SourceReference,
)
from ..storage.json_store import safe_filename


MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3,
    "march": 3, "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9,
    "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11,
    "november": 11, "dec": 12, "december": 12,
}
ASSESSMENT_MARKERS = (
    "response", "analysis", "quiz", "report", "essay", "assignment",
    "participation",
)


def _course_year(archive: CourseArchive) -> int:
    match = re.search(r"\b(20\d{2})\b", archive.course.title)
    return int(match.group(1)) if match else archive.collected_at.year


def _assessment_type(title: str) -> str:
    lowered = title.casefold()
    if "participation" in lowered:
        return "participation"
    if "lecture response" in lowered:
        return "lecture_response"
    if "argument analysis" in lowered:
        return "argument_analysis"
    if "quiz" in lowered:
        return "quiz"
    if "news report" in lowered:
        return "news_report"
    if "essay" in lowered:
        return "essay"
    return "other"


def _clean_title(title: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()


def _date(year: int, day: str, month: str) -> date:
    return date(year, MONTHS[month.casefold()], int(day))


def _apply_dates(item: AssessmentItem, title: str, year: int) -> None:
    range_match = re.search(
        r"(\d{1,2})\s+([A-Za-z]+)\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)",
        title,
    )
    if range_match:
        item.opens_on = _date(year, range_match.group(1), range_match.group(2))
        item.due_on = _date(year, range_match.group(3), range_match.group(4))
        return

    timed = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{1,2}):(\d{2})", title)
    if timed:
        day = _date(year, timed.group(1), timed.group(2))
        value = datetime(
            day.year,
            day.month,
            day.day,
            int(timed.group(3)),
            int(timed.group(4)),
            tzinfo=ZoneInfo("Asia/Hong_Kong"),
        )
        if item.assessment_type == "quiz":
            item.scheduled_on = day
        else:
            item.due_at = value
        return


    dated = re.search(r"(\d{1,2})\s+([A-Za-z]+)", title)
    if dated:
        value = _date(year, dated.group(1), dated.group(2))
        if item.assessment_type == "quiz":
            item.scheduled_on = value
        else:
            item.due_on = value


def _page_map(text: str) -> dict[int, str]:
    matches = list(re.finditer(r"--- Page (\d+) ---\n", text))
    if not matches:
        return {1: text}
    pages: dict[int, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages[int(match.group(1))] = text[start:end]
    return pages


def _pages_containing(pages: dict[int, str], *terms: str) -> list[int]:
    lowered_terms = [term.casefold() for term in terms]
    return [
        page_number
        for page_number, text in pages.items()
        if any(term in text.casefold() for term in lowered_terms)
    ]


def _syllabus_source(
    relative_path: str, pages: dict[int, str], *terms: str
) -> SourceReference:
    return SourceReference(
        source_type="syllabus",
        relative_path=relative_path,
        page_numbers=_pages_containing(pages, *terms),
    )


def _section_items(archive: CourseArchive) -> list[AssessmentItem]:
    year = _course_year(archive)
    items: list[AssessmentItem] = []
    for section in archive.sections:
        lowered = section.title.casefold()
        if not any(marker in lowered for marker in ASSESSMENT_MARKERS):
            continue
        title = _clean_title(section.title)
        item = AssessmentItem(
            assessment_id=safe_filename(title).casefold(),
            title=title,
            assessment_type=_assessment_type(title),
            visible_in_course=section.visible,
            status="tentative",
            sources=[
                SourceReference(
                    source_type="moodle_section",
                    section_id=section.section_id,
                    note=section.title,
                )
            ],
        )
        _apply_dates(item, section.title, year)
        items.append(item)
    return items


def build_assessment_overview(
    archive: CourseArchive,
    *,
    storage_root: Path,
) -> AssessmentOverview:
    items = _section_items(archive)
    syllabus_location = ArchiveIndex(archive).find_document(role="syllabus")
    syllabus = syllabus_location.stored_file if syllabus_location else None
    if not syllabus or not syllabus.analysis or not syllabus.analysis.extracted_text_path:
        return AssessmentOverview(
            items=items,
            warnings=["Syllabus text was unavailable; assessment details are tentative."],
        )

    text_path = storage_root / syllabus.analysis.extracted_text_path
    text = text_path.read_text(encoding="utf-8")
    pages = _page_map(text)
    lowered = text.casefold()
    source_path = syllabus.relative_path

    groups = [
        AssessmentGroup(
            group_id="lecture-responses",
            title="Lecture Responses",
            weight_percent=20,
            description="Two short lecture responses, worth 10% each.",
            sources=[_syllabus_source(source_path, pages, "Lecture Responses")],
        ),
        AssessmentGroup(
            group_id="writing-portfolio",
            title="Writing Portfolio",
            weight_percent=25,
            description="Argument analysis (15%) and news report (10%).",
            sources=[_syllabus_source(source_path, pages, "Writing Portfolio")],
        ),
    ]

    tutorial = AssessmentItem(
        assessment_id="tutorial-participation",
        title="Tutorial Participation",
        assessment_type="participation",
        weight_percent=15,
        description="Tutorial attendance and substantive participation.",
        requirements=[
            "Attend tutorials.",
            "Make substantive contributions to tutorial discussions.",
        ],
        visible_in_course=True,
        status="confirmed",
        sources=[_syllabus_source(source_path, pages, "Tutorial participation")],
    )
    items.insert(0, tutorial)

    for item in items:
        title = item.title.casefold()
        terms = [item.title]
        if item.assessment_type == "lecture_response":
            item.group_id = "lecture-responses"
            item.weight_percent = 10
            item.word_limit = 400
            item.description = "Short response to a selected lecture."
            item.requirements = [
                "Summarize the lecture content.",
                "Discuss the points that were most interesting.",
                "State the questions left after the lecture.",
            ]
            terms = ["Lecture Responses", "lecture response submission period"]
        elif item.assessment_type == "argument_analysis":
            item.group_id = "writing-portfolio"
            item.weight_percent = 15
            item.word_limit = 600
            item.description = "Analyze a central argument in one assigned reading."
            item.requirements = [
                "Choose an assigned reading.",
                "Identify and concisely summarize a central argument.",
                "Evaluate the argument's strengths and/or weaknesses.",
            ]
            terms = ["argument analysis"]
        elif item.assessment_type == "quiz":
            item.weight_percent = 15
            item.description = "In-class online multiple-choice quiz on weeks 1-6."
            item.requirements = ["Review course material from the first six weeks."]
            terms = ["Midterm Quiz", "midterm quiz"]
        elif item.assessment_type == "news_report":
            item.group_id = "writing-portfolio"
            item.weight_percent = 10
            item.word_limit = 300
            item.description = "Connect a recent news article with an assigned reading."
            item.requirements = [
                "Use a relevant news article published within the last year.",
                "Summarize the article in your own words.",
                "Explain its relevance to an assigned reading.",
                "Discuss the philosophical issues or questions it raises.",
            ]
            terms = ["news report"]
        elif item.assessment_type == "essay":
            item.weight_percent = 25
            item.word_limit = 1000
            item.description = "Final essay based on a provided list of topics."
            item.requirements = ["Select a topic from the list provided by the course."]
            terms = ["Final Essay", "final essay due"]

        if item.assessment_type != "participation":
            confirmed = any(term.casefold() in lowered for term in terms)
            if confirmed:
                item.status = "confirmed"
                item.sources.append(_syllabus_source(source_path, pages, *terms))

    policies: list[str] = []
    if "loss of 25% for each day" in lowered:
        policies.append(
            "Late work requires a legitimate reason; otherwise 25% is deducted per day."
        )
    if "tutorial attendance is mandatory" in lowered:
        policies.append("Tutorial attendance is mandatory.")
    if "generative ai" in lowered and "acknowledgment" in lowered:
        policies.append(
            "Any generative-AI assistance must be acknowledged with the tool and usage described."
        )

    item_total = sum(item.weight_percent or 0 for item in items)
    warnings: list[str] = []
    if abs(item_total - 100) > 0.01:
        warnings.append(f"Assessment item weights sum to {item_total:g}%, not 100%.")

    return AssessmentOverview(
        grading_basis="100% Coursework" if "100% coursework" in lowered else None,
        total_weight_percent=item_total,
        groups=groups,
        items=items,
        policies=policies,
        warnings=warnings,
    )
