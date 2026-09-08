"""Platform-standard runtime paths for private user data."""

from __future__ import annotations

from typing import Any

__all__ = [
    "RuntimePaths",
    "ensure_resources_layout",
    "get_runtime_paths",
    "hku_portal_profile_dir",
]


def __getattr__(name: str) -> Any:
    if name in {
        "RuntimePaths",
        "ensure_resources_layout",
        "get_runtime_paths",
        "hku_portal_profile_dir",
    }:
        from .resolve_paths import (
            RuntimePaths,
            ensure_resources_layout,
            get_runtime_paths,
            hku_portal_profile_dir,
        )

        return {
            "RuntimePaths": RuntimePaths,
            "ensure_resources_layout": ensure_resources_layout,
            "get_runtime_paths": get_runtime_paths,
            "hku_portal_profile_dir": hku_portal_profile_dir,
        }[name]
    raise AttributeError(name)
