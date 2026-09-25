"""Structured, read-only attention contracts shared by agents and UI clients."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from hsas.domain.courses.define_models import StrictModel


AttentionReason = Literal[
    "DUE_DATE_TENTATIVE",
    "DUE_DATE_UNKNOWN",
    "SUBMISSION_DETAILS_MISSING",
    "WEIGHT_UNKNOWN",
    "SOURCE_CONFLICT",
    "SOURCE_SYNC_FAILED",
    "SOURCE_CHANGED_REVIEW_PENDING",
    "LOGIN_REQUIRED",
    "OVERDUE_UNRESOLVED",
]
AttentionSeverity = Literal["high", "medium", "low"]
AttentionActionKind = Literal[
    "open_item",
    "open_evidence",
    "retry_source",
    "login_source",
    "review_changes",
]


class AttentionEvidence(StrictModel):
    """One existing source reference that can be inspected by a person or agent."""

    source_type: str
    title: str
    url: str | None = None
    relative_path: str | None = None
    page_numbers: list[int] = Field(default_factory=list)
    note: str | None = None


class AttentionAction(StrictModel):
    """An allowed action; presentation labels remain the delivery adapter's job."""

    kind: AttentionActionKind
    item_id: str | None = None
    source: str | None = None
    evidence_index: int | None = None


class AttentionItem(StrictModel):
    """A deterministic attention signal derived from existing validated state."""

    attention_id: str
    fingerprint: str
    course_id: str | None = None
    course_code: str | None = None
    course_title: str | None = None
    information_item_id: str | None = None
    title: str
    severity: AttentionSeverity
    reason_codes: list[AttentionReason]
    due_at: AwareDatetime | None = None
    date_status: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    conflicting_sources: list[str] = Field(default_factory=list)
    affected_source: str | None = None
    evidence: list[AttentionEvidence] = Field(default_factory=list)
    actions: list[AttentionAction] = Field(default_factory=list)


class AttentionSnapshot(StrictModel):
    """Complete attention packet exposed through the public HIQS port."""

    generated_at: AwareDatetime
    horizon_days: int = Field(ge=1, le=90)
    items: list[AttentionItem] = Field(default_factory=list)
    counts: dict[AttentionSeverity, int]
