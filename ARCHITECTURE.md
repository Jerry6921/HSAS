# HSAS architecture

## Dependency rule

Dependencies point inward:

```text
hsas.interfaces
      |
      v
hsas.application
      |
      v
hsas.domain

hsas.infrastructure implements Moodle, documents, storage, runtime, and updates.
```

Folders are nouns that express architectural ownership. Ordinary Python module
names are verb phrases that express behavior; Python-required `__init__.py` and
`__main__.py` are the only source-module exceptions. Domain modules do not import
Typer, Playwright, platform paths, filesystem persistence, or update transport.
Application services return results or typed errors; interface adapters own
presentation and exit codes; infrastructure owns external and filesystem effects.

```text
src/hsas/
├── interfaces/       # CLI, local web UI, and agent adapters
├── application/      # synchronization, planning, retrieval, Profile/Execution use cases
├── domain/
│   ├── courses/      # course, assessment, document contracts and rules
│   └── planning/     # Profile, Execution, Plan models and deterministic rules
└── infrastructure/
    ├── moodle/       # browser/API acquisition and Moodle transformation
    ├── documents/    # PDF analysis
    ├── storage/      # atomic persistence and snapshot publication
    ├── runtime/      # platform paths and migration
    └── updates/      # pinned Git release updates
```

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

## Local dashboard boundary

`hsas ui` binds only to `127.0.0.1` and serves packaged static assets plus a small JSON API.
Read operations validate the same domain models used by the CLI. Confirmed execution writes call
the application service and request a validated replan; synchronization calls the existing
Collector transaction. The UI never patches Profile, CourseArchive, Execution Log, or Integrated
Plan JSON directly. Write requests require JSON plus a custom local-request header, and the server
does not enable cross-origin access.

## Update trust boundary

The in-place updater cannot mutate dependencies. HTTPS releases require a
two-step flow: dry-run to obtain a full Git commit, then an explicit run pinned to
that exact commit. Dependency changes require a normal package-manager upgrade.
