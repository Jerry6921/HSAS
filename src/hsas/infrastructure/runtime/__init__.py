"""Runtime paths and legacy-data migration."""

from __future__ import annotations

from typing import Any

__all__ = [
    "MigrationError",
    "MigrationResult",
    "RuntimePaths",
    "ensure_resources_layout",
    "get_runtime_paths",
    "migrate_legacy_data",
]


def __getattr__(name: str) -> Any:
    if name in {"RuntimePaths", "ensure_resources_layout", "get_runtime_paths"}:
        from .resolve_paths import RuntimePaths, ensure_resources_layout, get_runtime_paths

        return {
            "RuntimePaths": RuntimePaths,
            "ensure_resources_layout": ensure_resources_layout,
            "get_runtime_paths": get_runtime_paths,
        }[name]
    if name in {"MigrationError", "MigrationResult", "migrate_legacy_data"}:
        from .migrate_data import MigrationError, MigrationResult, migrate_legacy_data

        return {
            "MigrationError": MigrationError,
            "MigrationResult": MigrationResult,
            "migrate_legacy_data": migrate_legacy_data,
        }[name]
    raise AttributeError(name)
