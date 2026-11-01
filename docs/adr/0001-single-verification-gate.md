# ADR 0001 — One verification gate, and what is deliberately not gated yet

- Status: accepted
- Date: 2026-11-02

## Context

CI enforced four separate checks (ruff, two regenerated contract snapshots, generated
UI/TypeScript contracts, pytest). Locally that meant reconstructing the list from
`.github/workflows/quality.yml` on every task. Two failure modes followed:

1. A person or agent runs two of the four gates, reports success, and CI fails later on a
   stale contract. The feedback loop is long and the failure looks mysterious.
2. The four steps drift: a gate is added to CI and never to anyone's local habit.

The default suite is a couple of seconds offline with the `slow` marker excluded, which
makes a single combined gate cheap enough to run on every task.

## Decision

- `scripts/check_all.py` is the single local verification gate. It runs lint, both
  committed JSON contract snapshots (compared in memory against the generator's own
  render functions, so the check never rewrites files), and the default test suite.
  `--fast` skips only the test suite.
- The Definition of Done in `docs/agents/engineering-management.md` names this script and
  nothing else. If a gate exists in CI and not in the script, the script is incomplete.
- The script is the contract between "green locally" and "green in CI"; keep those two
  meanings identical.

## Explicitly deferred

**Static type checking.** `ruff` runs only `E9,F` (syntax and pyflakes), so a wrong type is
caught by tests or at runtime, never by the linter. Around 75% of modules already carry
return annotations, so a checker would pay off. It is deferred, not rejected, because
adopting one requires three things in the same change: a new dev dependency resolved into
`requirements.lock`, a measured error baseline, and per-package gating that is honest about
what is actually checked. A checker that is added but not enforced in CI is worse than
none — it produces output nobody acts on.

**Splitting files above ~800 lines.** `material_search.py`, the Moodle gateway and the
dashboard projection are each large enough to cost an agent context and raise mis-edit
risk. Splitting them is a real improvement, but it is a behaviour-preserving refactor with
no test-visible signal; it should be done when that file is already being changed for a
functional reason, not as a standalone campaign.

## Consequences

- One command, one exit code, one meaning. An agent that reports "checks pass" has a
  single verifiable claim behind it.
- The in-memory contract comparison means running the gate never mutates the working tree.
- The deferred items are recorded with their cost, so a later session does not relitigate
  them from zero or, worse, adopt them half-way.
