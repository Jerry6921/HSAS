"""Authenticated Moodle response acquisition stage."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from playwright.async_api import APIResponse, BrowserContext

from hsas.domain.courses.models import StoredFile


FetchFunction = Callable[..., Awaitable[tuple[APIResponse | None, StoredFile | None]]]


class MoodleDownloadService:
    def __init__(self, fetcher: FetchFunction) -> None:
        self._fetcher = fetcher

    async def fetch(
        self,
        context: BrowserContext,
        url: str,
        *,
        previous: StoredFile | None,
        storage_root: Path,
        timeout_ms: int,
    ) -> tuple[APIResponse | None, StoredFile | None]:
        return await self._fetcher(
            context,
            url,
            previous=previous,
            storage_root=storage_root,
            timeout_ms=timeout_ms,
        )
