"""Behavioral acceptance for planning and Agent-operated enrolment checkpoints."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import json
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from hsas.application.course_planning import CourseOption, PlanningRequest, WeeklyMeeting, plan
from hsas.cli.app import app
from hsas.core import HIQSCore, HIQSPort, HIQSPortError
from hsas.core.services.course_planning import CoursePlanningService
from hsas.infrastructure.sis.course_info.gateway import SisCourseInfoBrowserGateway
from hsas.infrastructure.storage.json_store import write_json
from hsas.mcp import build_mcp_server
from scripts.package_agent_skills import package_skills


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 17, 1, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, seconds=1):
        self.now += timedelta(seconds=seconds)
        return self.now.isoformat()


def evidence(clock, content="Official test page"):
    return {
        "source": "https://sis.hku.hk/official-test-fixture",
        "locator": "Account term / component row",
        "observed_at": clock().isoformat(),
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
    }


def option(clock, oid="a", course="TEST1001", hour=1, lab=False):
    components = {"lecture": "L1"}
    meetings = [
        {
            "component": "lecture",
            "starts_at": f"2026-11-02T{hour:02}:00:00+08:00",
            "ends_at": f"2026-11-02T{hour + 1:02}:00:00+08:00",
        }
    ]
    if lab:
        components["lab"] = "B1"
        meetings.append(
            {
                "component": "lab",
                "starts_at": "2026-11-03T10:00:00+08:00",
                "ends_at": "2026-11-03T11:00:00+08:00",
            }
        )
    return {
        "option_id": oid,
        "course_code": course,
        "term": "2026-S1",
        "credits": 6,
        "components": components,
        "required_components": list(components),
        "meetings": meetings,
        "schedule_verified": True,
        "eligible": True,
        "eligibility_note": "Fixture verified prerequisites/student limits",
        "evidence": [evidence(clock)],
    }


def request(clock, options=None, goals=None, **constraints):
    options = options or [option(clock)]
    return {
        "account": "local-account",
        "term": "2026-S1",
        "scope": "Fixture-only semester",
        "goals": goals
        or [
            {
                "goal_id": "g1",
                "description": "Approved alternatives",
                "option_ids": [o["option_id"] for o in options],
            }
        ],
        "options": options,
        "constraints": {"min_credits": 6, "max_credits": 30, **constraints},
    }


def observation(clock, options, statuses=None, availability=None, outcomes=None, **kwargs):
    statuses = statuses or {}
    return {
        "account": "local-account",
        "term": "2026-S1",
        "captured_at": clock.advance(),
        "complete": True,
        "authenticated": True,
        "window": "open",
        "evidence": evidence(clock),
        "records": [
            {
                "option": o,
                "status": statuses[o["option_id"]],
                "raw_status": statuses[o["option_id"]],
                "evidence": evidence(clock),
            }
            for o in options
            if o["option_id"] in statuses
        ],
        "availability": {
            o["option_id"]: {
                "status": (availability or {}).get(o["option_id"], "open"),
                "condition_key": (availability or {}).get(o["option_id"], "open") + "-v1",
                "evidence": evidence(clock),
            }
            for o in options
        },
        "attempt_outcomes": outcomes or {},
        **kwargs,
    }


@pytest.fixture
def setup(tmp_path):
    clock = Clock()
    service = CoursePlanningService(tmp_path, clock)
    return service, clock


def create(service, req):
    return service.create({"request": req, "confirmed": True})


def mutate(service, method, run, **kwargs):
    return getattr(service, method)(
        {"run_id": run["run_id"], "expected_revision": run["revision"], "confirmed": True, **kwargs}
    )


def authorized(service, clock, req):
    run = create(service, req)
    return mutate(
        service,
        "authorize",
        run,
        request_sha256=run["request_sha256"],
        authorization={
            "starts_at": clock().isoformat(),
            "expires_at": (clock() + timedelta(hours=2)).isoformat(),
            "check_interval_seconds": 30,
            "max_snapshot_age_seconds": 120,
            "max_attempts": 20,
        },
    )


def reconcile(service, clock, run, statuses=None, **kwargs):
    return mutate(
        service,
        "reconcile",
        run,
        observation=observation(clock, run["request"]["options"], statuses, **kwargs),
    )


def test_failure_replans_approved_alternative_and_success_is_counted_once(setup):
    service, clock = setup
    req = request(clock, [option(clock), option(clock, "b", "TEST1002", 4)])
    run = authorized(service, clock, req)
    run = reconcile(service, clock, run)
    run = mutate(service, "next_action", run)
    attempt = run["action"]["attempt_id"]
    assert run["action"]["option"]["option_id"] == "a"
    run = reconcile(
        service, clock, run, {"a": "absent"}, availability={"a": "full"}, outcomes={attempt: "full"}
    )
    assert run["plan"]["assignments"] == {"g1": "b"}
    run = mutate(service, "next_action", run)
    assert run["action"]["option"]["option_id"] == "b"
    run = reconcile(service, clock, run, {"b": "enrolled"})
    assert run["status"] == "completed"
    assert run["plan"]["credits"] == 6
    assert run["plan"]["remaining_option_ids"] == []
    assert mutate(service, "next_action", run)["action"]["type"] == "none"
    assert not (service.resources_dir / "information.json").exists()


def test_successful_courses_lock_and_remaining_whole_combination_is_solved(setup):
    service, clock = setup
    a = option(clock)
    b = option(clock, "b", "TEST1002", 1)
    c = option(clock, "c", "TEST1003", 4, lab=True)
    req = request(
        clock,
        [a, b, c],
        [
            {"goal_id": "g1", "description": "Required", "option_ids": ["a"]},
            {"goal_id": "g2", "description": "Elective", "option_ids": ["b", "c"]},
        ],
        min_credits=12,
    )
    run = reconcile(service, clock, authorized(service, clock, req), {"a": "enrolled"})
    assert run["plan"]["assignments"] == {"g1": "a", "g2": "c"}
    assert run["plan"]["remaining_option_ids"] == ["c"]
    next_run = mutate(service, "next_action", run)
    assert next_run["action"]["option"]["components"] == {"lecture": "L1", "lab": "B1"}
    assert run["fixed"]["TEST1001"] == CourseOption.model_validate(a).model_dump(mode="json")


def test_global_solver_avoids_greedy_trap_and_respects_exam_lab_and_buffer(setup):
    _, clock = setup
    a, b = option(clock), option(clock, "b", "TEST1002", 4)
    c = option(clock, "c", "TEST1003", 1)
    goals = [
        {"goal_id": "g1", "description": "Alternatives", "option_ids": ["a", "b"]},
        {"goal_id": "g2", "description": "Required", "option_ids": ["c"]},
    ]
    result = plan(PlanningRequest.model_validate(request(clock, [a, b, c], goals)), [], set())
    assert result["assignments"] == {"g1": "b", "g2": "c"}
    b["meetings"].append({**c["meetings"][0], "component": "exam"})
    assert (
        plan(PlanningRequest.model_validate(request(clock, [a, b, c], goals)), [], set())["status"]
        == "blocked"
    )
    b = option(clock, "b", "TEST1002", 2)
    req = PlanningRequest.model_validate(
        request(
            clock,
            [a, b],
            [
                {"goal_id": "g1", "description": "A", "option_ids": ["a"]},
                {"goal_id": "g2", "description": "B", "option_ids": ["b"]},
            ],
            buffer_minutes=10,
        )
    )
    assert plan(req, [], set())["status"] == "blocked"


def test_fixed_goal_matching_explores_overlapping_pools_without_double_credit(setup):
    _, clock = setup
    a, b = option(clock), option(clock, "b", "TEST1002", 4)
    req = PlanningRequest.model_validate(
        request(
            clock,
            [a, b],
            [
                {"goal_id": "g1", "description": "Any", "option_ids": ["a", "b"]},
                {"goal_id": "g2", "description": "Exact", "option_ids": ["a"]},
            ],
            min_credits=12,
        )
    )
    result = plan(req, [CourseOption.model_validate(a)], set())
    assert result["assignments"] == {"g2": "a", "g1": "b"}
    assert result["credits"] == 12


def test_pending_does_not_complete_or_replay_but_other_goals_can_progress(setup):
    service, clock = setup
    a, b = option(clock), option(clock, "b", "TEST1002", 4)
    req = request(
        clock,
        [a, b],
        [
            {"goal_id": "g1", "description": "A", "option_ids": ["a"]},
            {"goal_id": "g2", "description": "B", "option_ids": ["b"]},
        ],
        min_credits=12,
    )
    run = reconcile(service, clock, authorized(service, clock, req))
    run = mutate(service, "next_action", run)
    run = reconcile(service, clock, run, {"a": "pending"})
    assert run["plan"]["pending_goals"] == {"g1": "a"}
    assert run["plan"]["satisfied_goals"] == {}
    run = mutate(service, "next_action", run)
    assert run["action"]["option"]["option_id"] == "b"
    run = reconcile(service, clock, run, {"a": "pending", "b": "enrolled"})
    assert run["status"] == "waiting"
    run = reconcile(service, clock, run, {"a": "enrolled", "b": "enrolled"})
    assert run["status"] == "completed"


def test_timeout_and_restart_require_exact_readback_before_another_submission(setup):
    service, clock = setup
    run = reconcile(service, clock, authorized(service, clock, request(clock)))
    run = mutate(service, "next_action", run)
    service = CoursePlanningService(service.resources_dir, clock)
    run = service.get(run["run_id"])
    assert run["attempts"][0]["status"] == "unknown"
    again = mutate(service, "next_action", run)
    assert again["action"]["type"] == "reconcile"
    again = reconcile(service, clock, again, {"a": "absent"})
    assert again["status"] == "reconciling"  # absence without disposition cannot authorize a replay
    again = reconcile(service, clock, again, {"a": "enrolled"})
    assert again["status"] == "completed"
    assert len(again["attempts"]) == 1
    assert again["background_running"] is False


def test_partial_readback_wrong_account_future_and_stale_revision_are_rejected(setup):
    service, clock = setup
    run = authorized(service, clock, request(clock))
    obs = observation(clock, run["request"]["options"], {"a": "enrolled"}, complete=False)
    run = mutate(service, "reconcile", run, observation=obs)
    assert run["status"] == "reconciling" and not run["fixed"]
    for change in (
        {"account": "wrong"},
        {"term": "wrong"},
        {"captured_at": "2099-01-01T00:00:00Z"},
    ):
        obs = observation(clock, run["request"]["options"], **change)
        with pytest.raises(HIQSPortError):
            mutate(service, "reconcile", run, observation=obs)
    stale = dict(run, revision=-1)
    with pytest.raises(HIQSPortError, match="Stale"):
        mutate(service, "next_action", stale)


def test_authority_is_hash_bound_expires_and_budgets_are_not_success(setup):
    service, clock = setup
    run = create(service, request(clock))
    run = reconcile(service, clock, run)
    assert mutate(service, "next_action", run)["action"]["type"] == "authorize"
    run = service.get(run["run_id"])
    auth = {
        "starts_at": clock().isoformat(),
        "expires_at": (clock() + timedelta(seconds=60)).isoformat(),
        "check_interval_seconds": 30,
        "max_snapshot_age_seconds": 30,
        "max_attempts": 1,
    }
    with pytest.raises(HIQSPortError, match="hash"):
        mutate(service, "authorize", run, request_sha256="wrong", authorization=auth)
    run = mutate(
        service, "authorize", run, request_sha256=run["request_sha256"], authorization=auth
    )
    run = reconcile(service, clock, run)
    clock.advance(61)
    run = mutate(service, "next_action", run)
    assert run["action"]["type"] == "authorize"
    assert not run["attempts"] and run["status"] == "needs-user"


def test_full_pool_waits_closed_window_blocks_and_unknown_eligibility_is_visible(setup):
    service, clock = setup
    run = authorized(service, clock, request(clock))
    run = reconcile(service, clock, run, availability={"a": "full"})
    assert run["status"] == "waiting" and run["next_check_at"]
    run = reconcile(service, clock, run, window="closed")
    assert run["status"] == "blocked"
    req = request(clock)
    req["options"][0]["eligible"] = None
    run = reconcile(service, clock, create(service, req))
    assert run["status"] == "needs-user"
    assert run["plan"]["unverified_option_ids"] == ["a"]


def test_permanent_failure_only_retries_after_conditions_change(setup):
    service, clock = setup
    run = reconcile(service, clock, authorized(service, clock, request(clock)))
    run = mutate(service, "next_action", run)
    aid = run["action"]["attempt_id"]
    run = reconcile(service, clock, run, {"a": "absent"}, outcomes={aid: "ineligible"})
    assert run["status"] == "waiting"
    run = reconcile(service, clock, run, {"a": "absent"})
    assert run["status"] == "waiting"
    obs = observation(clock, run["request"]["options"], {"a": "absent"})
    obs["availability"]["a"]["condition_key"] = "prerequisite-approved-v2"
    run = mutate(service, "reconcile", run, observation=obs)
    assert mutate(service, "next_action", run)["action"]["type"] == "submit"


def test_transient_failure_respects_backoff_then_recovers(setup):
    service, clock = setup
    run = reconcile(service, clock, authorized(service, clock, request(clock)))
    run = mutate(service, "next_action", run)
    aid = run["action"]["attempt_id"]
    run = reconcile(service, clock, run, {"a": "absent"}, outcomes={aid: "transient"})
    assert run["status"] == "waiting"
    assert mutate(service, "next_action", run)["action"]["type"] != "submit"
    clock.advance(31)
    run = service.get(run["run_id"])
    run = reconcile(service, clock, run, {"a": "absent"})
    assert mutate(service, "next_action", run)["action"]["type"] == "submit"


def test_cancel_preserves_unknown_attempt_and_local_account_lock(setup):
    service, clock = setup
    first = reconcile(service, clock, authorized(service, clock, request(clock)))
    first = mutate(service, "next_action", first)
    first = mutate(service, "cancel", first)
    assert first["status"] == "cancelled" and first["attempts"][0]["status"] == "unknown"
    assert mutate(service, "next_action", first)["action"]["type"] == "none"
    second = reconcile(service, clock, authorized(service, clock, request(clock)))
    second = mutate(service, "next_action", second)
    assert second["action"]["type"] == "reconcile-other-task"
    first = service.get(first["run_id"])
    first = reconcile(service, clock, first, {"a": "enrolled"})
    assert first["status"] == "cancelled" and first["fixed"]
    second = reconcile(service, clock, second, {"a": "enrolled"})
    assert second["status"] == "completed"


def test_parallel_reservation_and_manual_external_changes_preserve_successes(setup):
    service, clock = setup
    run = reconcile(service, clock, authorized(service, clock, request(clock)))

    def submit():
        try:
            return mutate(service, "next_action", run)["action"]["type"]
        except HIQSPortError:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: submit(), range(2))) == ["stale", "submit"]
    run = reconcile(service, clock, service.get(run["run_id"]), {"a": "enrolled"})
    run = reconcile(service, clock, run, {"a": "absent"})
    assert run["status"] == "needs-user" and run["fixed"]


def test_weekly_dates_holidays_makeups_and_complete_components(setup):
    _, clock = setup
    weekly = WeeklyMeeting.model_validate(
        {
            "component": "lecture",
            "starts_on": "2026-11-02",
            "ends_on": "2026-11-16",
            "weekday": 0,
            "starts_at": "10:00",
            "ends_at": "11:00",
            "excluded_dates": ["2026-11-09"],
            "additional_dates": ["2026-11-10"],
        }
    )
    assert [m.starts_at.date().isoformat() for m in weekly.expand()] == [
        "2026-11-02",
        "2026-11-10",
        "2026-11-16",
    ]
    a = option(clock, lab=True)
    a["meetings"] = a["meetings"][:1]
    with pytest.raises(ValidationError, match="every component"):
        CourseOption.model_validate(a)
    a["asynchronous_components"] = ["lab"]
    assert CourseOption.model_validate(a).schedule_verified
    req = PlanningRequest.model_validate(request(clock))
    assert plan(req, [], set(), budget=1)["status"] == "blocked"


def test_mcp_roundtrip_and_cli_use_the_same_port(tmp_path):
    clock = Clock()
    core = HIQSCore(tmp_path, clock=clock)
    assert isinstance(core, HIQSPort)
    server = build_mcp_server(core)

    async def call(name, args):
        result = await server.call_tool(name, args)
        assert not result.is_error
        return result.structured_content

    run = asyncio.run(call("create_course_plan", {"request": request(clock), "confirmed": True}))
    run = asyncio.run(
        call(
            "reconcile_course_plan",
            {
                "run_id": run["run_id"],
                "expected_revision": run["revision"],
                "observation": observation(clock, run["request"]["options"], {"a": "enrolled"}),
                "confirmed": True,
            },
        )
    )
    assert run["status"] == "completed"
    result = CliRunner().invoke(
        app, ["--resources", str(tmp_path), "course-planning", "show", "--run-id", run["run_id"]]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["run_id"] == run["run_id"]
    assert json.loads(
        CliRunner().invoke(app, ["--resources", str(tmp_path), "course-planning", "schema"]).output
    )["request"]


def test_explicit_unselected_catalogue_queries_preserve_other_courses(tmp_path):
    gateway = SisCourseInfoBrowserGateway(tmp_path)
    first = {"course_code": "TEST1001", "content_sha256": "old"}
    write_json(gateway.root / "latest.json", {"courses": [first]})
    second = {"course_code": "TEST1002", "content_sha256": "new"}
    gateway._finalize_sync([{"course_code": "TEST1002"}], [], [second], [], retain_unselected=True)
    manifest = json.loads((gateway.root / "latest.json").read_text())
    assert {c["course_code"] for c in manifest["courses"]} == {"TEST1001", "TEST1002"}
    assert [c["action"] for c in manifest["changes"]] == ["added"]
    core = HIQSCore(tmp_path)
    result = Mock(
        status="synced",
        synced_at="today",
        discovered_course_count=1,
        succeeded_course_codes=("TEST1002",),
        unchanged_course_codes=(),
        skipped_course_titles=(),
        failures=(),
    )
    fake = Mock()
    fake.sync.return_value = result
    core.source_service._sis_course_info_factory = lambda _: fake
    core.synchronize_sis_course_info({"course_codes": ["TEST1002"], "confirmed": True})
    fake.sync.assert_called_once_with(
        selected_courses=[
            {"course_code": "TEST1002", "subject_area": "TEST", "catalogue_number": "1002"}
        ],
        preserve_other_courses=True,
    )
    with pytest.raises(HIQSPortError):
        core.synchronize_sis_course_info({"course_codes": ["../../bad"], "confirmed": True})


def test_skill_packaging_and_no_confirmation_or_path_escape(setup, tmp_path):
    service, clock = setup
    with pytest.raises(HIQSPortError):
        service.create({"request": request(clock)})
    with pytest.raises(HIQSPortError):
        service.get("../../information.json")
    with ZipFile(package_skills(tmp_path / "skills.zip")) as archive:
        assert "hiqs-course-planning/SKILL.md" in archive.namelist()
        assert all("resources" not in name for name in archive.namelist())


def test_entire_authorized_execution_roundtrip_through_mcp(tmp_path):
    clock = Clock()
    server = build_mcp_server(HIQSCore(tmp_path, clock=clock))

    async def call(name, args):
        result = await server.call_tool(name, args)
        assert not result.is_error, result
        return result.structured_content

    def operation(name, **args):
        return asyncio.run(call(name, args))

    assert operation("get_course_planning_schema")["authorization"]
    run = operation("create_course_plan", request=request(clock), confirmed=True)
    run = operation(
        "authorize_course_plan",
        run_id=run["run_id"],
        expected_revision=run["revision"],
        request_sha256=run["request_sha256"],
        confirmed=True,
        authorization={
            "starts_at": clock().isoformat(),
            "expires_at": (clock() + timedelta(hours=1)).isoformat(),
            "check_interval_seconds": 30,
            "max_snapshot_age_seconds": 120,
            "max_attempts": 2,
        },
    )
    run = operation(
        "reconcile_course_plan",
        run_id=run["run_id"],
        expected_revision=run["revision"],
        observation=observation(clock, run["request"]["options"]),
        confirmed=True,
    )
    run = operation(
        "next_course_plan_action",
        run_id=run["run_id"],
        expected_revision=run["revision"],
        confirmed=True,
    )
    assert run["action"]["type"] == "submit"
    run = operation(
        "reconcile_course_plan",
        run_id=run["run_id"],
        expected_revision=run["revision"],
        observation=observation(clock, run["request"]["options"], {"a": "pending"}),
        confirmed=True,
    )
    assert run["status"] == "waiting"
    run = operation(
        "reconcile_course_plan",
        run_id=run["run_id"],
        expected_revision=run["revision"],
        observation=observation(clock, run["request"]["options"], {"a": "enrolled"}),
        confirmed=True,
    )
    assert run["status"] == "completed"
    assert operation("get_course_plan", run_id=run["run_id"])["plan"]["credits"] == 6
    assert not (tmp_path / "information.json").exists()


def test_live_qualification_update_and_capacity_reopening_stay_in_pool(setup):
    service, clock = setup
    req = request(clock)
    req["options"][0]["eligible"] = None
    run = authorized(service, clock, req)
    obs = observation(clock, run["request"]["options"])
    obs["availability"]["a"].update(
        eligibility="eligible", eligibility_note="Official approval granted"
    )
    run = mutate(service, "reconcile", run, observation=obs)
    run = mutate(service, "next_action", run)
    assert run["action"]["option"]["eligible"] is True
    aid = run["action"]["attempt_id"]
    obs = observation(
        clock,
        run["request"]["options"],
        {"a": "absent"},
        availability={"a": "full"},
        outcomes={aid: "full"},
    )
    obs["availability"]["a"]["eligibility"] = "eligible"
    run = mutate(service, "reconcile", run, observation=obs)
    assert run["status"] == "waiting"
    obs = observation(clock, run["request"]["options"], {"a": "absent"})
    obs["availability"]["a"]["eligibility"] = "eligible"
    run = mutate(service, "reconcile", run, observation=obs)
    assert mutate(service, "next_action", run)["action"]["type"] == "submit"


def test_attempt_budget_stale_availability_and_service_retry_after(setup):
    service, clock = setup
    run = authorized(service, clock, request(clock))
    run = reconcile(service, clock, run)
    obs = observation(clock, run["request"]["options"])
    obs["availability"]["a"]["evidence"]["observed_at"] = (
        clock() - timedelta(minutes=10)
    ).isoformat()
    run = mutate(service, "reconcile", run, observation=obs)
    run = mutate(service, "next_action", run)
    assert run["action"]["type"] == "reconcile" and not run["attempts"]
    obs = observation(
        clock, run["request"]["options"], retry_after=(clock() + timedelta(minutes=5)).isoformat()
    )
    run = mutate(service, "reconcile", run, observation=obs)
    run = mutate(service, "next_action", run)
    assert run["action"]["type"] == "wait" and not run["attempts"]
    run = reconcile(service, clock, run)
    run = mutate(service, "next_action", run)
    aid = run["action"]["attempt_id"]
    run = reconcile(service, clock, run, {"a": "absent"}, outcomes={aid: "not-submitted"})
    clock.advance(31)
    auth = dict(run["authorization"], max_attempts=1)
    run = mutate(
        service, "authorize", run, request_sha256=run["request_sha256"], authorization=auth
    )
    run = reconcile(service, clock, run)
    run = mutate(service, "next_action", run)
    assert run["status"] == "needs-user" and "budget" in run["reason"]
    assert len(run["attempts"]) == 1


def test_external_courses_count_credits_and_identity_changes_do_not_replace_locked_success(setup):
    service, clock = setup
    req = request(clock, max_credits=6)
    run = authorized(service, clock, req)
    external = option(clock, "external", "ELSE1001", 4)
    obs = observation(clock, run["request"]["options"] + [external], {"external": "enrolled"})
    obs["availability"].pop("external")
    run = mutate(service, "reconcile", run, observation=obs)
    assert run["status"] == "blocked" and run["fixed"]["ELSE1001"]
    changed = observation(clock, run["request"]["options"], {"a": "enrolled"})
    changed["records"][0]["option"]["components"]["lecture"] = "L2"
    with pytest.raises(HIQSPortError, match="changed"):
        mutate(service, "reconcile", run, observation=changed)
    assert service.get(run["run_id"])["fixed"]["ELSE1001"]


def test_corequisites_and_exclusions_are_checked_on_whole_combination(setup):
    _, clock = setup
    a, b, c = option(clock), option(clock, "b", "TEST1002", 4), option(clock, "c", "TEST1003", 7)
    a["corequisite_courses"] = ["TEST1002"]
    goals = [
        {"goal_id": "g1", "description": "A", "option_ids": ["a"]},
        {"goal_id": "g2", "description": "B or C", "option_ids": ["c", "b"]},
    ]
    result = plan(PlanningRequest.model_validate(request(clock, [a, b, c], goals)), [], set())
    assert result["assignments"] == {"g1": "a", "g2": "b"}
    b["excluded_courses"] = ["TEST1001"]
    assert (
        plan(PlanningRequest.model_validate(request(clock, [a, b, c], goals)), [], set())["status"]
        == "blocked"
    )


def test_plan_history_keeps_rebuildable_input_snapshots(setup):
    service, clock = setup
    run = reconcile(service, clock, authorized(service, clock, request(clock)))
    digest = run["plans"][0]["observation_sha256"]
    before = service.get(run["run_id"], digest)["historical_observation"]
    run = reconcile(service, clock, run, {"a": "enrolled"})
    assert service.get(run["run_id"], digest)["historical_observation"] == before
    assert service.get(run["run_id"])["observation"] != before
    with pytest.raises(HIQSPortError, match="hash"):
        service.get(run["run_id"], "../../information")


def test_two_existing_alternatives_preserved_but_goal_counted_once(setup):
    service, clock = setup
    run = authorized(
        service, clock, request(clock, [option(clock), option(clock, "b", "TEST1002", 4)])
    )
    run = reconcile(service, clock, run, {"a": "enrolled", "b": "enrolled"})
    assert run["status"] == "completed"
    assert len(run["plan"]["satisfied_goals"]) == 1
    assert len(run["fixed"]) == 2
    assert run["plan"]["goal_credits"] == 6
    assert run["plan"]["credits"] == 12  # actual total includes both existing courses


def test_stale_component_evidence_cannot_lock_courses_or_complete_task(setup):
    service, clock = setup
    run = authorized(service, clock, request(clock))
    obs = observation(clock, run["request"]["options"], {"a": "enrolled"})
    obs["records"][0]["evidence"]["observed_at"] = (clock() - timedelta(minutes=10)).isoformat()
    run = mutate(service, "reconcile", run, observation=obs)
    assert run["status"] == "reconciling" and not run["fixed"]


def test_official_choice_alias_still_resolves_unknown_submission(setup):
    service, clock = setup
    run = reconcile(service, clock, authorized(service, clock, request(clock)))
    run = mutate(service, "next_action", run)
    obs = observation(clock, run["request"]["options"], {"a": "enrolled"})
    obs["records"][0]["option"]["option_id"] = "official-roster-alias"
    run = mutate(service, "reconcile", run, observation=obs)
    assert run["status"] == "completed"
    assert run["attempts"][0]["status"] == "enrolled"
