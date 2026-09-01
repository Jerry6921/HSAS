"""Resolve user-owned HSAS directories independently of the code checkout."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from platformdirs import PlatformDirs


APP_NAME = "HSAS"
DATA_DIR_ENV = "HSAS_DATA_DIR"


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    data_dir: Path
    resources_dir: Path
    config_file: Path
    browser_profile_dir: Path
    state_dir: Path
    cache_dir: Path
    log_dir: Path

    def create(self) -> "RuntimePaths":
        for path in (
            self.data_dir,
            self.resources_dir,
            self.resources_dir / "courses",
            self.browser_profile_dir,
            self.state_dir,
            self.cache_dir,
            self.log_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self


def get_runtime_paths(data_dir: Path | None = None) -> RuntimePaths:
    """Return platform-standard paths, honoring HSAS_DATA_DIR."""
    directories = PlatformDirs(APP_NAME, appauthor=False)
    override = data_dir or _environment_data_dir()
    root = override.expanduser().resolve() if override else Path(directories.user_data_dir)
    return RuntimePaths(
        data_dir=root,
        resources_dir=root / "resources",
        config_file=root / "config.toml",
        browser_profile_dir=root / "browser-profile",
        state_dir=root / "state",
        cache_dir=Path(directories.user_cache_dir),
        log_dir=Path(directories.user_log_dir),
    )


def ensure_resources_layout(resources_dir: Path) -> Path:
    """Create and return the stable, user-owned resources directory layout."""
    resources = resources_dir.expanduser().resolve()
    resources.mkdir(parents=True, exist_ok=True)
    (resources / "courses").mkdir(parents=True, exist_ok=True)
    return resources


def _environment_data_dir() -> Path | None:
    value = os.environ.get(DATA_DIR_ENV, "").strip()
    return Path(value) if value else None
