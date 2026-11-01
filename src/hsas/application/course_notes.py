"""Validated checkpoints for Agent-authored notes, separate from course facts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NotesModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceReview(NotesModel):
    source_id: str
    role: Literal["unknown", "lecture", "syllabus", "paper", "quiz", "answer", "supplement"]
    disposition: Literal["included", "excluded"] = "included"
    reading: Literal["pending", "read", "limited"] = "pending"
    locators: list[str] = Field(default_factory=list)
    reason: str = ""
    limitations: list[str] = Field(default_factory=list)
    question_inventory_complete: bool = False

    @model_validator(mode="after")
    def explain_decision(self):
        if self.disposition == "excluded" and not self.reason:
            raise ValueError("Excluded sources need a reason.")
        if self.reading == "read" and not self.locators:
            raise ValueError("Read sources need verified page/slide/heading locators.")
        if self.reading == "limited" and not self.limitations:
            raise ValueError("Limited reading needs precise limitations.")
        return self


class NotesUnit(NotesModel):
    unit_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    title: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)


class NotesCitation(NotesModel):
    source_id: str
    locator: str = Field(min_length=1)


class NotesArtifact(NotesModel):
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    kind: Literal["overview", "unit", "question-map", "review", "coverage"]
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    citations: list[NotesCitation] = Field(min_length=1)


class NotesQuestion(NotesModel):
    question_id: str = Field(min_length=1)
    source_id: str
    locator: str = Field(min_length=1)
    unit_ids: list[str] = Field(default_factory=list)
    scope: Literal["current", "historical-only", "unmatched"] = "current"
    answer_kind: Literal["official", "agent-derived", "teaching-variant", "unresolved"]
    answer_citation: NotesCitation | None = None
    note: str = ""

    @model_validator(mode="after")
    def explain_mapping(self):
        if self.scope == "current" and not self.unit_ids:
            raise ValueError("Current-scope questions must map to a unit.")
        if self.scope != "current" and not self.note:
            raise ValueError("Unmatched/historical questions need a scope explanation.")
        if self.answer_kind == "official" and self.answer_citation is None:
            raise ValueError("Official answers need a separate source locator.")
        return self


class NotesPublication(NotesModel):
    target: str = Field(min_length=1)
    status: Literal["pending", "failed", "verified"]
    url: str = ""
    readback_note: str = ""

    @model_validator(mode="after")
    def verify_receipt(self):
        if self.status == "verified" and (not self.url or not self.readback_note):
            raise ValueError("Verified publication needs its URL and Agent readback evidence.")
        return self


class NotesCheckpoint(NotesModel):
    source_reviews: list[SourceReview] = Field(default_factory=list)
    units: list[NotesUnit] | None = None
    artifacts: list[NotesArtifact] = Field(default_factory=list)
    questions: list[NotesQuestion] | None = None
    limitations: list[str] | None = None
    publication: NotesPublication | None = None
    reconciled_exports: dict[str, str] = Field(default_factory=dict)
    status: Literal["working", "partial", "blocked", "complete"] = "working"
    status_note: str = ""
