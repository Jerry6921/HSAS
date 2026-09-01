from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from hsas.infrastructure.storage.persist_data import read_text, safe_filename
from hsas.domain.courses.index_courses import ArchiveIndex, FileLocation
from .parse_assessment_text import course_year, looks_like_assessment, normalized_title, page_map
from . import (
    extract_moodle_candidates,
    extract_syllabus_candidates,
    extract_syllabus_metadata,
)
from hsas.domain.courses.define_assessments import (
    AssessmentCandidate,
    AssessmentGroup,
    AssessmentGroupCandidate,
    AssessmentItem,
    AssessmentOverview,
    SourceReference,
    SyllabusDocument,
)


SYLLABUS_MARKERS = (
    "syllabus",
    "course outline",
    "course guide",
    "course handbook",
)
MERGED_FIELDS = (
    "weight_percent",
    "bonus_percent",
    "word_limit",
    "opens_on",
    "due_on",
    "due_at",
    "scheduled_on",
    "description",
)
CONFLICT_FIELDS = {
    "weight_percent",
    "word_limit",
    "opens_on",
    "due_on",
    "due_at",
    "scheduled_on",
}
GROUP_GENERIC_WORDS = {
    "assessment",
    "assignment",
    "collection",
    "coursework",
    "portfolio",
    "series",
    "weekly",
    "writing",
}


def _find_syllabus(index: ArchiveIndex) -> FileLocation | None:
    for marker in SYLLABUS_MARKERS:
        location = index.find_document(role=marker)
        if location is not None:
            return location
    return None


def _load_syllabus(
    index: ArchiveIndex,
    *,
    storage_root: Path,
) -> tuple[SyllabusDocument | None, list[str]]:
    location = _find_syllabus(index)
    if location is None:
        return None, [
            "No analyzed syllabus, course outline, or course guide was found."
        ]

    stored_file = location.stored_file
    analysis = stored_file.analysis
    if analysis is None or not analysis.extracted_text_path:
        return None, [
            f"{stored_file.filename}: PDF text analysis is unavailable."
        ]

    text_path = storage_root / analysis.extracted_text_path
    try:
        text = read_text(text_path)
    except (OSError, UnicodeError) as exc:
        return None, [
            f"Could not read syllabus text at {analysis.extracted_text_path}: {exc}"
        ]

    return (
        SyllabusDocument(
            text=text,
            pages=page_map(text),
            relative_path=stored_file.relative_path,
        ),
        [],
    )


def _source_key(source: SourceReference) -> tuple[Any, ...]:
    return (
        source.source_type,
        source.relative_path,
        source.section_id,
        source.activity_id,
        tuple(source.page_numbers),
        source.note,
    )


def _unique_sources(candidates: list[AssessmentCandidate]) -> list[SourceReference]:
    sources: list[SourceReference] = []
    seen: set[tuple[Any, ...]] = set()
    for candidate in candidates:
        for source in candidate.sources:
            key = _source_key(source)
            if key not in seen:
                seen.add(key)
                sources.append(source)
    return sources


def _choose_field(
    candidates: list[AssessmentCandidate],
    field: str,
    warnings: list[str],
) -> Any:
    values = [
        (candidate, getattr(candidate, field))
        for candidate in candidates
        if getattr(candidate, field) is not None
    ]
    if not values:
        return None
    chosen_candidate, chosen = values[0]
    distinct = {str(value) for _, value in values}
    if field in CONFLICT_FIELDS and len(distinct) > 1:
        warnings.append(
            f"Conflicting {field} values for {chosen_candidate.title}: "
            + ", ".join(sorted(distinct))
            + f"; selected {chosen}."
        )
    return chosen


def _merge_candidates(
    candidates: list[AssessmentCandidate],
) -> tuple[list[AssessmentItem], list[str]]:
    grouped: dict[str, list[AssessmentCandidate]] = defaultdict(list)
    for candidate in candidates:
        key = normalized_title(candidate.title)
        if key:
            grouped[key].append(candidate)

    items: list[AssessmentItem] = []
    warnings: list[str] = []
    used_ids: set[str] = set()
    for group in grouped.values():
        ordered = sorted(group, key=lambda candidate: candidate.confidence, reverse=True)
        primary = ordered[0]
        methods = list(
            dict.fromkeys(candidate.extraction_method for candidate in ordered)
        )
        confidence = min(
            0.99,
            primary.confidence + 0.05 * (len(set(methods)) - 1),
        )
        item_id = safe_filename(primary.title).casefold()
        base_id = item_id
        suffix = 2
        while item_id in used_ids:
            item_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(item_id)

        values = {
            field: _choose_field(ordered, field, warnings)
            for field in MERGED_FIELDS
        }
        requirements = list(
            dict.fromkeys(
                requirement
                for candidate in ordered
                for requirement in candidate.requirements
            )
        )
        visible_values = [
            candidate.visible_in_course
            for candidate in ordered
            if candidate.visible_in_course is not None
        ]
        group_ids = [candidate.group_id for candidate in ordered if candidate.group_id]
        group_id = group_ids[0] if group_ids else None
        if len(set(group_ids)) > 1:
            warnings.append(
                f"Conflicting group assignments for {primary.title}: "
                + ", ".join(dict.fromkeys(group_ids))
                + f"; selected {group_id}."
            )
        items.append(
            AssessmentItem(
                assessment_id=item_id,
                group_id=group_id,
                title=primary.title,
                assessment_type=primary.assessment_type,
                requirements=requirements,
                visible_in_course=any(visible_values) if visible_values else True,
                status=(
                    "confirmed"
                    if confidence >= 0.8 or len(set(methods)) >= 2
                    else "tentative"
                ),
                confidence=confidence,
                extraction_methods=methods,
                sources=_unique_sources(ordered),
                **values,
            )
        )
    return items, warnings


