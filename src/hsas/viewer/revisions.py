"""A cheap revision token for "did anything the page shows actually change?"

The page costs ~200ms to build because it reads the whole snapshot. Polling that
on a timer would be wasteful, so the page polls a stat-only fingerprint instead
and reloads only when a file it renders has moved.
"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path

#: Files whose change alters something a page shows.
WATCHED = (
    "information.json",
    "ai-state/recent-information-update.json",
    "ai-state/change-checkpoint.json",
    "sis-enrollment/latest.json",
    "sis-course-info/latest.json",
    "class-planner/latest.json",
    "apple/state.json",
)


def data_revision(resources_dir: Path) -> str:
    """Fingerprint file sizes and mtimes; never read the contents."""
    parts: list[str] = []
    for relative in WATCHED:
        try:
            stat = (resources_dir / relative).stat()
        except OSError:
            parts.append(f"{relative}:missing")
            continue
        parts.append(f"{relative}:{stat.st_size}:{stat.st_mtime_ns}")
    return sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


__all__ = ["WATCHED", "data_revision"]
