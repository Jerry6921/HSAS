from __future__ import annotations

import re
from dataclasses import dataclass

from ..parse_rules import (
    classify_assessment,
    clean_title,
    GENERIC_ASSESSMENT_HEADINGS,
    looks_like_assessment,
    normalized_title,
    pages_containing,
    parse_dates,
)
from ..schema import (
    AssessmentCandidate,
    AssessmentComponentHint,
    AssessmentGroupCandidate,
    SourceReference,
    SyllabusDocument,
)


WEIGHT_IN_PARENTHESES = re.compile(
    r"^\s*(?:\d+\s*[.)]\s*)?(?P<title>[^()\n]{2,100}?)\s*"
    r"\((?P<body>[^)]*?(?P<weight>\d+(?:\.\d+)?)\s*%[^)]*)\)\s*$",
    flags=re.IGNORECASE,
)
WEIGHT_AT_END = re.compile(
    r"^\s*(?:\d+\s*[.)]\s*)?(?P<title>[^%\n]{2,100}?)\s+"
    r"(?P<weight>\d+(?:\.\d+)?)\s*%\s*$",
    flags=re.IGNORECASE,
)
COMPONENT_PATTERN = re.compile(
    r"(?P<weight>\d+(?:\.\d+)?)\s*%\s*(?P<title>.*?)"
    r"(?=,\s*\d+(?:\.\d+)?\s*%|$)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class WeightedHeading:
    page_number: int
    title: str
    weight_percent: float
    body: str


def _weighted_headings(document: SyllabusDocument) -> list[WeightedHeading]:
    found: list[WeightedHeading] = []
    for page_number, page_text in document.pages.items():
        for line in page_text.splitlines():
            compact = " ".join(line.split())
            match = WEIGHT_IN_PARENTHESES.match(compact) or WEIGHT_AT_END.match(compact)
            if not match:
                continue
            title = clean_title(match.group("title"))
            if (
                title.casefold() in GENERIC_ASSESSMENT_HEADINGS
                or not looks_like_assessment(title)
            ):
                continue
            found.append(
                WeightedHeading(
                    page_number=page_number,
                    title=title,
                    weight_percent=float(match.group("weight")),
                    body=match.groupdict().get("body") or match.group(0),
                )
            )
    return found


def _component_hints(heading: WeightedHeading) -> list[AssessmentComponentHint]:
    tail = re.sub(
        r"^\s*\d+(?:\.\d+)?\s*%\s*(?:--|[-–—:])?\s*",
        "",
        heading.body,
        count=1,
    )
    matches = list(COMPONENT_PATTERN.finditer(tail))
    if len(matches) < 2:
        return []
    hints: list[AssessmentComponentHint] = []
    for match in matches:
        raw_title = match.group("title").strip(" -–—:;.")
        title = clean_title(raw_title) if raw_title else None
        hints.append(
            AssessmentComponentHint(
                title=title or None,
                weight_percent=float(match.group("weight")),
            )
        )
    return hints


def _context_for_title(document: SyllabusDocument, page_number: int, title: str) -> str:
    page = document.pages[page_number]
    lines = page.splitlines()
    matching_indexes = [
        index for index, line in enumerate(lines) if title.casefold() in line.casefold()
    ]
    if not matching_indexes:
        return page[:1800]

    preferred = [
        index
        for index in matching_indexes
        if "%" not in lines[index]
        and (
            lines[index].strip().casefold().startswith(title.casefold())
            or lines[index].strip().casefold().startswith(f"the {title.casefold()}")
        )
    ]
    start = preferred[0] if preferred else matching_indexes[0]
    context = [lines[start]]
    for following in lines[start + 1 : start + 8]:
        compact = " ".join(following.split())
        heading_match = (
            WEIGHT_IN_PARENTHESES.match(compact)
            or WEIGHT_AT_END.match(compact)
        )
        if heading_match:
            next_title = clean_title(heading_match.group("title"))
            if looks_like_assessment(next_title):
                break
        context.append(following)
    return " ".join(context)[:1800]


def _candidate(
    document: SyllabusDocument,
    *,
    page_number: int,
    title: str,
    weight_percent: float,
    year: int,
    group_id: str | None = None,
    confidence: float = 0.9,
) -> AssessmentCandidate:
    context = _context_for_title(document, page_number, title)
    assessment_type = classify_assessment(title)
    word_match = re.search(
        r"\b(\d{2,5})\s*[- ]?words?\b",
        context,
        flags=re.IGNORECASE,
    )
    return AssessmentCandidate(
        title=title,
        assessment_type=assessment_type,
        group_id=group_id,
        extraction_method="syllabus_text",
        confidence=confidence,
        weight_percent=weight_percent,
        word_limit=int(word_match.group(1)) if word_match else None,
        description=re.sub(r"\s+", " ", context).strip()[:500] or None,
        sources=[
            SourceReference(
                source_type="syllabus",
                relative_path=document.relative_path,
                page_numbers=[page_number],
            )
        ],
        **parse_dates(context, year=year, assessment_type=assessment_type),
    )


def extract_syllabus_candidates(
    document: SyllabusDocument,
    *,
    year: int,
) -> tuple[list[AssessmentCandidate], list[AssessmentGroupCandidate]]:
    candidates: list[AssessmentCandidate] = []
    groups: list[AssessmentGroupCandidate] = []
    for heading in _weighted_headings(document):
        hints = _component_hints(heading)
        if not hints:
            candidates.append(
                _candidate(
                    document,
                    page_number=heading.page_number,
                    title=heading.title,
                    weight_percent=heading.weight_percent,
                    year=year,
                )
            )
            continue

        group_id = normalized_title(heading.title).replace(" ", "-")
        groups.append(
            AssessmentGroupCandidate(
                group_id=group_id,
                title=heading.title,
                weight_percent=heading.weight_percent,
                description=_context_for_title(
                    document,
                    heading.page_number,
                    heading.title,
                )[:500],
                confidence=0.9,
                components=hints,
                sources=[
                    SourceReference(
                        source_type="syllabus",
                        relative_path=document.relative_path,
                        page_numbers=[heading.page_number],
                    )
                ],
            )
        )
        for hint in hints:
            if not hint.title or not looks_like_assessment(hint.title):
                continue
            candidates.append(
                _candidate(
                    document,
                    page_number=heading.page_number,
                    title=hint.title,
                    weight_percent=hint.weight_percent,
                    year=year,
                    group_id=group_id,
                    confidence=0.88,
                )
            )
    return candidates, groups


def extract_syllabus_metadata(
    document: SyllabusDocument,
) -> tuple[str | None, list[str]]:
    lowered = document.text.casefold()
    basis_match = re.search(
        r"assessment\s*\(\s*(\d+(?:\.\d+)?)\s*%\s*([^)]*)\)",
        document.text,
        flags=re.IGNORECASE,
    )
    grading_basis = None
    if basis_match:
        grading_basis = f"{basis_match.group(1)}% {basis_match.group(2).strip()}".strip()

    policies: list[str] = []
    normalized_lines = [" ".join(line.split()) for line in document.text.splitlines()]
    policy_markers = (
        "late assignment",
        "late work",
        "attendance is mandatory",
        "generative ai",
        "plagiarism",
        "academic honesty",
    )
    for line in normalized_lines:
        if len(line) < 20 or not any(
            marker in line.casefold() for marker in policy_markers
        ):
            continue
        value = line[:400]
        if value not in policies:
            policies.append(value)
        if len(policies) >= 6:
            break

    if "100% coursework" in lowered and not grading_basis:
        grading_basis = "100% Coursework"
    return grading_basis, policies


def syllabus_source(
    document: SyllabusDocument,
    *terms: str,
) -> SourceReference:
    return SourceReference(
        source_type="syllabus",
        relative_path=document.relative_path,
        page_numbers=pages_containing(document.pages, *terms),
    )
