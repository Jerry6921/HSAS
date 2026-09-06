"""Validated drafts for user-provided personal course information."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator

from hsas.domain.courses.define_models import StrictModel

from .define_information import InformationUpdate


class PersonalInboxEntry(StrictModel):
    entry_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    title: str = Field(min_length=1)
    note: str | None = None
    created_at: datetime
    status: Literal["pending", "applied"] = "pending"
    applied_at: datetime | None = None
    update: InformationUpdate

    @field_validator("created_at", "applied_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("inbox timestamps must include a UTC offset")
        return value


class PersonalInbox(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    entries: list[PersonalInboxEntry] = Field(default_factory=list)

    @field_validator("updated_at")
    @classmethod
    def require_updated_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("updated_at must include a UTC offset")
        return value
