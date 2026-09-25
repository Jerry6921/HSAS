"""Pure Moodle link-discovery stage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    file_urls: tuple[str, ...]
    page_urls: tuple[str, ...]


class MoodleDiscoveryService:
    def __init__(
        self,
        file_candidates: Callable[[str, str, str], list[str]],
        page_candidates: Callable[[str, str, str], list[str]],
    ) -> None:
        self._file_candidates = file_candidates
        self._page_candidates = page_candidates

    def discover(self, html: str, page_url: str, base_url: str) -> DiscoveryResult:
        return DiscoveryResult(
            file_urls=tuple(self._file_candidates(html, page_url, base_url)),
            page_urls=tuple(self._page_candidates(html, page_url, base_url)),
        )