def _title_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in normalized_title(value).split():
        singular = token[:-1] if token.endswith("s") and len(token) > 3 else token
        if singular not in GROUP_GENERIC_WORDS:
            tokens.add(singular)
    return tokens


def _matches_group(item: AssessmentItem, group: AssessmentGroupCandidate) -> bool:
    group_tokens = _title_tokens(group.title)
    item_tokens = _title_tokens(item.title)
    return bool(group_tokens) and group_tokens.issubset(item_tokens)


def _append_sources(item: AssessmentItem, sources: list[SourceReference]) -> None:
    existing = {_source_key(source) for source in item.sources}
    for source in sources:
        if _source_key(source) not in existing:
            item.sources.append(source)
            existing.add(_source_key(source))


def _apply_groups(
    items: list[AssessmentItem],
    candidates: list[AssessmentGroupCandidate],
) -> tuple[list[AssessmentGroup], list[str]]:
    groups: list[AssessmentGroup] = []
    warnings: list[str] = []
    for candidate in candidates:
        groups.append(
            AssessmentGroup(
                group_id=candidate.group_id,
                title=candidate.title,
                weight_percent=candidate.weight_percent,
                description=candidate.description,
                confidence=candidate.confidence,
                extraction_methods=["syllabus_text"],
                sources=candidate.sources,
            )
        )

        assigned = [item for item in items if item.group_id == candidate.group_id]
        unnamed_hints = [
            hint
            for hint in candidate.components
            if not hint.title or not looks_like_assessment(hint.title)
        ]
        if not assigned and len(unnamed_hints) == len(candidate.components):
            matched = [
                item
                for item in items
                if item.group_id is None and _matches_group(item, candidate)
            ]
            if len(matched) == len(candidate.components):
                for item, hint in zip(matched, candidate.components, strict=True):
                    item.group_id = candidate.group_id
                    item.weight_percent = item.weight_percent or hint.weight_percent
                    item.extraction_methods = list(
                        dict.fromkeys([*item.extraction_methods, "syllabus_text"])
                    )
                    item.confidence = max(item.confidence or 0, 0.85)
                    item.status = "confirmed"
                    _append_sources(item, candidate.sources)
                assigned = matched
            elif matched:
                warnings.append(
                    f"Could not safely distribute {candidate.title} weights: "
                    f"found {len(matched)} matching items for "
                    f"{len(candidate.components)} components."
                )

        child_total = sum(
            item.weight_percent or 0
            for item in items
            if item.group_id == candidate.group_id
        )
        if assigned and abs(child_total - candidate.weight_percent) > 0.01:
            warnings.append(
                f"{candidate.title} child weights sum to {child_total:g}%, "
                f"not {candidate.weight_percent:g}%."
            )
    return groups, warnings


def _validate_overview(overview: AssessmentOverview) -> AssessmentOverview:
    warnings = list(overview.warnings)
    if not overview.items:
        warnings.append("No assessment items were detected.")

    weighted = [item for item in overview.items if item.weight_percent is not None]
    missing_weights = sum(
        item.weight_percent is None and item.bonus_percent is None
        for item in overview.items
    )
    total = sum(item.weight_percent or 0 for item in weighted)
    overview.total_weight_percent = total if weighted else None
    if weighted and missing_weights:
        warnings.append(
            f"Known assessment weights sum to {total:g}%; "
            f"{missing_weights} item(s) have no confirmed weight."
        )
    elif weighted and abs(total - 100) > 0.01:
        warnings.append(f"Assessment item weights sum to {total:g}%, not 100%.")

    for item in overview.items:
        if item.opens_on and item.due_on and item.opens_on > item.due_on:
            warnings.append(f"{item.title}: opens_on is later than due_on.")
        if not item.sources:
            warnings.append(f"{item.title}: no source reference was retained.")

    overview.warnings = list(dict.fromkeys(warnings))
    return overview


def build_assessment_overview(
    index: ArchiveIndex,
    *,
    storage_root: Path,
) -> AssessmentOverview:
    """Extract, merge, group, validate, and return one assessment overview."""
    archive = index.archive
    candidates = extract_moodle_candidates(archive)
    document, warnings = _load_syllabus(index, storage_root=storage_root)
    grading_basis: str | None = None
    policies: list[str] = []
    group_candidates: list[AssessmentGroupCandidate] = []

    if document is not None:
        syllabus_candidates, group_candidates = extract_syllabus_candidates(
            document,
            year=course_year(archive),
        )
        candidates.extend(syllabus_candidates)
        grading_basis, policies = extract_syllabus_metadata(document)

    items, merge_warnings = _merge_candidates(candidates)
    groups, group_warnings = _apply_groups(items, group_candidates)
    overview = AssessmentOverview(
        parser_version="generic-v1",
        grading_basis=grading_basis,
        groups=groups,
        items=items,
        policies=policies,
        warnings=[*warnings, *merge_warnings, *group_warnings],
    )
    return _validate_overview(overview)
