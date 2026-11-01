"""The local gate and CI must not drift apart.

``scripts/check_all.py`` is the only thing an agent runs, and it is trusted
because a green run means what a green CI run means. That promise is kept by
comparing the two definitions here rather than by anyone remembering.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
GATE = (ROOT / "scripts" / "check_all.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")


def test_local_and_ci_require_the_same_coverage() -> None:
    local = re.search(r"^COVERAGE_MIN = (\d+)$", GATE, re.MULTILINE)
    assert local, "the local gate stopped declaring a coverage threshold"
    assert "--cov-fail-under={COVERAGE_MIN}" in GATE, (
        "the local gate declares a threshold it does not pass to pytest"
    )
    ci = re.search(r"--cov-fail-under=(\d+)", WORKFLOW)
    assert ci, "CI stopped enforcing coverage"
    assert local.group(1) == ci.group(1), (
        f"local gate demands {local.group(1)}%, CI demands {ci.group(1)}%"
    )


def test_local_gate_runs_the_lint_and_test_steps_ci_runs() -> None:
    assert '"check", "src", "tests", "scripts"' in GATE, "local lint targets changed"
    assert "ruff check src tests scripts" in WORKFLOW, "CI lint targets changed"
    assert '"pytest"' in GATE and "pytest" in WORKFLOW
    assert "no:cacheprovider" in GATE and "no:cacheprovider" in WORKFLOW


def _step_blocks() -> list[list[str]]:
    blocks: list[list[str]] = []
    for line in WORKFLOW.splitlines():
        if line.strip().startswith("- name:"):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
    return blocks


def test_coverage_is_enforced_on_exactly_one_interpreter_leg() -> None:
    """A version-dependent threshold enforced on every leg is a flaky gate."""
    steps = [block for block in _step_blocks() if any("cov-fail-under" in line for line in block)]
    assert len(steps) == 1, "coverage is enforced in more than one CI step"
    guards = [line.strip() for line in steps[0] if "python-version" in line and "if:" in line]
    assert guards == ["if: matrix.python-version == '3.13'"], guards


def test_every_interpreter_still_runs_the_suite() -> None:
    plain = [block for block in _step_blocks() if any(
        "pytest" in line and "cov" not in line for line in block
    )]
    assert plain, "no CI step runs the suite without coverage"
    assert any("python-version != '3.13'" in line for block in plain for line in block)


def test_every_committed_contract_is_checked_locally() -> None:
    for contract in sorted((ROOT / "contracts").glob("*.json")):
        assert contract.name in GATE, (
            f"{contract.name} is committed but the local gate never compares it"
        )


def test_the_gate_does_not_reference_removed_scripts() -> None:
    assert "check_generated.py" not in GATE
