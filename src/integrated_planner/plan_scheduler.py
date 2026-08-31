"""Availability-aware timetable allocation for an integrated plan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime, time as Time, timedelta

from .plan_rules import block_type, capacity_rank, effective_deadline
from .plan_schema import CapacitySummary, PlanItem, TimetableBlock
from .profile_schema import StudentProfile


DAY_NAMES = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


@dataclass(slots=True)
class _Slot:
    day: Date
    start: Time
    end: Time
    capacity: str

    @property
    def minutes(self) -> int:
        return int(
            (
                datetime.combine(self.day, self.end)
                - datetime.combine(self.day, self.start)
            ).total_seconds()
            // 60
        )


def build_timetable(
    profile: StudentProfile,
    items: list[PlanItem],
    *,
    start: Date,
    end: Date,
    current: datetime,
    preserved_blocks: list[TimetableBlock],
) -> tuple[list[TimetableBlock], CapacitySummary, list[str]]:
    slots = _clip_slots_to_now(_available_slots(profile, start, end), current)
    available_minutes = sum(slot.minutes for slot in slots)
    slots = _subtract_blocks(slots, preserved_blocks)
    buffer_minutes = round(
        available_minutes
        * profile.planning_preferences.unscheduled_capacity_percent
        / 100
    )
    allocatable = max(available_minutes - buffer_minutes, 0)
    already_scheduled = sum(block.planned_minutes for block in preserved_blocks)
    remaining_capacity = max(allocatable - already_scheduled, 0)
    scheduled_by_day: dict[Date, int] = {}
    deep_sessions_by_day: dict[Date, int] = {}
    for block in preserved_blocks:
        scheduled_by_day[block.date] = (
            scheduled_by_day.get(block.date, 0) + block.planned_minutes
        )
        if block.block_type == "deep_work":
            deep_sessions_by_day[block.date] = (
                deep_sessions_by_day.get(block.date, 0) + 1
            )
    timetable = list(preserved_blocks)
    warnings: list[str] = []
    session_minutes = profile.study_capacity.preferred_session_minutes or 60
    break_minutes = profile.study_capacity.preferred_break_minutes or 10
    maximum_daily = profile.availability.maximum_study_minutes_per_day
    maximum_deep = profile.study_capacity.maximum_deep_work_sessions_per_day
    candidates = [
        item
        for item in items
        if item.status not in {"completed", "cancelled"}
        and item.readiness == "ready"
        and item.priority.level != "planned"
        and (item.effort.remaining_minutes or 0) > 0
    ]
    required_minutes = sum(item.effort.remaining_minutes or 0 for item in candidates)
    candidate_ids = {item.plan_item_id for item in candidates}
    preserved_allocation = sum(
        block.planned_minutes
        for block in preserved_blocks
        if block.status == "started" and block.plan_item_id in candidate_ids
    )
    newly_scheduled = 0

    if not slots:
        warnings.append(
            "Student Profile has no future availability in this planning "
            "window; tasks were classified but no new timetable blocks were "
            "generated."
        )
        capacity = CapacitySummary(
            available_minutes=0,
            allocatable_minutes=0,
            required_minutes=required_minutes,
            scheduled_minutes=sum(
                block.planned_minutes for block in preserved_blocks
            ),
            buffer_minutes=0,
            unscheduled_minutes=0,
            unscheduled_workload_minutes=max(
                required_minutes - preserved_allocation,
                0,
            ),
            over_capacity=required_minutes > preserved_allocation,
        )
        return list(preserved_blocks), capacity, warnings

    for item in candidates:
        item_remaining = item.effort.remaining_minutes or 0
        deadline = effective_deadline(item.official_timing, current.tzinfo)
        if deadline is not None:
            deadline -= timedelta(
                hours=profile.planning_preferences.deadline_buffer_hours
            )
        item_block_type = block_type(item)
        item_slots = sorted(
            slots,
            key=lambda slot: (
                slot.day,
                capacity_rank(slot.capacity)
                if item.learning_demand.difficulty_level >= 4
                else 0,
                slot.start,
            ),
        )
        for slot in item_slots:
            if item_remaining <= 0 or remaining_capacity <= 0:
                break
            slot_start = datetime.combine(
                slot.day,
                slot.start,
                tzinfo=current.tzinfo,
            )
            if slot_start < current:
                continue
            if deadline is not None and slot_start >= deadline:
                continue
            if (
                item_block_type == "deep_work"
                and maximum_deep is not None
                and deep_sessions_by_day.get(slot.day, 0) >= maximum_deep
            ):
                continue
            day_remaining = (
                max(maximum_daily - scheduled_by_day.get(slot.day, 0), 0)
                if maximum_daily is not None
                else slot.minutes
            )
            chunk = min(
                item_remaining,
                session_minutes,
                slot.minutes,
                day_remaining,
                remaining_capacity,
            )
            if deadline is not None:
                deadline_minutes = int((deadline - slot_start).total_seconds() // 60)
                chunk = min(chunk, max(deadline_minutes, 0))
            if chunk <= 0:
                continue
            end_time = (
                datetime.combine(slot.day, slot.start) + timedelta(minutes=chunk)
            ).time()
            block = TimetableBlock(
                block_id=(
                    f"block:{item.plan_item_id}:{slot.day.isoformat()}:"
                    f"{slot.start.strftime('%H%M')}"
                ),
                plan_item_id=item.plan_item_id,
                date=slot.day,
                start_time=slot.start,
                end_time=end_time,
                planned_minutes=chunk,
                block_type=item_block_type,
                expected_output=(
                    item.completion_criteria[0]
                    if item.completion_criteria
                    else f"Make measurable progress on {item.title}"
                ),
            )
            timetable.append(block)
            newly_scheduled += chunk
            item_remaining -= chunk
            remaining_capacity -= chunk
            scheduled_by_day[slot.day] = (
                scheduled_by_day.get(slot.day, 0) + chunk
            )
            if item_block_type == "deep_work":
                deep_sessions_by_day[slot.day] = (
                    deep_sessions_by_day.get(slot.day, 0) + 1
                )
            next_start = (
                datetime.combine(slot.day, end_time)
                + timedelta(minutes=break_minutes)
            ).time()
            slot.start = min(next_start, slot.end)
        if item_remaining > 0:
            warnings.append(
                f"Insufficient schedulable capacity for {item.plan_item_id}; "
                f"{item_remaining} minute(s) remain unscheduled."
            )

    timetable.sort(key=lambda block: (block.date, block.start_time, block.block_id))
    scheduled = sum(block.planned_minutes for block in timetable)
    unscheduled_workload = max(
        required_minutes - preserved_allocation - newly_scheduled,
        0,
    )
    capacity = CapacitySummary(
        available_minutes=available_minutes,
        allocatable_minutes=allocatable,
        required_minutes=required_minutes,
        scheduled_minutes=scheduled,
        buffer_minutes=buffer_minutes,
        unscheduled_minutes=max(
            available_minutes - scheduled - buffer_minutes,
            0,
        ),
        unscheduled_workload_minutes=unscheduled_workload,
        over_capacity=unscheduled_workload > 0,
    )
    return timetable, capacity, warnings


def _available_slots(
    profile: StudentProfile,
    start: Date,
    end: Date,
) -> list[_Slot]:
    weekly = {
        entry.day_of_week: entry.available_blocks
        for entry in profile.availability.weekly_pattern
    }
    exceptions = {
        entry.date: entry.available_blocks
        for entry in profile.availability.date_exceptions
    }
    commitments = profile.availability.fixed_commitments
    slots: list[_Slot] = []
    day = start
    while day <= end:
        day_name = DAY_NAMES[day.weekday()]
        if (
            not profile.planning_preferences.allow_weekend_study
            and day.weekday() >= 5
        ):
            day += timedelta(days=1)
            continue
        blocks = exceptions.get(day, weekly.get(day_name, []))
        day_slots = [
            _Slot(
                day=day,
                start=block.start,
                end=block.end,
                capacity=block.capacity,
            )
            for block in blocks
        ]
        for commitment in commitments:
            if commitment.date == day or commitment.day_of_week == day_name:
                day_slots = _subtract_interval(
                    day_slots,
                    commitment.start,
                    commitment.end,
                )
        slots.extend(day_slots)
        day += timedelta(days=1)
    return sorted(slots, key=lambda slot: (slot.day, slot.start))


def _clip_slots_to_now(slots: list[_Slot], current: datetime) -> list[_Slot]:
    result: list[_Slot] = []
    rounded = current.replace(second=0, microsecond=0)
    if rounded < current:
        rounded += timedelta(minutes=1)
    for slot in slots:
        if slot.day < current.date():
            continue
        if slot.day > current.date():
            result.append(slot)
            continue
        if slot.end <= rounded.time():
            continue
        if slot.start < rounded.time():
            slot.start = rounded.time()
        result.append(slot)
    return result


def _subtract_blocks(
    slots: list[_Slot],
    blocks: list[TimetableBlock],
) -> list[_Slot]:
    result = slots
    for block in blocks:
        matching = [slot for slot in result if slot.day == block.date]
        other = [slot for slot in result if slot.day != block.date]
        result = other + _subtract_interval(
            matching,
            block.start_time,
            block.end_time,
        )
    return sorted(result, key=lambda slot: (slot.day, slot.start))


def _subtract_interval(
    slots: list[_Slot],
    blocked_start: Time,
    blocked_end: Time,
) -> list[_Slot]:
    result: list[_Slot] = []
    for slot in slots:
        if blocked_end <= slot.start or blocked_start >= slot.end:
            result.append(slot)
            continue
        if slot.start < blocked_start:
            result.append(
                _Slot(
                    slot.day,
                    slot.start,
                    min(blocked_start, slot.end),
                    slot.capacity,
                )
            )
        if blocked_end < slot.end:
            result.append(
                _Slot(
                    slot.day,
                    max(blocked_end, slot.start),
                    slot.end,
                    slot.capacity,
                )
            )
    return [slot for slot in result if slot.start < slot.end]
