"""Runtime services with lazy imports to keep storage independent of platform paths."""

from __future__ import annotations

from typing import Any

__all__ = [
    "MigrationError",
    "MigrationResult",
    "RuntimePaths",
    "get_runtime_paths",
    "migrate_legacy_data",
]


def __getattr__(name: str) -> Any:
    if name in {"RuntimePaths", "get_runtime_paths"}:
        from .paths import RuntimePaths, get_runtime_paths

        return {"RuntimePaths": RuntimePaths, "get_runtime_paths": get_runtime_paths}[name]
    if name in {"MigrationError", "MigrationResult", "migrate_legacy_data"}:
        from .migration import MigrationError, MigrationResult, migrate_legacy_data

        return {
            "MigrationError": MigrationError,
            "MigrationResult": MigrationResult,
            "migrate_legacy_data": migrate_legacy_data,
        }[name]
    raise AttributeError(name)
