"""Durable Agent-driven enrolment transactions, independent of course facts.

A returned submit action is a one-time reservation, not an SIS HTTP request.
The Agent operates the authenticated official UI and supplies fresh readback.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from pydantic import ValidationError

from hsas.application.course_planning import (
    Authorization,
    CourseOption,
    Observation,
    PlanningRequest,
    plan,
    same_choice,
)
from hsas.core.ports import HIQSPortError
from hsas.infrastructure.storage.json_store import read_json, write_json


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(slots=True)
class CoursePlanningService:
    resources_dir: Path
    clock: Callable[[], datetime]

    @property
    def root(self):
        return self.resources_dir / "course-planning"

    def schema(self):
        return {
            "request": PlanningRequest.model_json_schema(),
            "observation": Observation.model_json_schema(),
            "authorization": Authorization.model_json_schema(),
        }

    @contextmanager
    def _lock(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _path(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise HIQSPortError("Invalid planning run ID.")
        return self.root / run_id / "state.json"

    def _read(self, run_id):
        try:
            state = read_json(self._path(run_id))
            if state["schema_version"] != "1.0":
                raise ValueError("Unsupported planning checkpoint version")
            return state
        except (OSError, ValueError, KeyError) as exc:
            raise HIQSPortError(f"Cannot read planning checkpoint: {exc}") from exc

    def _write(self, state):
        state["revision"] += 1
        path = self._path(state["run_id"])
        write_json(path, state)
        if read_json(path) != state:
            raise HIQSPortError("Planning checkpoint readback failed.")

    def _confirmed(self, payload):
        if payload.get("confirmed") is not True:
            raise HIQSPortError("This operation requires confirmed=true and the stated user scope.")

    def _revision(self, state, payload):
        revision = payload.get("expected_revision")
        if type(revision) is not int or state["revision"] != revision:
            raise HIQSPortError("Stale planning revision; read the checkpoint before retrying.")

    def _validate(self, model, value):
        try:
            return model.model_validate(value)
        except (ValidationError, TypeError) as exc:
            raise HIQSPortError(f"Invalid planning input: {exc}") from exc

    def create(self, payload):
        self._confirmed(payload)
        request = self._validate(PlanningRequest, payload.get("request"))
        state = {
            "schema_version": "1.0",
            "run_id": uuid4().hex,
            "revision": -1,
            "created_at": self.clock().isoformat(),
            "request": request.model_dump(mode="json"),
            "request_sha256": fingerprint(request.model_dump(mode="json")),
            "authorization": None,
            "observation": None,
            "fixed": {},
            "attempts": [],
            "plans": [],
            "status": "planning",
            "reason": "Read the official account and candidate state.",
            "next_check_at": None,
            "cancelled_at": None,
        }
        with self._lock():
            self._write(state)
        return self._report(state)

    def get(self, run_id=None, observation_sha256=None):
        with self._lock():
            if run_id is None:
                return {
                    "runs": [
                        {
                            key: state[key]
                            for key in ("run_id", "revision", "status", "reason", "created_at")
                        }
                        for path in sorted(self.root.glob("*/state.json"))
                        for state in [read_json(path)]
                    ]
                }
            state = self._read(run_id)
            report = self._report(state)
            if observation_sha256 is not None:
                if not isinstance(observation_sha256, str) or not re.fullmatch(
                    r"[a-f0-9]{64}", observation_sha256
                ):
                    raise HIQSPortError("Invalid observation hash.")
                try:
                    snapshot = read_json(
                        self._path(run_id).parent / "observations" / f"{observation_sha256}.json"
                    )
                    if fingerprint(snapshot) != observation_sha256:
                        raise ValueError("Historical observation hash mismatch")
                except (OSError, ValueError) as exc:
                    raise HIQSPortError(f"Cannot read historical observation: {exc}") from exc
                report["historical_observation"] = snapshot
            return report

    def authorize(self, payload):
        self._confirmed(payload)
        authorization = self._validate(Authorization, payload.get("authorization"))
        if authorization.expires_at <= self.clock():
            raise HIQSPortError("Authorization has already expired.")
        with self._lock():
            state = self._read(payload.get("run_id"))
            self._revision(state, payload)
            if state["cancelled_at"]:
                raise HIQSPortError("Cancelled tasks remain cancelled; create a new task.")
            if payload.get("request_sha256") != state["request_sha256"]:
                raise HIQSPortError("Authorization must bind the exact reviewed request hash.")
            state["authorization"] = authorization.model_dump(mode="json")
            state["status"], state["reason"] = (
                "reconciling",
                "Authorization saved; refresh official state before submission.",
            )
            # A new authorization cannot reuse an earlier observation for submission.
            state["authorization_observed_after"] = self.clock().isoformat()
            self._write(state)
            return self._report(state)

    def reconcile(self, payload):
        self._confirmed(payload)
        observation = self._validate(Observation, payload.get("observation"))
        now = self.clock()
        if observation.captured_at > now:
            raise HIQSPortError("Observation cannot be from the future.")
        with self._lock():
            state = self._read(payload.get("run_id"))
            self._revision(state, payload)
            request = PlanningRequest.model_validate(state["request"])
            if observation.account != request.account or observation.term != request.term:
                raise HIQSPortError("Observation account/term does not match the task.")
            if state["observation"] and observation.captured_at <= datetime.fromisoformat(
                state["observation"]["captured_at"]
            ):
                raise HIQSPortError("Observation must be newer than the saved snapshot.")
            choices = {o.option_id: o for o in request.options}
            if not set(observation.availability) <= choices.keys():
                raise HIQSPortError("Availability names an option outside the approved pool.")
            for record in observation.records:
                if record.option.option_id in choices and not same_choice(
                    record.option, choices[record.option.option_id]
                ):
                    raise HIQSPortError(
                        "Candidate identity/schedule changed; review a new request."
                    )
            unresolved_ids = {
                a["attempt_id"]
                for a in state["attempts"]
                if a["status"] in {"unknown", "pending", "waitlisted"}
            }
            if not set(observation.attempt_outcomes) <= unresolved_ids:
                raise HIQSPortError("Outcome refers to a settled or unknown attempt.")
            state["observation"] = observation.model_dump(mode="json")
            records = {r.option.option_id: r for r in observation.records}
            # Every official success is locked, including courses enrolled manually.
            freshness = (state["authorization"] or {}).get("max_snapshot_age_seconds", 300)
            fresh = all(
                (now - e.observed_at).total_seconds() <= freshness
                for e in [observation.evidence] + [r.evidence for r in observation.records]
            )
            if observation.authenticated and observation.complete and fresh:
                for record in observation.records:
                    if record.status == "enrolled":
                        existing = state["fixed"].get(record.option.course_code)
                        if existing and not same_choice(
                            CourseOption.model_validate(existing), record.option
                        ):
                            # Keep the original lock so a manual section change requires a decision.
                            continue
                        state["fixed"][record.option.course_code] = record.option.model_dump(
                            mode="json"
                        )
                for attempt in state["attempts"]:
                    if attempt["status"] not in {"unknown", "pending", "waitlisted"}:
                        continue
                    record = records.get(attempt["option_id"]) or next(
                        (
                            r
                            for r in observation.records
                            if same_choice(r.option, choices[attempt["option_id"]])
                        ),
                        None,
                    )
                    submitted = datetime.fromisoformat(attempt["prepared_at"])
                    if (
                        observation.captured_at <= submitted
                        or record is None
                        or record.evidence.observed_at <= submitted
                    ):
                        continue
                    if record.status in {"enrolled", "pending", "waitlisted"}:
                        attempt["status"] = record.status
                        attempt["readback"] = record.model_dump(mode="json")
                    elif (
                        record.status == "absent"
                        and attempt["attempt_id"] in observation.attempt_outcomes
                    ):
                        attempt["status"] = "failed"
                        attempt["failure"] = observation.attempt_outcomes[attempt["attempt_id"]]
                        current_condition = observation.availability.get(attempt["option_id"])
                        if current_condition:
                            attempt["condition_key"] = current_condition.condition_key
                        attempt["readback"] = record.model_dump(mode="json")
                        interval = (state["authorization"] or {}).get("check_interval_seconds", 60)
                        retry = now + timedelta(seconds=interval)
                        if observation.retry_after:
                            retry = max(retry, observation.retry_after)
                        attempt["retry_not_before"] = retry.isoformat()
            self._refresh(state)
            snapshot_hash = fingerprint(state["observation"])
            snapshot_path = (
                self._path(state["run_id"]).parent / "observations" / f"{snapshot_hash}.json"
            )
            if snapshot_path.exists() and read_json(snapshot_path) != state["observation"]:
                raise HIQSPortError(
                    "Historical observation is corrupted; no state replacement performed."
                )
            if not snapshot_path.exists():
                write_json(snapshot_path, state["observation"])
            if read_json(snapshot_path) != state["observation"]:
                raise HIQSPortError("Observation readback failed.")
            self._write(state)
            return self._report(state)

    def _refresh(self, state):
        if state["cancelled_at"]:
            state["status"], state["reason"] = (
                "cancelled",
                "Cancelled; existing courses and unresolved receipts retained.",
            )
            return
        if not state["observation"]:
            state["status"], state["reason"] = (
                "reconciling",
                "Read the official account roster and candidate state.",
            )
            return
        observation = Observation.model_validate(state["observation"])
        request = PlanningRequest.model_validate(state["request"])
        state["next_check_at"] = None
        if not observation.authenticated:
            state["status"], state["reason"] = (
                "needs-user",
                "Complete official authentication, then reconcile.",
            )
            return
        if not observation.complete:
            state["status"], state["reason"] = (
                "reconciling",
                "Full active/pending account roster is required.",
            )
            return
        actual = [r.option for r in observation.records if r.status == "enrolled"]
        freshness = (state["authorization"] or {}).get("max_snapshot_age_seconds", 300)
        if any(
            (self.clock() - e.observed_at).total_seconds() > freshness
            for e in [observation.evidence] + [r.evidence for r in observation.records]
        ):
            state["status"], state["reason"] = "reconciling", "Official roster evidence is stale."
            return
        if any(r.status == "unknown" for r in observation.records):
            state["status"], state["reason"] = (
                "reconciling",
                "Unknown account request status; clarify official disposition.",
            )
            return
        for locked in state["fixed"].values():
            locked_option = CourseOption.model_validate(locked)
            if not any(same_choice(locked_option, o) for o in actual):
                state["status"], state["reason"] = (
                    "needs-user",
                    "A locked course was changed/removed externally; reconcile the user decision.",
                )
                return
        if any(a["status"] == "unknown" for a in state["attempts"]):
            state["status"], state["reason"] = (
                "reconciling",
                "Submission result unknown; query its exact course/components before retrying.",
            )
            return
        # Qualification observations may change while the authorized option identities
        # and constraints remain fixed (e.g. an official prerequisite approval).
        for option in request.options:
            availability = observation.availability.get(option.option_id)
            if availability and availability.eligibility != "unchanged":
                option.eligible = {"eligible": True, "ineligible": False, "unknown": None}[
                    availability.eligibility
                ]
                option.eligibility_note = availability.eligibility_note or option.eligibility_note
        unavailable = {
            oid
            for oid, value in observation.availability.items()
            if value.status in {"full", "closed", "ineligible"}
        }
        for attempt in state["attempts"]:
            if attempt["status"] == "failed":
                availability = observation.availability.get(attempt["option_id"])
                retryable = attempt["failure"] in {"transient", "authentication", "not-submitted"}
                if retryable:
                    if self.clock() < datetime.fromisoformat(attempt["retry_not_before"]):
                        unavailable.add(attempt["option_id"])
                elif availability is None or availability.condition_key == attempt["condition_key"]:
                    unavailable.add(attempt["option_id"])
        pending_records = [r for r in observation.records if r.status in {"pending", "waitlisted"}]
        choices = {o.option_id: o for o in request.options}
        if any(
            a["status"] in {"pending", "waitlisted"}
            and not any(
                same_choice(r.option, choices[a["option_id"]])
                and r.status in {"enrolled", "pending", "waitlisted"}
                for r in observation.records
            )
            for a in state["attempts"]
        ):
            state["status"], state["reason"] = (
                "waiting",
                "Previously pending request needs an explicit official disposition.",
            )
            self._wait(state, observation)
            return
        reserved = [r.option for r in pending_records]
        result = plan(request, actual + reserved, unavailable)
        if result["status"] == "ready":
            pending_goals = {
                g: oid
                for g, oid in result["satisfied_goals"].items()
                if any(
                    same_choice(next(o for o in request.options if o.option_id == oid), p)
                    for p in reserved
                )
            }
            result["pending_goals"] = pending_goals
            result["satisfied_goals"] = {
                g: oid for g, oid in result["satisfied_goals"].items() if g not in pending_goals
            }
        state["plan"] = result
        if not state["plans"] or fingerprint(result) != fingerprint(state["plans"][-1]["result"]):
            state["plans"].append(
                {
                    "version": len(state["plans"]) + 1,
                    "observation_sha256": fingerprint(state["observation"]),
                    "created_at": self.clock().isoformat(),
                    "result": result,
                }
            )
        if result["status"] == "ready" and not result["remaining_option_ids"]:
            if result.get("pending_goals"):
                state["status"], state["reason"] = (
                    "waiting",
                    "Goals still pending/waitlisted; preserve requests and await official approval.",
                )
                self._wait(state, observation)
            else:
                state["status"], state["reason"] = (
                    "completed",
                    "All goals and credits satisfied by exact official readback.",
                )
        elif observation.window == "closed":
            state["status"], state["reason"] = (
                "blocked",
                "Enrolment window closed; outstanding goals retained.",
            )
        elif observation.window in {"not-open", "unknown"}:
            state["status"], state["reason"] = (
                "waiting",
                "Wait for a verified open enrolment window.",
            )
            self._wait(state, observation)
        elif result["status"] != "ready":
            temporarily_unavailable = (
                unavailable and plan(request, actual + reserved, set())["status"] == "ready"
            )
            if temporarily_unavailable:
                state["status"], state["reason"] = (
                    "waiting",
                    "No executable combination; refresh capacity/conditions before replanning.",
                )
                self._wait(state, observation)
            else:
                state["status"], state["reason"] = result["status"], result["reason"]
        else:
            state["status"], state["reason"] = (
                "planning",
                "Complete plan ready; execution requires scoped authorization and fresh evidence.",
            )

    def _wait(self, state, observation):
        authorization = state["authorization"]
        if authorization:
            interval = authorization["check_interval_seconds"]
            next_check = self.clock() + timedelta(seconds=interval)
            if observation.retry_after:
                next_check = max(next_check, observation.retry_after)
            state["next_check_at"] = next_check.isoformat()

    def next_action(self, payload):
        """Atomically reserve at most one submission; repeat calls demand readback."""
        self._confirmed(payload)
        with self._lock():
            state = self._read(payload.get("run_id"))
            self._revision(state, payload)
            self._refresh(state)
            action = {"type": "none", "reason": state["reason"]}
            if (
                state["authorization"]
                and self.clock() >= datetime.fromisoformat(state["authorization"]["expires_at"])
                and state["status"] not in {"completed", "cancelled"}
                and not any(a["status"] == "unknown" for a in state["attempts"])
            ):
                action = self._prepare(state)
            elif state["status"] == "reconciling":
                action["type"] = "reconcile"
            elif state["status"] == "planning":
                action = self._prepare(state)
            self._write(state)
            return self._report(state) | {"action": action}

    def _prepare(self, state):
        now = self.clock()
        if not state["authorization"]:
            state["status"], state["reason"] = (
                "needs-user",
                "Authorize the exact request before real enrolment.",
            )
            return {"type": "authorize", "request_sha256": state["request_sha256"]}
        authorization = Authorization.model_validate(state["authorization"])
        if now >= authorization.expires_at:
            state["status"], state["reason"] = (
                "needs-user",
                "Authorization expired; no further submissions.",
            )
            return {"type": "authorize", "reason": state["reason"]}
        if now < authorization.starts_at:
            state["status"], state["reason"] = (
                "waiting",
                "Authorization execution window has not opened.",
            )
            state["next_check_at"] = authorization.starts_at.isoformat()
            return {"type": "wait", "reason": state["reason"]}
        observation = Observation.model_validate(state["observation"])
        after = datetime.fromisoformat(state["authorization_observed_after"])
        evidence_times = [observation.evidence.observed_at] + [
            r.evidence.observed_at for r in observation.records
        ]
        if observation.captured_at < after or any(
            (now - timestamp).total_seconds() > authorization.max_snapshot_age_seconds
            for timestamp in [observation.captured_at] + evidence_times
        ):
            state["status"], state["reason"] = (
                "reconciling",
                "Official snapshot is stale or predates authorization.",
            )
            return {"type": "reconcile", "reason": state["reason"]}
        if len(state["attempts"]) >= authorization.max_attempts:
            state["status"], state["reason"] = (
                "needs-user",
                "Authorized attempt budget exhausted; checkpoint retained.",
            )
            return {"type": "authorize", "reason": state["reason"]}
        # A lock spans all local tasks. An interrupted reservation must be reconciled
        # even if its owning task has since been cancelled or its authority expired.
        request = state["request"]
        for path in self.root.glob("*/state.json"):
            other = read_json(path)
            if (
                other["run_id"] != state["run_id"]
                and (other["request"]["account"], other["request"]["term"])
                == (request["account"], request["term"])
                and any(a["status"] == "unknown" for a in other["attempts"])
            ):
                state["status"], state["reason"] = (
                    "blocked",
                    "Another local task has an unreconciled submission for this account/term.",
                )
                return {"type": "reconcile-other-task", "run_id": other["run_id"]}
        if observation.retry_after and now < observation.retry_after:
            state["status"], state["reason"] = "waiting", "Official service requested backoff."
            state["next_check_at"] = observation.retry_after.isoformat()
            return {"type": "wait", "reason": state["reason"]}
        oid = state["plan"]["remaining_option_ids"][0]
        availability = observation.availability.get(oid)
        if (
            availability is None
            or availability.status != "open"
            or (now - availability.evidence.observed_at).total_seconds()
            > authorization.max_snapshot_age_seconds
        ):
            state["status"], state["reason"] = (
                "reconciling",
                "Refresh official availability for the next exact combination.",
            )
            return {"type": "reconcile", "reason": state["reason"]}
        option = dict(next(o for o in request["options"] if o["option_id"] == oid))
        if availability.eligibility != "unchanged":
            option["eligible"] = {"eligible": True, "ineligible": False, "unknown": None}[
                availability.eligibility
            ]
            option["eligibility_note"] = availability.eligibility_note or option["eligibility_note"]
            option["evidence"] = option["evidence"] + [
                availability.evidence.model_dump(mode="json")
            ]
        attempt = {
            "attempt_id": uuid4().hex,
            "option_id": oid,
            "plan_version": state["plans"][-1]["version"],
            "prepared_at": now.isoformat(),
            "condition_key": availability.condition_key,
            "status": "unknown",
            "observation_sha256": fingerprint(state["observation"]),
        }
        state["attempts"].append(attempt)
        state["status"], state["reason"] = (
            "executing",
            "One submission reserved; read back official state afterwards, including on timeout.",
        )
        return {
            "type": "submit",
            "attempt_id": attempt["attempt_id"],
            "option": option,
            "account": request["account"],
            "term": request["term"],
            "valid_until": min(
                authorization.expires_at,
                observation.captured_at + timedelta(seconds=authorization.max_snapshot_age_seconds),
            ).isoformat(),
            "preflight_observation_sha256": attempt["observation_sha256"],
            "instruction": "Recheck account, term, current roster and exact components immediately; execute add/enrol only, then reconcile. Never replay this reservation.",
        }

    def cancel(self, payload):
        self._confirmed(payload)
        with self._lock():
            state = self._read(payload.get("run_id"))
            self._revision(state, payload)
            state["cancelled_at"] = self.clock().isoformat()
            self._refresh(state)
            self._write(state)
            return self._report(state)

    def _report(self, state):
        # Read-only reporting computes expiry without changing checkpoints.
        report = json.loads(json.dumps(state))
        authorization = report["authorization"]
        report["authorization_active"] = bool(
            authorization
            and not report["cancelled_at"]
            and datetime.fromisoformat(authorization["starts_at"])
            <= self.clock()
            < datetime.fromisoformat(authorization["expires_at"])
        )
        if (
            authorization
            and self.clock() >= datetime.fromisoformat(authorization["expires_at"])
            and report["status"] not in {"completed", "cancelled"}
        ):
            report["status"], report["reason"] = (
                "needs-user",
                "Authorization expired; reconcile receipts and renew scope before submissions.",
            )
        report["verified_as_of"] = (
            report["observation"]["captured_at"] if report["observation"] else None
        )
        report["executor"] = "foreground-agent"
        report["background_running"] = False
        report["verification"] = (
            "Agent-supplied official-page evidence; not independently fetched by this service."
        )
        report["checkpoint_path"] = str(self._path(state["run_id"]).resolve())
        return report
