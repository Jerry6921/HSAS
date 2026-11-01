"""CORE use cases for Notion delivery; canonical facts remain read-only."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
import fcntl
from pathlib import Path
from typing import Any

from hsas.application.notion_projection import build_notion_projection
from hsas.application.ports.notion import NotionWorkspaceGateway
from hsas.core.ports import HIQSPortError
from hsas.core.services.materials import MaterialQueryService
from hsas.domain.information.models import moodle_source_course_ids
from hsas.infrastructure.notion.client import NotionAPIError, NotionClient
from hsas.infrastructure.notion.config import load_config, notion_id, save_config
from hsas.infrastructure.notion.export import export_package
from hsas.infrastructure.notion.workspace import NotionWorkspaceAdapter
from hsas.infrastructure.notion.worker import worker_plist
from hsas.infrastructure.storage import JsonInformationRepository
from hsas.infrastructure.storage.json_store import read_json


def _workspace(config: dict, path: Path) -> NotionWorkspaceGateway:
    return NotionWorkspaceAdapter(NotionClient(config["token"]), config, path)


@dataclass(slots=True)
class NotionDeliveryService:
    resources_dir: Path
    materials: MaterialQueryService
    workspace_factory: Callable[[dict, Path], NotionWorkspaceGateway] = field(
        default=_workspace, repr=False)

    def projection(self) -> dict[str, Any]:
        try:
            store = JsonInformationRepository().load(self.resources_dir / "information.json")
            source_ids = list(dict.fromkeys(s for c in store.courses for s in moodle_source_course_ids(c)))
            documents = self.materials.manifest(source_ids).get("documents", [])
            return build_notion_projection(store, self.materials.resolve_file, source_documents=documents)
        except (ValueError, OSError, RuntimeError) as exc:
            raise HIQSPortError(f"Notion projection failed: {type(exc).__name__}") from exc

    def export(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Write a private import package behind a path boundary and confirmation.

        The MCP tool is Agent-callable and course material is untrusted input, so
        an Agent export may only land inside ``resources/exports``. The human CLI
        recovery path passes ``allow_outside=True`` because a person typed the
        destination explicitly.
        """
        if payload.get("confirmed") is not True:
            raise HIQSPortError("请先确认导出 Notion 数据包。")
        raw_destination = payload.get("destination")
        if raw_destination is not None and (
            not isinstance(raw_destination, str) or not raw_destination.strip()
        ):
            raise HIQSPortError("destination 必须是有效路径，或省略以使用私有导出目录。")
        exports_root = (self.resources_dir / "exports").resolve()
        if raw_destination is None:
            destination = exports_root / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        else:
            destination = Path(raw_destination).expanduser().resolve()
            if payload.get("allow_outside") is not True and not destination.is_relative_to(
                exports_root
            ):
                raise HIQSPortError(
                    "Agent 导出目录必须位于私有 resources/exports 下；"
                    "人工 CLI 恢复路径可显式使用 --allow-outside。"
                )
        return export_package(
            self.projection(),
            None,
            destination,
            include_files=bool(payload.get("include_files", True)),
        )

    def status(self) -> dict[str, Any]:
        config = load_config(self.resources_dir, require_token=False)
        path = self.resources_dir / "notion" / "state.json"
        report = read_json(path).get("report") if path.exists() else None
        parent = config.get("parent_page_id")
        return {"configured": bool(config.get("token")),
            "workspace_url": "https://www.notion.so/" + parent.replace("-", "") if parent else None,
            "data_sources": config.get("data_sources", {}), "last_sync": report,
            "collect_interval_seconds": config.get("collect_interval_seconds", 0)}

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = dict(payload)
        config["parent_page_id"] = notion_id(config["parent_page_id"])
        config["data_sources"] = {k: notion_id(v) for k, v in config["data_sources"].items()}
        config["upload_limit_bytes"] = int(config.get("upload_limit_bytes", 5 * 1024 * 1024))
        if config["upload_limit_bytes"] < 1:
            raise HIQSPortError("Upload limit must be positive")
        interval = int(config.get("collect_interval_seconds", 0))
        if interval != 0 and not 600 <= interval <= 86400:
            raise HIQSPortError("Automatic collection interval must be 0 or 600–86400 seconds")
        config["collect_interval_seconds"] = interval
        try:
            adapter = self.workspace_factory(config, self.resources_dir / "notion" / "state.json")
            adapter.check_connection()
            save_config(self.resources_dir, config)
        except (ValueError, NotionAPIError, OSError) as exc:
            raise HIQSPortError(str(exc) if isinstance(exc, NotionAPIError) else
                                f"Notion configuration failed: {type(exc).__name__}") from None
        return self.status()

    def check(self) -> dict[str, Any]:
        try:
            config = load_config(self.resources_dir)
            return self.workspace_factory(config,
                self.resources_dir / "notion" / "state.json").check_connection()
        except (ValueError, NotionAPIError, OSError) as exc:
            raise HIQSPortError(str(exc) if isinstance(exc, (ValueError, NotionAPIError)) else
                                "Notion connection file cannot be read") from None

    def synchronize(self) -> dict[str, Any]:
        try:
            config = load_config(self.resources_dir)
            with self._sync_lock():
                projection = self.projection()
                return self.workspace_factory(config,
                    self.resources_dir / "notion" / "state.json").synchronize(projection)
        except (ValueError, NotionAPIError, OSError) as exc:
            raise HIQSPortError(str(exc) if isinstance(exc, (ValueError, NotionAPIError)) else
                                "Notion sync cannot access local resources") from None

    def worker(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.check()
        destination = payload.get("destination")
        if not isinstance(destination, str) or not destination:
            raise HIQSPortError("Worker plist destination is required")
        return worker_plist(self.resources_dir, Path(destination).expanduser(),
                            interval=int(payload.get("interval_seconds", 300)))

    @contextmanager
    def _sync_lock(self):
        directory = self.resources_dir / "notion"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "sync.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise HIQSPortError("Another Notion sync is running") from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
