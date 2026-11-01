"""Pure Notion property formatting shared by projections and adapters.

Keeping these value builders in the domain layer lets both the application
projection and the infrastructure adapter use one implementation without either
layer importing the other's internals.
"""

from __future__ import annotations

from typing import Any


def rich_text(value: str | None) -> dict[str, Any]:
    text = value or ""
    return {"rich_text": [
        {"type": "text", "text": {"content": text[i:i + 2000]}}
        for i in range(0, len(text), 2000)
    ]}


def title(value: str) -> dict[str, Any]:
    return {"title": [{"text": {"content": value[:2000]}}]}


def date_property(start: str | None, end: str | None = None) -> dict[str, Any]:
    return {"date": {"start": start, "end": end} if start else None}


def select(value: str) -> dict[str, Any]:
    return {"select": {"name": value}}
