# Verification matrix

Choose checks in proportion to the affected boundary. Prefer observable behavior
over tests that only assert a phrase exists.

## Python domain, application, or core

- focused `pytest` tests for changed rules and failure paths;
- full `PYTHONPATH=.:src .venv/bin/pytest -q` for shared models, ports, storage,
  synchronization, or release-facing changes;
- `.venv/bin/ruff check .` and `git diff --check`.

## MCP or CLI adapter

- verify the adapter delegates through `HIQSPort`;
- cover validation, explicit confirmation, error translation, and returned
  report/checkpoint state;
- ensure no parallel business implementation was introduced.

## React and local web UI

- run `pnpm run typecheck` and focused Vitest tests;
- run `pnpm run build` so `src/hsas/web/static/modern-assets` matches source;
- run `.venv/bin/python scripts/check_generated.py` when Pydantic, MCP, or UI
  response models change;
- inspect the served page for layout or interaction changes, including empty,
  error, busy, completed, and narrow-screen states when relevant;
- confirm keyboard names and controls express their actual action.

## Collectors and file processing

- test discovery, download, and parsing independently where possible;
- cover bounds, duplicate links, unsupported content, partial failure, staging,
  and preservation of the last valid snapshot;
- verify provenance and completeness metadata reach evidence nodes and review
  queues.

## Persistent models and local state

- load both new and representative old records;
- verify migrations are deterministic and writes are atomic;
- separate canonical facts, derived caches, review state, and personal UI state;
- confirm corrupted derived state can rebuild without changing canonical data.

## Final review

Run `git status --short` and inspect the scoped diff. Check for stale terminology,
dead compatibility fields, accidental secrets, direct canonical writes, generated
artifacts not rebuilt, and changes inherited from other work that must remain
untouched. State what was and was not committed, pushed, or released.
