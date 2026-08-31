from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from ...settings import SelectorConfig
from .course_schema import (
    Announcement,
    Assignment,
    CourseSnapshot,
    CourseSummary,
    Resource,
    Section,
)


def _first(root: Tag | BeautifulSoup, selectors: list[str]) -> Tag | None:
    for selector in selectors:
        node = root.select_one(selector)
        if node:
            return node
    return None


def _all(root: Tag | BeautifulSoup, selectors: list[str]) -> list[Tag]:
    for selector in selectors:
        nodes = root.select(selector)
        if nodes:
            return nodes
    return []


def _text(node: Tag | None) -> str | None:
    if not node:
        return None
    value = " ".join(node.get_text(" ", strip=True).split())
    return value or None


def _activity_title(link: Tag, selectors: SelectorConfig) -> str:
    return _text(_first(link, selectors.activity_name)) or _text(link) or "Untitled"


def _resource_type(url: str) -> str | None:
    path = PurePosixPath(urlparse(url).path)
    suffix = path.suffix.lower().lstrip(".")
    return suffix or None


def parse_course(
    html: str, page_url: str, selectors: SelectorConfig
) -> CourseSnapshot:
    soup = BeautifulSoup(html, "html.parser")
    title = _text(_first(soup, selectors.course_title)) or "Untitled course"
    course_id = parse_qs(urlparse(page_url).query).get("id", [None])[0]
    parsed_sections: list[Section] = []

    section_nodes = _all(soup, selectors.sections)
    # Some Moodle themes omit explicit section wrappers. Treat main content as one section.
    if not section_nodes:
        section_nodes = [soup]

    for index, node in enumerate(section_nodes):
        section = Section(
            title=_text(_first(node, selectors.section_title)) or f"Section {index + 1}",
            index=index,
        )
        seen: set[str] = set()
        for link in _all(node, selectors.activity_links):
            href = link.get("href")
            if not href:
                continue
            url = urljoin(page_url, href)
            if url in seen:
                continue
            seen.add(url)
            activity_title = _activity_title(link, selectors)
            container = link.parent if isinstance(link.parent, Tag) else link
            description = _text(_first(container, selectors.activity_description))
            lowered_url = url.lower()
            lowered_title = activity_title.casefold()

            if "/mod/assign/" in lowered_url:
                section.assignments.append(
                    Assignment(title=activity_title, url=url, description=description)
                )
            elif "/mod/forum/" in lowered_url and any(
                word in lowered_title for word in ("announcement", "announcements", "公告", "通知")
            ):
                section.announcements.append(
                    Announcement(title=activity_title, url=url, description=description)
                )
            else:
                section.resources.append(
                    Resource(
                        title=activity_title,
                        url=url,
                        description=description,
                        resource_type=_resource_type(url),
                    )
                )
        parsed_sections.append(section)

    return CourseSnapshot(
        collected_at=datetime.now(timezone.utc),
        course=CourseSummary(title=title, url=page_url, course_id=course_id),
        sections=parsed_sections,
    )
