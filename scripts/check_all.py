"""Run every gate CI enforces, locally, in one command.

This is the single verification entry point. A green run here means the same
things a green CI run means, so an agent does not have to rediscover the four
separate commands from ``.github/workflows/quality.yml``.

Usage:
    python scripts/check_all.py            # all gates
    python scripts/check_all.py --fast     # skip the test suite

Exit code is 0 only when every gate passed.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

# ``python scripts/check_all.py`` puts ``scripts/`` on sys.path, not the repo root.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# The package is installed editable in CI; fall back to the source tree otherwise.
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _run(label: str, command: list[str]) -> bool:
    print(f"\n=== {label} ===", flush=True)
    started = time.perf_counter()
    completed = subprocess.run(  # noqa: S603 - fixed, reviewed argument lists
        command,
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    elapsed = time.perf_counter() - started
    status = "PASS" if completed.returncode == 0 else "FAIL"
    print(f"--- {status}: {label} ({elapsed:.1f}s)", flush=True)
    return completed.returncode == 0


def _check_generated(label: str, path: Path, expected: str) -> bool:
    print(f"\n=== {label} ===", flush=True)
    actual = path.read_text(encoding="utf-8") if path.exists() else ""
    if actual == expected:
        print(f"--- PASS: {label}", flush=True)
        return True
    print(f"Stale generated file: {path.relative_to(ROOT)}", file=sys.stderr)
    print("Regenerate it; do not edit it by hand.", file=sys.stderr)
    print(f"--- FAIL: {label}", flush=True)
    return False


def _contract_checks() -> list[bool]:
    from scripts.generate_agent_contracts import render_contract_document
    from scripts.generate_notes_contracts import render_notes_contracts
    from scripts.generate_tool_profiles import render_tool_profiles

    return [
        _check_generated(
            "Agent evidence contract",
            ROOT / "contracts/agent-evidence.schema.json",
            render_contract_document(),
        ),
        _check_generated(
            "Course notes contract",
            ROOT / "contracts/course-notes.schema.json",
            render_notes_contracts(),
        ),
        _check_generated(
            "MCP tool profiles",
            ROOT / "contracts/mcp-tool-profiles.json",
            render_tool_profiles(),
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fast",
        action="store_true",
        help="skip the test suite; lint and contract gates still run",
    )
    args = parser.parse_args()

    results = {
        "lint": _run("Lint", [PY, "-m", "ruff", "check", "src", "tests", "scripts"]),
    }
    results.update({f"contract[{index}]": ok for index, ok in enumerate(_contract_checks())})
    if not args.fast:
        results["tests"] = _run(
            "Tests",
            [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        )

    failed = [name for name, ok in results.items() if not ok]
    print("\n" + "=" * 60)
    if failed:
        print(f"FAILED ({len(failed)}/{len(results)}): {', '.join(failed)}")
        return 1
    print(f"All {len(results)} gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
