"""Local-only connection configuration and synchronization checkpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from hsas.infrastructure.storage.json_store import atomic_write


def notion_id(value: str) -> str:
    value = value.removeprefix("collection://").rstrip("/").split("?")[0].split("/")[-1]
    return str(UUID(value[-32:] if "-" not in value else value))


def config_path(resources: Path) -> Path:
    return resources / "notion" / "connection.json"


def save_config(resources: Path, config: dict) -> None:
    root = resources / "notion"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    atomic_write(config_path(resources), json.dumps(config, ensure_ascii=False, indent=2))
    config_path(resources).chmod(0o600)


def load_config(resources: Path, *, require_token: bool = True) -> dict:
    path = config_path(resources)
    value = json.loads(path.read_text()) if path.exists() else {}
    value["token"] = os.environ.get("HIQS_NOTION_TOKEN") or value.get("token", "")
    if require_token and not value["token"]:
        raise ValueError("Notion connection is not configured; run hsas notion configure")
    if value.get("parent_page_id"):
        value["parent_page_id"] = notion_id(value["parent_page_id"])
    value["data_sources"] = {k: notion_id(v) for k, v in value.get("data_sources", {}).items()}
    return value
