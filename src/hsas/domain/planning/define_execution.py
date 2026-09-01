"""User-confirmed execution records; this is input data, not a generated plan."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from hsas.domain.courses import StrictModel


class ExecutionRecord(StrictModel):
    record_id: str
    plan_item_id: str
    item_type: str
    recorded_at: datetime
    planned_minutes: int = Field(gt=0)
    actual_minutes: int = Field(ge=0)
    progress_minutes: int | None = Field(default=None, ge=0)
    item_completed: bool = False
    notes: str | None = None

    @model_validator(mode="after")
    def default_progress_to_planned(self) -> "ExecutionRecord":
        if self.progress_minutes is None:
            self.progress_minutes = self.planned_minutes
        return self


class ExecutionWritePolicy(StrictModel):
    owner: Literal["student"] = "student"
    ai_may_read: bool = True
    ai_may_write_user_confirmed_data: bool = True
    ai_must_not_infer_actual_minutes: bool = True


class ExecutionLog(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    updated_at: datetime | None = None
    records: list[ExecutionRecord] = Field(default_factory=list)
    write_policy: ExecutionWritePolicy = Field(default_factory=ExecutionWritePolicy)

    @model_validator(mode="after")
    def ensure_unique_records(self) -> "ExecutionLog":
        ids = [record.record_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate execution record_id")
        return self
