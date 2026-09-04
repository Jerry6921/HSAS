# Contributing

Keep user data outside the checkout and never add `.env`, browser profiles,
downloaded course materials, extracted text, or `information.json` to Git.

Install and verify changes with:

```bash
python -m pip install -c requirements.lock -e '.[dev]'
python -m ruff check src tests
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
```

Preserve the dependency direction documented in `ARCHITECTURE.md`. Collector
changes require download-coverage, last-known-good and failure-path tests.
Information changes require strict-schema, atomic-upsert and no-data-loss tests;
calendar changes require API and browser-level rendering checks.

Place code under the noun-based `hsas/interfaces`, `hsas/application`,
`hsas/domain`, or `hsas/infrastructure` hierarchy. Name ordinary Python modules
with an action-oriented `verb_object.py` responsibility such as
`update_information.py` or `persist_data.py`; only Python-required modules such as
`__init__.py` and `__main__.py` are exempt. Tests retain pytest's action prefix
and use `test_<verb_object>.py`.
