"""Persist the shared private browser authentication state between contexts."""

from __future__ import annotations

from pathlib import Path

from playwright.async_api import BrowserContext

from hsas.infrastructure.storage.json_store import read_json


SHARED_BROWSER_STATE = "storage-state.json"


async def restore_shared_browser_state(
    context: BrowserContext, profile_dir: Path
) -> None:
    """Restore session-only cookies saved by a previous official login flow."""
    path = profile_dir / SHARED_BROWSER_STATE
    if not path.is_file():
        return
    value = read_json(path)
    cookies = value.get("cookies", []) if isinstance(value, dict) else []
    if isinstance(cookies, list) and cookies:
        await context.add_cookies(
            [cookie for cookie in cookies if isinstance(cookie, dict)]
        )


async def save_shared_browser_state(
    context: BrowserContext, profile_dir: Path
) -> Path:
    """Save browser state privately so Portal SSO survives a context restart."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.chmod(0o700)
    path = profile_dir / SHARED_BROWSER_STATE
    await context.storage_state(path=str(path))
    path.chmod(0o600)
    return path


def shared_browser_state_path(profile_dir: Path) -> Path:
    return profile_dir / SHARED_BROWSER_STATE


__all__ = [
    "restore_shared_browser_state",
    "save_shared_browser_state",
    "shared_browser_state_path",
]
