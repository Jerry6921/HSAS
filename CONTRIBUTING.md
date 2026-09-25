# Contributing

Keep user data outside the checkout. Git tracks source and public fixtures;
`.env`, browser profiles, downloaded course materials, extracted text, and
`information.json` stay in the private runtime directory.

Install and verify changes with:

```bash
python -m pip install -c requirements.lock -e '.[dev]'
python -m ruff check src tests
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
cd ui
pnpm install --frozen-lockfile
pnpm run check
```

Preserve the dependency direction documented in `ARCHITECTURE.md`. Collector
changes require download-coverage, last-known-good and failure-path tests.
Information changes require strict-schema, atomic-upsert, and data-preservation tests;
calendar changes require API and browser-level rendering checks.

Pull requests run the Python suite, frontend typecheck/component tests/build,
wheel construction, and a generated-bundle drift check in GitHub Actions.

Place code under the architectural `hsas/domain`, `hsas/application`,
`hsas/infrastructure`, `hsas/core`, `hsas/cli`, `hsas/web`, `hsas/mcp`, or
`hsas/codegen` hierarchy. Use responsibility-oriented, lowercase snake_case module
names such as `material_search.py`, `change_tracking.py`, `course_publisher.py`, or
`session_store.py`. Generic action prefixes such as `define_`, `manage_`, `build_`,
and `run_` are reserved for function names rather than module names. Group related
adapters and services into focused subpackages instead of adding loose modules at
the package root. Tests retain pytest's `test_*.py` naming convention.
