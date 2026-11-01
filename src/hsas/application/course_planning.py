"""Evidence-bearing course choices and deterministic whole-plan constraint solving.

Official pages are interpreted by the Agent. This module never turns a missing
qualification, component, or date into a verified fact.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


Identifier = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")]


class PlanningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Evidence(PlanningModel):
    source: str = Field(min_length=1, max_length=500)
    locator: str = Field(min_length=1, max_length=500)
    observed_at: AwareDatetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Meeting(PlanningModel):
    component: str = Field(min_length=1)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    location: str = ""

    @model_validator(mode="after")
    def ordered(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Meeting end must follow start")
        return self


class WeeklyMeeting(PlanningModel):
    """Expand source-backed teaching weeks, excluding holidays and adding makeups."""

    component: str
    starts_on: date
    ends_on: date
    weekday: int = Field(ge=0, le=6)
    starts_at: time
    ends_at: time
    timezone: str = "Asia/Hong_Kong"
    excluded_dates: list[date] = Field(default_factory=list)
    additional_dates: list[date] = Field(default_factory=list)
    location: str = ""

    @model_validator(mode="after")
    def ordered(self):
        if self.ends_on < self.starts_on or self.ends_at <= self.starts_at:
            raise ValueError("Invalid teaching period or daily times")
        if (self.ends_on - self.starts_on).days > 1096:
            raise ValueError("A term meeting period cannot exceed three years")
        return self

    def expand(self) -> list[Meeting]:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(self.timezone)
        current = self.starts_on
        dates = set(self.additional_dates)
        while current <= self.ends_on:
            if current.weekday() == self.weekday and current not in self.excluded_dates:
                dates.add(current)
            current += timedelta(days=1)
        return [
            Meeting(
                component=self.component,
                starts_at=datetime.combine(day, self.starts_at, zone),
                ends_at=datetime.combine(day, self.ends_at, zone),
                location=self.location,
            )
            for day in sorted(dates)
        ]


class CourseOption(PlanningModel):
    option_id: Identifier
    course_code: str = Field(pattern=r"^[A-Z]{4}[0-9]{4}$")
    term: Identifier
    credits: float = Field(gt=0, le=100)
    # A complete combination, e.g. {"lecture": "1A", "lab": "2B"}.
    components: dict[str, str] = Field(min_length=1)
    required_components: list[str] = Field(min_length=1)
    meetings: list[Meeting] = Field(default_factory=list, max_length=1000)
    recurring_meetings: list[WeeklyMeeting] = Field(default_factory=list, max_length=30)
    asynchronous_components: list[str] = Field(default_factory=list)
    schedule_verified: bool = False
    exams_checked: bool = False
    corequisite_courses: list[str] = Field(default_factory=list)
    excluded_courses: list[str] = Field(default_factory=list)
    eligible: bool | None = None
    eligibility_note: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def components_complete(self):
        if len(set(self.required_components)) != len(self.required_components):
            raise ValueError("Duplicate required component")
        if not set(self.required_components) <= self.components.keys():
            raise ValueError("Option is missing a required component")
        if any(not k.strip() or not v.strip() for k, v in self.components.items()):
            raise ValueError("Component identities must be non-empty")
        if self.recurring_meetings:
            self.meetings.extend(m for weekly in self.recurring_meetings for m in weekly.expand())
            self.recurring_meetings = []
        if len(self.meetings) > 1000:
            raise ValueError("Expanded option exceeds 1000 meetings")
        scheduled = {m.component for m in self.meetings} | set(self.asynchronous_components)
        if self.schedule_verified and not set(self.components) <= scheduled:
            raise ValueError(
                "Verified schedule must cover every component, including explicit asynchronous components"
            )
        if not set(self.asynchronous_components) <= self.components.keys():
            raise ValueError("Unknown asynchronous component")
        if any(m.component not in {*self.components, "exam"} for m in self.meetings):
            raise ValueError("Meeting refers to an unknown component")
        self.meetings.sort(key=lambda m: (m.starts_at, m.ends_at, m.component, m.location))
        self.required_components.sort()
        self.asynchronous_components.sort()
        return self


class Goal(PlanningModel):
    goal_id: Identifier
    option_ids: list[Identifier] = Field(min_length=1)
    description: str = Field(min_length=1)


class Constraints(PlanningModel):
    min_credits: float = Field(default=0, ge=0)
    max_credits: float = Field(gt=0)
    unavailable: list[Meeting] = Field(default_factory=list)
    buffer_minutes: int = Field(default=0, ge=0, le=240)
    prefer_start_after: int | None = Field(default=None, ge=0, lt=1440)
    prefer_fewer_days: bool = False

    @model_validator(mode="after")
    def credit_range(self):
        if self.min_credits > self.max_credits:
            raise ValueError("Minimum credits exceed maximum")
        return self


class PlanningRequest(PlanningModel):
    account: Identifier  # non-secret local account label, not credentials
    term: Identifier
    goals: list[Goal] = Field(min_length=1, max_length=30)
    options: list[CourseOption] = Field(min_length=1, max_length=200)
    constraints: Constraints
    scope: str = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        options = {o.option_id: o for o in self.options}
        if len(options) != len(self.options) or len({g.goal_id for g in self.goals}) != len(
            self.goals
        ):
            raise ValueError("Duplicate option or goal IDs")
        if any(o.term != self.term for o in self.options):
            raise ValueError("Option belongs to another term")
        for goal in self.goals:
            if (
                len(set(goal.option_ids)) != len(goal.option_ids)
                or not set(goal.option_ids) <= options.keys()
            ):
                raise ValueError("Goal options must be distinct approved pool members")
        if set(options) != {oid for g in self.goals for oid in g.option_ids}:
            raise ValueError("Every approved option must belong to a goal")
        return self


EnrollmentStatus = Literal["enrolled", "pending", "waitlisted", "absent", "unknown"]
Failure = Literal[
    "full",
    "closed",
    "conflict",
    "ineligible",
    "credit-limit",
    "transient",
    "authentication",
    "not-submitted",
]


class EnrollmentRecord(PlanningModel):
    option: CourseOption
    status: EnrollmentStatus
    raw_status: str = Field(min_length=1)
    evidence: Evidence


class Availability(PlanningModel):
    status: Literal["open", "full", "closed", "unknown", "ineligible"]
    # Change only when the underlying restriction/capacity changes, not each poll.
    condition_key: str = Field(min_length=1, max_length=200)
    eligibility: Literal["unchanged", "eligible", "ineligible", "unknown"] = "unchanged"
    eligibility_note: str = ""
    evidence: Evidence


class Observation(PlanningModel):
    account: Identifier
    term: Identifier
    captured_at: AwareDatetime
    complete: bool  # full active/pending account roster, not only the chosen courses
    window: Literal["open", "not-open", "closed", "unknown"]
    authenticated: bool
    evidence: Evidence
    records: list[EnrollmentRecord] = Field(default_factory=list)
    availability: dict[str, Availability] = Field(default_factory=dict)
    attempt_outcomes: dict[str, Failure] = Field(default_factory=dict)
    retry_after: AwareDatetime | None = None

    @model_validator(mode="after")
    def coherent(self):
        ids = [r.option.option_id for r in self.records]
        active = [r.option.course_code for r in self.records if r.status == "enrolled"]
        if len(set(ids)) != len(ids) or len(set(active)) != len(active):
            raise ValueError("Duplicate enrolment identities")
        if any(r.option.term != self.term for r in self.records):
            raise ValueError("Roster contains another term")
        if any(
            e.observed_at > self.captured_at
            for e in [self.evidence]
            + [r.evidence for r in self.records]
            + [v.evidence for v in self.availability.values()]
        ):
            raise ValueError("Evidence is newer than its observation")
        return self


class Authorization(PlanningModel):
    starts_at: AwareDatetime
    expires_at: AwareDatetime
    check_interval_seconds: int = Field(ge=30, le=86400)
    max_snapshot_age_seconds: int = Field(ge=1, le=3600)
    max_attempts: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def ordered(self):
        if self.expires_at <= self.starts_at:
            raise ValueError("Authorization expiry must follow start")
        return self


def conflicts(a: list[Meeting], b: list[Meeting], buffer: int) -> bool:
    padding = timedelta(minutes=buffer)
    return any(
        x.starts_at < y.ends_at + padding and y.starts_at < x.ends_at + padding
        for x in a
        for y in b
    )


def same_choice(a: CourseOption, b: CourseOption) -> bool:
    """Exact enrolled course/components and schedule, independent of evidence refresh."""
    return (a.course_code, a.term, a.credits, a.components, a.required_components, a.meetings) == (
        b.course_code,
        b.term,
        b.credits,
        b.components,
        b.required_components,
        b.meetings,
    )


def plan(
    request: PlanningRequest,
    fixed: list[CourseOption],
    unavailable: set[str],
    *,
    budget: int = 50000,
) -> dict:
    """Solve all remaining goals together, preserving every fixed account course."""
    constraints = request.constraints
    options = {o.option_id: o for o in request.options}
    if len({o.course_code for o in fixed}) != len(fixed):
        return {
            "status": "blocked",
            "reason": "Multiple active/pending combinations for one course need review.",
        }
    if any(not o.schedule_verified for o in fixed):
        return {"status": "needs-user", "reason": "Fixed course schedule is unverified."}
    for index, option in enumerate(fixed):
        if (
            any(
                conflicts([m], option.meetings[:i], constraints.buffer_minutes)
                for i, m in enumerate(option.meetings)
            )
            or conflicts(option.meetings, constraints.unavailable, 0)
            or any(
                conflicts(option.meetings, other.meetings, constraints.buffer_minutes)
                for other in fixed[:index]
            )
        ):
            return {
                "status": "blocked",
                "reason": "Fixed courses violate time constraints; preserved.",
            }
    best = None
    visits = 0
    exhausted = False
    used_codes = {o.course_code for o in fixed}

    def tick():
        nonlocal visits, exhausted
        visits += 1
        if visits > budget:
            exhausted = True
        return not exhausted

    def search(remaining, index, selected, assignments, matched, credits, rank):
        nonlocal best
        if not tick() or credits > constraints.max_credits:
            return
        if index == len(remaining):
            if credits < constraints.min_credits:
                return
            all_choices = fixed + selected
            course_codes = {o.course_code for o in all_choices}
            if any(
                not set(o.corequisite_courses) <= course_codes
                or (set(o.excluded_courses) & (course_codes - {o.course_code}))
                for o in all_choices
            ):
                return
            meetings = [m for o in fixed + selected for m in o.meetings if m.component != "exam"]
            days = (
                len({m.starts_at.date() for m in meetings}) if constraints.prefer_fewer_days else 0
            )
            early = (
                sum(
                    max(
                        0,
                        constraints.prefer_start_after
                        - (m.starts_at.hour * 60 + m.starts_at.minute),
                    )
                    for m in meetings
                )
                if constraints.prefer_start_after is not None
                else 0
            )
            score = (days, early, rank, tuple(sorted(assignments.items())))
            if best is None or score < best[0]:
                best = (score, dict(assignments), list(selected), credits, dict(matched))
            return
        goal = remaining[index]
        for priority, oid in enumerate(goal.option_ids):
            option = options[oid]
            if oid in unavailable or option.eligible is not True or not option.schedule_verified:
                continue
            if option.course_code in used_codes or any(
                o.course_code == option.course_code for o in selected
            ):
                continue
            if any(
                conflicts([m], option.meetings[:i], constraints.buffer_minutes)
                for i, m in enumerate(option.meetings)
            ):
                continue
            if conflicts(option.meetings, constraints.unavailable, 0) or any(
                conflicts(option.meetings, o.meetings, constraints.buffer_minutes)
                for o in fixed + selected
            ):
                continue
            assignments[goal.goal_id] = oid
            search(
                remaining,
                index + 1,
                selected + [option],
                assignments,
                matched,
                credits + option.credits,
                rank + priority,
            )
            del assignments[goal.goal_id]
            if exhausted:
                return

    def match_fixed(index, matched):
        if not tick():
            return
        if index == len(fixed):
            remaining = [g for g in request.goals if g.goal_id not in matched]
            search(remaining, 0, [], matched.copy(), matched, sum(o.credits for o in fixed), 0)
            return
        option = fixed[index]
        matches = [
            (g, oid)
            for g in request.goals
            for oid in g.option_ids
            if same_choice(option, options[oid])
        ]
        if not matches or all(g.goal_id in matched for g, _ in matches):
            match_fixed(index + 1, matched)
        for goal, oid in matches:
            if goal.goal_id not in matched:
                matched[goal.goal_id] = oid
                match_fixed(index + 1, matched)
                del matched[goal.goal_id]
            if exhausted:
                return

    match_fixed(0, {})
    if exhausted:
        return {"status": "blocked", "reason": "Search budget reached; feasibility is unresolved."}
    if best is None:
        unknown = [
            o.option_id for o in request.options if o.eligible is None or not o.schedule_verified
        ]
        return {
            "status": "needs-user" if unknown else "blocked",
            "reason": "No complete combination satisfies known constraints; unknown inputs remain."
            if unknown
            else "No complete combination satisfies known constraints.",
            "unverified_option_ids": unknown,
        }
    _, assignments, selected, credits, matched = best
    return {
        "status": "ready",
        "assignments": assignments,
        "remaining_option_ids": [o.option_id for o in selected],
        "credits": credits,
        "goal_credits": sum(options[oid].credits for oid in assignments.values()),
        "satisfied_goals": matched,
        "reason": "All goals solved together; fixed courses retained. Preferences: fewer dates, later starts, pool order.",
        "warnings": request.limitations
        + [
            f"Exam times unchecked: {o.course_code}"
            for o in fixed + selected
            if not o.exams_checked
        ]
        + [w for o in fixed + selected for w in o.warnings],
    }
