"""Human- and Agent-readable explanations for indexed evidence."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from hsas.domain.courses import StrictModel
from hsas.domain.information import InformationStore, SourceReference


class EvidenceExplanation(StrictModel):
    """Explain what one evidence ID represents, supports, and cannot establish."""

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["found", "not_found"]
    evidence_id: str
    source_kind: str | None = None
    record_id: str | None = None
    course_id: str | None = None
    title: str | None = None
    statement: str | None = None
    confirmation_status: str | None = None
    sources: list[SourceReference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    extraction_method: str | None = None
    indexed_context: list[dict[str, Any]] = Field(default_factory=list)
    provenance: dict[str, Any] | None = None


def explain_information_evidence(
    information: InformationStore | None,
    evidence_id: str,
    indexed_context: list[dict[str, Any]],
) -> EvidenceExplanation | None:
    if information is None:
        return None
    if evidence_id.startswith("information:course:"):
        record_id = evidence_id.removeprefix("information:course:")
        course = next((value for value in information.courses if value.course_id == record_id), None)
        if course is None:
            return None
        limitations = [] if course.sources else ["该课程记录没有附带可打开的来源引用。"]
        return EvidenceExplanation(
            status="found", evidence_id=evidence_id,
            source_kind="information_course", record_id=record_id,
            course_id=record_id, title=f"{course.code} {course.title}",
            statement=course.overview or "课程级正式信息记录。",
            confirmation_status="canonical",
            sources=course.sources, limitations=limitations,
            extraction_method="Validated information.json course record",
            indexed_context=indexed_context,
        )
    if evidence_id.startswith("information:item:"):
        record_id = evidence_id.removeprefix("information:item:")
        item = next((value for value in information.items if value.item_id == record_id), None)
        if item is None:
            return None
        limitations = [] if item.sources else ["该事项没有附带可打开的来源引用。"]
        if item.date_status != "confirmed":
            limitations.append(f"日期状态为 {item.date_status}，不得视为已确认日期。")
        return EvidenceExplanation(
            status="found", evidence_id=evidence_id,
            source_kind="information_item", record_id=record_id,
            course_id=item.course_id, title=item.title,
            statement=item.description or f"{item.category} 事项的正式记录。",
            confirmation_status=item.date_status,
            sources=item.sources, warnings=item.warnings,
            limitations=limitations,
            extraction_method="Validated information.json item record",
            indexed_context=indexed_context,
        )
    return None
