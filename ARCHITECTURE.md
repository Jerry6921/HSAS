# HSAS architecture

## Dependency rule

Dependencies point inward:

```text
command / AI_interface adapters
             |
             v
      hsas_application use cases
             |
             v
 integrated_planner domain rules
             ^
             |
moodle_collector public contracts

hsas_runtime supplies platform paths and generic atomic persistence.
Playwright, Typer, filesystem layout, and update transport stay outside planning rules.
```

External consumers import course models from `moodle_collector.contracts`, not
from transformation internals. Application services return results or typed
errors; CLI adapters own presentation and exit codes.

## Course synchronization transaction

One course is built as an isolated snapshot:

```text
copy last-known-good snapshot to staging
  -> map raw Moodle state
  -> download/revalidate files
  -> analyze PDFs
  -> build assessments and changes
  -> validate staged course.json
  -> journaled directory swap
```

The live course directory is unchanged until validation succeeds. A per-course
lock prevents concurrent writers. The recovery journal restores the previous
directory after an interrupted swap.

`sync-report.json` schema 2 retains per-course outcomes across single-course and
full synchronization operations.

## Planning consistency

`IntegratedPlan.source_snapshot` records Profile, Execution Log, and CourseArchive
revisions. `assess_plan_freshness` compares those revisions with current inputs
and exposes synchronization failures. Confirmed Profile/Execution mutations and
successful course syncs request an automatic replan. If planning fails, confirmed
inputs and the prior valid Plan remain intact and status reports the Plan as stale.

## Update trust boundary

The in-place updater cannot mutate dependencies. HTTPS releases require a
two-step flow: dry-run to obtain a full Git commit, then an explicit run pinned to
that exact commit. Dependency changes require a normal package-manager upgrade.
