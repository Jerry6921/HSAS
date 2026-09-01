# Contributing

Keep user data outside the checkout and never add `.env`, browser profiles,
downloaded course materials, or generated plans to Git.

Install and verify changes with:

```bash
python -m pip install -c requirements.lock -e '.[dev]'
python -m ruff check src tests
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
```

Preserve the dependency direction documented in `ARCHITECTURE.md`. New planning
rules require deterministic tests; collector changes require last-known-good and
failure-path tests; confirmed-data mutations require idempotency and validation
tests.
