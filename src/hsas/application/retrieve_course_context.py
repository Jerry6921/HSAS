"""Build a local, cited retrieval context for course-information questions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re

from pydantic import Field

from hsas.application.retrieve_materials import MaterialSearchResult, search_materials
from hsas.domain.courses import StrictModel
from hsas.domain.information import CourseRecord, InformationItem, InformationStore


WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[\u3400-\u9fff]+")


class CourseFactHit(StrictModel):
    """One relevant course-wide record from the canonical information store."""

    score: float = Field(ge=0)
    course: CourseRecord


class InformationItemHit(StrictModel):
    """One relevant timetable or assessment record with its stored evidence."""

    score: float = Field(ge=0)
    item: InformationItem


class CourseQuestionContext(StrictModel):
    """Evidence packet consumed by an AI; it is not itself an AI answer."""

    question: str
    generated_at: datetime
    timezone: str
    information_updated_at: datetime | None = None
    selected_course_ids: list[str] = Field(default_factory=list)
    course_facts: list[CourseFactHit] = Field(default_factory=list)
    information_items: list[InformationItemHit] = Field(default_factory=list)
    material_evidence: MaterialSearchResult
    warnings: list[str] = Field(default_factory=list)


def build_course_question_context(
    resources_dir: Path,
    question: str,
    *,
    information: InformationStore | None,
    course_ids: set[str] | None = None,
    material_limit: int = 6,
    item_limit: int = 20,
) -> CourseQuestionContext:
    """Retrieve structured facts and source excerpts without calling an LLM."""
    normalized_question = question.strip()
    tokens = _tokenize(normalized_question)
    if not tokens:
        raise ValueError("course question must contain searchable text")
    if item_limit < 1 or item_limit > 100:
        raise ValueError("information item limit must be between 1 and 100")

    selected = set(course_ids or [])
    warnings: list[str] = []
    if information is None:
        warnings.append(
            "information.json is unavailable; the packet contains material excerpts only"
        )
        courses: list[CourseRecord] = []
        items: list[InformationItem] = []
        timezone = "Asia/Hong_Kong"
        information_updated_at = None
    else:
        courses = [
            course
            for course in information.courses
            if not selected or course.course_id in selected
        ]
        items = [
            item
            for item in information.items
            if not selected or item.course_id in selected
        ]
        timezone = information.timezone
        information_updated_at = information.updated_at
        known_ids = {course.course_id for course in information.courses}
        missing_ids = sorted(selected - known_ids)
        if missing_ids:
            warnings.append(
                "selected course IDs are absent from information.json: "
                + ", ".join(missing_ids)
            )

    course_hits = _rank_courses(courses, tokens, normalized_question, selected)
    item_hits = _rank_items(items, tokens, normalized_question, selected)[:item_limit]
    materials = search_materials(
        resources_dir,
        normalized_question,
        course_ids=selected or None,
        limit=material_limit,
    )
    if not materials.hits:
        warnings.append(
            "no matching extracted material text was found; do not infer missing course content"
        )

    return CourseQuestionContext(
        question=normalized_question,
        generated_at=datetime.now(UTC),
        timezone=timezone,
        information_updated_at=information_updated_at,
        selected_course_ids=sorted(selected),
        course_facts=course_hits,
        information_items=item_hits,
        material_evidence=materials,
        warnings=warnings,
    )


def _rank_courses(
    courses: list[CourseRecord],
    tokens: list[str],
    raw_question: str,
    selected: set[str],
) -> list[CourseFactHit]:
    hits: list[CourseFactHit] = []
    for course in courses:
        text = course.model_dump_json()
        score = _text_score(text, tokens, raw_question)
        if course.code.casefold() in raw_question.casefold():
            score += 8
        if course.course_id in selected:
            score += 1
        if score > 0:
            hits.append(CourseFactHit(score=round(score, 6), course=course))
    return sorted(hits, key=lambda hit: (-hit.score, hit.course.course_id))


def _rank_items(
    items: list[InformationItem],
    tokens: list[str],
    raw_question: str,
    selected: set[str],
) -> list[InformationItemHit]:
    hits: list[InformationItemHit] = []
    for item in items:
        score = _text_score(item.model_dump_json(), tokens, raw_question)
        if item.course_id in selected:
            score += 1
        if score > 0:
            hits.append(InformationItemHit(score=round(score, 6), item=item))
    return sorted(
        hits,
        key=lambda hit: (-hit.score, _item_date_key(hit.item), hit.item.item_id),
    )


def _text_score(text: str, query_tokens: list[str], raw_question: str) -> float:
    folded = text.casefold()
    score = float(sum(min(folded.count(token), 4) for token in query_tokens))
    if raw_question.casefold() in folded:
        score += 4
    return score


def _item_date_key(item: InformationItem) -> str:
    candidates = [
        item.due_at,
        item.due_on,
        item.starts_at,
        item.scheduled_on,
        item.recurrence.valid_from if item.recurrence else None,
    ]
    return min((value.isoformat() for value in candidates if value is not None), default="9999")


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in WORD.findall(text.casefold()):
        if re.fullmatch(r"[\u3400-\u9fff]+", match):
            tokens.extend(
                match[index : index + 2]
                for index in range(max(len(match) - 1, 1))
            )
        elif len(match) > 1 or match.isdigit():
            tokens.append(match)
    return list(dict.fromkeys(tokens))
