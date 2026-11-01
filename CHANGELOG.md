# Changelog

All notable changes to HIQS are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
Semantic Versioning.

## [2.12.0] - 2026-11-02

### Added

- Notion delivery: projection from canonical facts, staged original-file uploads,
  a controls queue, idempotent upsert keyed by stable local IDs, and an export
  package guarded by confirmation and a private-directory boundary.
- Apple Calendar/Reminders delivery: a locally compiled EventKit helper, a login
  worker, recurrence expansion, and verified EventKit readback of the dedicated
  HIQS containers.
- Course planning: candidate pools, complete class-combination solving, and
  revision-guarded plan state that refuses to overwrite a newer plan.
- Course notes: resumable checkpoints, revision guards and contract snapshots for
  chapter-level learning notes.
- Product Skills: four student-facing Skills under `skills/`, plus deterministic
  install and packaging scripts. `src/AI_Skills` is now a compatibility symlink.

### Changed

- Canonical `information.json` read-modify-write cycles are serialized across the
  MCP process, the CLI and the login worker with a dedicated `fcntl` lock.
- `atomic_write` flushes the parent directory after `os.replace`; course snapshot
  commits flush the published tree before the journal is cleaned up.
- Search and index refresh report a warning when canonical facts are missing or
  unreadable instead of silently returning an evidence packet without them.
- A corrupt Moodle snapshot is recorded as `baseline_status="corrupt"` and
  surfaced through the sync result instead of silently becoming a first sync.
- CI: coverage gate (75%), lockfile audit, wheel installation check, Python 3.12
  in the matrix, job timeouts and workflow concurrency.
- Security dependency bump: pypdf 6.21.4, certifi 2026.10.18,
  opentelemetry-api 1.45.1, PyJWT 2.15.0, setuptools 84.1.0.

### Fixed

- MCP sync control tools now forward `confirmed`; `start_course_sync` honours the
  single-course scope instead of silently running a full sync.
- `delete_courses` requires the repeated target list before deleting.
- The EventKit helper integrity stamp now covers the compiled executable, and the
  ad-hoc signature is verified with `codesign --verify --strict`.
- Moodle course-module ids are validated and file containment is checked before
  writing, instead of after.
- Course add/delete (compatibility UI only) now write the recent-update digest and
  keep the derived index consistent.

### Removed

- `add_course` and `delete_courses` are no longer MCP tools. Canonical facts are
  written through the validated apply flow; the compatibility UI keeps these
  maintenance actions.

## [2.11.0] - 2026-09-28

### Added

- Local AI-authored HKU course information database, cited retrieval, calendar
  projection and the compatibility dashboard.
- Moodle, SIS Student Center, SIS Course Information and Class Planner collectors.
- MCP tool surface and the `hsas` CLI recovery adapter.
