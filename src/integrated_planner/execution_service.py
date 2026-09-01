"""Validated, idempotent mutations for user-confirmed execution data."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from hsas_runtime.storage import read_json, write_model
from .execution_schema import ExecutionLog, ExecutionRecord
from .plan_schema import IntegratedPlan, PlanItem


class ExecutionServiceError(ValueError):
    """Raised when an execution mutation is invalid or conflicts with the plan."""


def load_execution_log(path: Path) -> ExecutionLog:
    if not path.exists():
        return ExecutionLog()
    try:
        return ExecutionLog.model_validate(read_json(path))
    except (OSError, ValueError, ValidationError) as exc:
        raise ExecutionServiceError(f"invalid Execution Log {path}: {exc}") from exc


def load_plan(path: Path) -> IntegratedPlan:
    if not path.exists():
        raise ExecutionServiceError(f"Integrated Plan does not exist: {path}")
    try:
        return IntegratedPlan.model_validate(read_json(path))
    except (OSError, ValueError, ValidationError) as exc:
        raise ExecutionServiceError(f"invalid Integrated Plan {path}: {exc}") from exc


def add_execution_record(
    log_path: Path,
    plan_path: Path,
    *,
    plan_item_id: str,
    actual_minutes: int,
    progress_minutes: int,
    item_completed: bool = False,
    planned_minutes: int,
    notes: str | None = None,
    record_id: str | None = None,
    recorded_at: datetime | None = None,
) -> tuple[ExecutionLog, ExecutionRecord, bool]:
    """Append one confirmed event; an identical record ID is a safe retry."""
    plan = load_plan(plan_path)
    item = _plan_item(plan, plan_item_id)
    stamp = recorded_at or datetime.now(UTC)
    if stamp.tzinfo is None:
        raise ExecutionServiceError("recorded_at must include a timezone")
    resolved_id = record_id or (
        f"execution:{plan_item_id}:"
        f"{stamp.astimezone(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    try:
        record = ExecutionRecord(
            record_id=resolved_id,
            plan_item_id=plan_item_id,
            item_type=item.item_type,
            recorded_at=stamp,
            planned_minutes=planned_minutes,
            actual_minutes=actual_minutes,
            progress_minutes=progress_minutes,
            item_completed=item_completed,
            notes=notes,
        )
    except ValidationError as exc:
        raise ExecutionServiceError(f"execution record failed validation: {exc}") from exc

    log = load_execution_log(log_path)
    for existing in log.records:
        if existing.record_id != resolved_id:
            continue
        if existing == record:
            return log, existing, False
        raise ExecutionServiceError(
            f"record_id {resolved_id!r} already exists with different data"
        )

    log.records.append(record)
    log.updated_at = datetime.now(UTC)
    try:
        validated = ExecutionLog.model_validate(log.model_dump(mode="json"))
    except ValidationError as exc:
        raise ExecutionServiceError(f"Execution Log failed validation: {exc}") from exc
    write_model(log_path, validated)
    return validated, record, True


def correct_execution_record(
    log_path: Path,
    plan_path: Path,
    record_id: str,
    *,
    actual_minutes: int | None = None,
    progress_minutes: int | None = None,
    item_completed: bool | None = None,
    notes: str | None = None,
) -> tuple[ExecutionLog, ExecutionRecord]:
    """Correct confirmed mutable values while preserving record identity."""
    if all(
        value is None
        for value in (actual_minutes, progress_minutes, item_completed, notes)
    ):
        raise ExecutionServiceError("provide at least one corrected value")
    plan = load_plan(plan_path)
    log = load_execution_log(log_path)
    position = next(
        (index for index, record in enumerate(log.records) if record.record_id == record_id),
        None,
    )
    if position is None:
        raise ExecutionServiceError(f"unknown execution record_id: {record_id}")

    existing = log.records[position]
    item = _plan_item(plan, existing.plan_item_id)
    if existing.item_type != item.item_type:
        raise ExecutionServiceError(
            f"plan item type changed from {existing.item_type} to {item.item_type}"
        )
    changes = {
        key: value
        for key, value in {
            "actual_minutes": actual_minutes,
            "progress_minutes": progress_minutes,
            "item_completed": item_completed,
            "notes": notes,
        }.items()
        if value is not None
    }
    try:
        corrected = existing.model_copy(update=changes)
        corrected = ExecutionRecord.model_validate(corrected.model_dump(mode="json"))
    except ValidationError as exc:
        raise ExecutionServiceError(f"execution correction failed validation: {exc}") from exc
    log.records[position] = corrected
    log.updated_at = datetime.now(UTC)
    validated = ExecutionLog.model_validate(log.model_dump(mode="json"))
    write_model(log_path, validated)
    return validated, corrected


def _plan_item(plan: IntegratedPlan, plan_item_id: str) -> PlanItem:
    item = next((value for value in plan.items if value.plan_item_id == plan_item_id), None)
    if item is None:
        raise ExecutionServiceError(f"unknown plan_item_id: {plan_item_id}")
    return item
