"""Server-rendered HTML for the local viewer.

No framework, no client bundle, no build step: three pages of escaped strings over
the same snapshot the Skills and MCP read. The viewer's whole job is to answer
"what do I have, how old is it, and where is the file" — anything that needs
interaction belongs in the chat workflow, not here.
"""

from __future__ import annotations

from html import escape
import re
from typing import Any
from urllib.parse import quote

LECTURE_HINT = re.compile(r"lecture|slide|lect", re.IGNORECASE)
#: Moodle activity names and file names often carry the lecture's own date
#: ("Electrochemistry (2026-09-28 by ...)"). A full re-sync rewrites every
#: downloaded_at to the same moment, so the download time cannot rank lectures.
DATE_HINT = re.compile(r"(20\d{2})[-_. /]?(\d{2})[-_. /]?(\d{2})")
MONTHS = {
    name: index
    for index, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}
DAY_MONTH_YEAR = re.compile(r"\b(\d{1,2})[-_./](\d{1,2})[-_./](20\d{2})\b")
MONTH_FIRST = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[-_. ]?(\d{1,2})[-_. ,]+(20\d{2})", re.I)
DAY_FIRST = re.compile(r"\b(\d{1,2})[-_. ]?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[-_. ,]+(20\d{2})", re.I)

STYLE = """
:root { color-scheme: light dark; --fg:#1b1b1f; --muted:#5f6368; --bg:#fbfbfa;
        --card:#fff; --line:#e4e4e1; --accent:#2f5d62; --warn:#b3261e; --ok:#2e6b46; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e8e8e6; --muted:#a0a0a0; --bg:#141414; --card:#1c1c1c;
          --line:#2e2e2e; --accent:#8ab4b8; --warn:#ff8a80; --ok:#7bc59a; }
}
* { box-sizing: border-box; }
body { margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
       font:15px/1.55 -apple-system, "Segoe UI", "Noto Sans SC", sans-serif; }
main { max-width: 62rem; margin: 0 auto; }
h1 { font-size:1.35rem; margin:0 0 .25rem; letter-spacing:-.01em; }
h2 { font-size:1rem; margin:2rem 0 .5rem; color:var(--muted); font-weight:600;
     text-transform:uppercase; letter-spacing:.08em; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
.sub { color:var(--muted); margin:0 0 1.5rem; font-size:.9rem; }
table { width:100%; border-collapse:collapse; background:var(--card);
        border:1px solid var(--line); border-radius:10px; overflow:hidden; }
th, td { text-align:left; padding:.5rem .75rem; border-bottom:1px solid var(--line);
         font-size:.92rem; vertical-align:top; }
th { font-weight:600; color:var(--muted); font-size:.78rem; text-transform:uppercase;
     letter-spacing:.06em; }
tr:last-child td { border-bottom:none; }
.bad { color:var(--warn); font-weight:600; }
.good { color:var(--ok); }
.muted { color:var(--muted); }
.pill { display:inline-block; padding:.05rem .45rem; border:1px solid var(--line);
        border-radius:999px; font-size:.75rem; color:var(--muted); }
.empty { padding:1rem; color:var(--muted); }
section { margin-bottom:2rem; }
ul.items { list-style:none; margin:0; padding:0; }
ul.items li { padding:.35rem 0; border-bottom:1px solid var(--line); }
ul.items li:last-child { border-bottom:none; }
"""


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)}</title><style>{STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def _when(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "never"
    return escape(value.replace("T", " ")[:16].replace("+00:00", ""))


def _age(entry: dict[str, Any]) -> str:
    age = entry.get("age_days")
    limit = entry.get("threshold_days")
    state = str(entry.get("state") or "never")
    if age is None:
        return f'<span class="bad">never collected</span> <span class="muted">(limit {limit:g}d)</span>'
    css = "good" if state == "fresh" else "bad"
    label = "fresh" if state == "fresh" else state
    return (
        f'<span class="{css}">{age:g}d</span> <span class="muted">/ {limit:g}d limit'
        f' · {escape(label)}</span>'
    )


def _freshness_table(freshness: dict[str, Any] | None) -> str:
    entries = (freshness or {}).get("sources") or []
    if not entries:
        return '<table><tr><td class="empty">No sources have been captured yet.</td></tr></table>'
    rows = "".join(
        f"<tr><td>{escape(str(entry.get('source')))}</td>"
        f"<td>{_when(entry.get('captured_at'))}</td>"
        f"<td>{_age(entry)}</td></tr>"
        for entry in entries
    )
    return (
        "<table><thead><tr><th>Source</th><th>Last captured</th><th>Age</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _delivery_section(delivery: dict[str, Any] | None) -> str:
    if not delivery or not delivery.get("configured"):
        return (
            '<section><h2>Apple delivery</h2><p class="muted">Not configured. '
            "Calendar and reminders will not be updated automatically.</p></section>"
        )
    counts = delivery.get("counts") or {}
    verification = delivery.get("verification") or {}
    state = (
        '<span class="good">up to date with the facts</span>'
        if delivery.get("up_to_date_with_facts")
        else f'<span class="bad">{escape(str(delivery.get("why") or "not current"))}</span>'
    )
    worker = "worker loaded" if delivery.get("worker_loaded") else "worker NOT loaded"
    return (
        "<section><h2>Apple delivery</h2>"
        '<table><tbody>'
        f"<tr><td>Calendar events</td><td>{counts.get('events', 0)}</td></tr>"
        f"<tr><td>Reminders</td><td>{counts.get('reminders', 0)}</td></tr>"
        f"<tr><td>Read-back verification</td>"
        f"<td>{verification.get('matched', 0)}/{verification.get('expected', 0)} "
        f"{escape(str(verification.get('status') or ''))}</td></tr>"
        f"<tr><td>Last delivered</td><td>{_when(delivery.get('last_delivered_at'))}</td></tr>"
        f"<tr><td>Facts last changed</td><td>{_when(delivery.get('facts_updated_at'))}</td></tr>"
        f"<tr><td>Sync state</td><td>{state} <span class=\"muted\">· {escape(worker)}</span></td></tr>"
        "</tbody></table></section>"
    )


def _written_date(haystack: str) -> str | None:
    """A date the material itself carries, normalized to YYYYMMDD."""
    match = DATE_HINT.search(haystack)
    if match:
        return f"{match.group(1)}{match.group(2)}{match.group(3)}"
    day_month_year = DAY_MONTH_YEAR.search(haystack)
    if day_month_year:
        return (
            f"{day_month_year.group(3)}"
            f"{int(day_month_year.group(2)):02d}{int(day_month_year.group(1)):02d}"
        )
    month_first = MONTH_FIRST.search(haystack)
    if month_first:
        month = MONTHS[month_first.group(1).lower()[:3]]
        return f"{month_first.group(3)}{month:02d}{int(month_first.group(2)):02d}"
    day_first = DAY_FIRST.search(haystack)
    if day_first:
        month = MONTHS[day_first.group(2).lower()[:3]]
        return f"{day_first.group(3)}{month:02d}{int(day_first.group(1)):02d}"
    return None


def _material_rank(material: dict[str, Any]) -> str:
    """One comparable day per material: what it says about itself, else when it arrived."""
    haystack = (
        f"{material.get('title', '')} {material.get('activity_name', '')} "
        f"{material.get('section_title', '')}"
    )
    written = _written_date(haystack)
    if written:
        return written
    downloaded = str(material.get("downloaded_at") or "")
    return downloaded[:10].replace("-", "") if len(downloaded) >= 10 else ""


def _latest_lecture(course: dict[str, Any]) -> dict[str, Any] | None:
    """The newest lecture-like material that has a local file."""
    entries = [
        material
        for material in (course.get("materials") or {}).get("all") or []
        if material.get("relative_path") and material.get("exists", True)
    ]
    if not entries:
        return None
    lectures = [
        material
        for material in entries
        if LECTURE_HINT.search(
            f"{material.get('title', '')} {material.get('activity_name', '')} "
            f"{material.get('section_title', '')}"
        )
    ]
    pool = lectures or entries
    return max(pool, key=_material_rank)


def _lecture_date(material: dict[str, Any]) -> str:
    day = _material_rank(material)
    if len(day) == 8 and day.isdigit():
        return f"{day[:4]}-{day[4:6]}-{day[6:8]}"
    return _when(material.get("downloaded_at"))


def _latest_section(snapshot: dict[str, Any]) -> str:
    rows = []
    for course in snapshot.get("courses") or []:
        lecture = _latest_lecture(course)
        if lecture is None:
            continue
        path = escape(quote(str(lecture.get("relative_path")), safe="/"))
        rows.append(
            f"<tr><td><a href=\"/courses/{escape(str(course.get('course_id')))}\">"
            f"{escape(str(course.get('code') or ''))}</a></td>"
            f"<td>{escape(str(lecture.get('title') or ''))}</td>"
            f"<td class=\"muted\">{_lecture_date(lecture)}</td>"
            f'<td><a href="/file?path={path}">open</a> · '
            f'<a href="/preview?path={path}">text</a></td></tr>'
        )
    if not rows:
        return ""
    return (
        "<section><h2>Latest lecture materials</h2>"
        "<table><thead><tr><th>Course</th><th>Newest lecture material</th>"
        "<th>Date</th><th></th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def render_status(
    snapshot: dict[str, Any],
    attention: dict[str, Any] | None = None,
    delivery: dict[str, Any] | None = None,
) -> str:
    summary = snapshot.get("summary") or {}
    freshness = snapshot.get("freshness") or {}
    stale = freshness.get("stale_sources") or []
    never = freshness.get("never_collected") or []
    if not snapshot.get("available"):
        banner = (
            '<p class="sub bad">information.json does not exist yet. '
            "Ask the agent to build a validated update from local materials.</p>"
        )
    elif stale or never:
        parts = []
        if stale:
            parts.append("stale: " + ", ".join(escape(str(item)) for item in stale))
        if never:
            parts.append("never collected: " + ", ".join(escape(str(item)) for item in never))
        banner = f'<p class="sub"><span class="bad">Needs a sync</span> — {" · ".join(parts)}</p>'
    else:
        banner = '<p class="sub good">All sources are within their freshness limit.</p>'

    attention_items = (attention or {}).get("items") or []
    attention_html = ""
    if attention_items:
        rows = "".join(
            f"<li><strong>{escape(str(item.get('title') or ''))}</strong> "
            f'<span class="pill">{escape(str(item.get("severity") or ""))}</span> '
            f'<span class="muted">{escape(", ".join(item.get("reason_codes") or []))}</span></li>'
            for item in attention_items[:12]
        )
        attention_html = f'<section><h2>Needs attention</h2><ul class="items">{rows}</ul></section>'

    return _page(
        "HIQS",
        f"""<h1>HIQS</h1>{banner}
{_latest_section(snapshot)}
<section><h2>Freshness</h2>{_freshness_table(freshness)}</section>
<section><h2>Contents</h2><table><tbody>
<tr><td>Courses</td><td>{summary.get("course_count", 0)}</td></tr>
<tr><td>Course facts</td><td>{summary.get("item_count", 0)}</td></tr>
<tr><td>Items with a date</td><td>{summary.get("calendar_item_count", 0)}</td></tr>
<tr><td>Pending review</td><td>{int((snapshot.get("pending_review") or {}).get("change_count", 0))}</td></tr>
</tbody></table></section>
{_delivery_section(delivery)}
{attention_html}
<section><h2>Browse</h2><p><a href="/courses">All course materials →</a></p></section>""",
    )


def render_courses(snapshot: dict[str, Any]) -> str:
    courses = snapshot.get("courses") or []
    if not courses:
        return _page(
            "Courses · HIQS",
            '<h1>Courses</h1><p class="sub">No courses recorded yet.</p>'
            '<p><a href="/">← status</a></p>',
        )
    rows = []
    for course in courses:
        moodle = course.get("moodle") or {}
        sections = course.get("material_sections") or []
        count = sum(len(section.get("materials") or []) for section in sections)
        collected = moodle.get("collected_at")
        rows.append(
            f"<tr><td><a href=\"/courses/{escape(str(course.get('course_id')))}\">"
            f"{escape(str(course.get('code') or ''))}</a></td>"
            f"<td>{escape(str(course.get('title') or ''))}</td>"
            f"<td>{count}</td>"
            f"<td>{_when(collected)}</td>"
            f'<td>{escape(str(moodle.get("download_failed_count") or 0))}</td></tr>'
        )
    return _page(
        "Courses · HIQS",
        "<h1>Courses</h1>"
        '<p class="sub">Materials collected from Moodle, grouped as the agent organized them.</p>'
        "<table><thead><tr><th>Code</th><th>Title</th><th>Materials</th>"
        f"<th>Moodle collected</th><th>Failed downloads</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        '<p><a href="/">← status</a></p>',
    )


def _material_row(material: dict[str, Any]) -> str:
    title = escape(str(material.get("title") or "untitled"))
    kind = escape(str(material.get("material_type") or ""))
    path = material.get("relative_path")
    links = []
    if path:
        quoted = escape(quote(str(path), safe="/"))
        links.append(f'<a href="/file?path={quoted}">open</a>')
        links.append(f'<a href="/preview?path={quoted}">text</a>')
    url = material.get("url")
    if isinstance(url, str) and url.startswith("http"):
        links.append(f'<a href="{escape(url, quote=True)}" rel="noreferrer">source</a>')
    when = material.get("downloaded_at")
    when_html = f' <span class="muted">{_when(when)}</span>' if when else ""
    pages = material.get("page_numbers") or []
    where = f' <span class="muted">p.{escape(",".join(str(p) for p in pages))}</span>' if pages else ""
    note = material.get("note")
    note_html = f' <span class="muted">— {escape(str(note))}</span>' if note else ""
    note_html = when_html + note_html
    return (
        f'<li>{title} <span class="pill">{kind}</span>{where}{note_html} '
        f'<span class="muted">· {" ".join(links) if links else "no local file"}</span></li>'
    )


def render_course(snapshot: dict[str, Any], course_id: str) -> str | None:
    courses = snapshot.get("courses") or []
    course = next(
        (item for item in courses if str(item.get("course_id")) == course_id), None
    )
    if course is None:
        return None
    items = [item for item in snapshot.get("items") or [] if str(item.get("course_id")) == course_id]
    item_rows = "".join(
        f"<li>{escape(str(item.get('title') or ''))} "
        f'<span class="pill">{escape(str(item.get("category") or ""))}</span> '
        f'<span class="muted">{escape(str(item.get("due_at") or item.get("due_on") or "no date"))}'
        f' · {escape(str(item.get("date_status") or ""))}</span></li>'
        for item in sorted(items, key=lambda value: str(value.get("due_at") or value.get("due_on") or "~"))
    )
    sections = []
    for section in course.get("material_sections") or []:
        ordered = sorted(
            section.get("materials") or [],
            key=lambda material: str(material.get("downloaded_at") or ""),
            reverse=True,
        )
        rows = "".join(_material_row(material) for material in ordered)
        sections.append(
            f'<section><h2>{escape(str(section.get("title") or "Materials"))}</h2>'
            f'<ul class="items">{rows or "<li class=muted>nothing in this section</li>"}</ul></section>'
        )
    moodle = course.get("moodle") or {}
    return _page(
        f"{course.get('code') or course_id} · HIQS",
        f"<h1>{escape(str(course.get('code') or course_id))} — "
        f"{escape(str(course.get('title') or ''))}</h1>"
        f'<p class="sub">Moodle captured {_when(moodle.get("collected_at"))} · '
        f'course record {escape(course_id)}</p>'
        f'<section><h2>Course facts</h2><ul class="items">'
        f'{item_rows or "<li class=muted>no recorded facts</li>"}</ul></section>'
        f"{''.join(sections)}"
        '<p><a href="/courses">← courses</a> · <a href="/">status</a></p>',
    )


def render_text(title: str, body: str, *, truncated: bool = False) -> str:
    body = body or "(no extracted text for this file)"
    note = '<p class="sub bad">Preview truncated.</p>' if truncated else ""
    return _page(
        f"{title} · HIQS",
        f"<h1>{escape(title)}</h1>{note}"
        f'<pre style="white-space:pre-wrap;background:var(--card);border:1px solid var(--line);'
        f'border-radius:10px;padding:1rem;overflow-x:auto">{escape(body)}</pre>',
    )


def render_error(status: int, message: str) -> str:
    return _page(f"{status} · HIQS", f'<h1>{status}</h1><p class="sub">{escape(message)}</p>')


__all__ = [
    "render_course",
    "render_courses",
    "render_error",
    "render_status",
    "render_text",
]
