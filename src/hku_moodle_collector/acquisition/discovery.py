from __future__ import annotations

from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from ..config import SelectorConfig
from ..transformation.models import CourseSummary


def _first_matching_nodes(soup: BeautifulSoup, selectors: list[str]):
    for selector in selectors:
        nodes = soup.select(selector)
        if nodes:
            return nodes
    return []


def discover_courses(
    html: str, page_url: str, selectors: SelectorConfig
) -> list[CourseSummary]:
    soup = BeautifulSoup(html, "html.parser")
    courses: dict[str, CourseSummary] = {}
    for link in _first_matching_nodes(soup, selectors.course_links):
        href = link.get("href")
        title = " ".join(link.get_text(" ", strip=True).split())
        if not href or not title:
            continue
        url = urljoin(page_url, href)
        course_id = parse_qs(urlparse(url).query).get("id", [None])[0]
        courses[url] = CourseSummary(title=title, url=url, course_id=course_id)
    return list(courses.values())
