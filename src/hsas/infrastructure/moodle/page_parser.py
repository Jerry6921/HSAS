"""Pure Moodle HTML parsing stage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bs4 import BeautifulSoup
from trafilatura import extract as extract_main_text

from .link_discovery import DiscoveryResult, MoodleDiscoveryService


@dataclass(frozen=True, slots=True)
class ParseResult:
    url: str
    title: str | None
    text: str
    discovered: DiscoveryResult


class MoodleParseService:
    def __init__(
        self,
        discovery: MoodleDiscoveryService,
        sanitize_url: Callable[[str], str],
    ) -> None:
        self.discovery = discovery
        self._sanitize_url = sanitize_url

    def parse(self, html: str, page_url: str, base_url: str) -> ParseResult:
        soup = BeautifulSoup(html, "html.parser")
        text = "\n".join(
            line for line in (" ".join(line.split()) for line in soup.get_text("\n").splitlines())
            if line
        ).strip()
        try:
            extracted = extract_main_text(
                html, include_links=False, include_comments=False
            )
        except Exception:
            extracted = None
        if isinstance(extracted, str):
            main_text = extracted.strip()
            if (
                len(main_text) > len(text)
                or len(text) > 1_000
                and len(main_text) >= max(120, len(text) // 4)
            ):
                text = main_text
        return ParseResult(
            url=self._sanitize_url(page_url),
            title=soup.title.get_text(" ", strip=True) if soup.title else None,
            text=text[:20_000],
            discovered=self.discovery.discover(html, page_url, base_url),
        )
