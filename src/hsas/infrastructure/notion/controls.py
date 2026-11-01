"""Native Notion request queue and progress/prompt publishing."""

from datetime import UTC, datetime
import json

from hsas.domain.information.notion_properties import date_property, rich_text, select
from hsas.infrastructure.notion.client import NotionClient
from hsas.infrastructure.notion.config import load_config
from hsas.infrastructure.notion.export import plain_property


class NotionControlsAdapter:
    def __init__(self, resources):
        self.config = load_config(resources)
        self.source = self.config.get("data_sources", {}).get("controls")
        if not self.source:
            raise ValueError("Notion controls data source is not configured")
        self.client = NotionClient(self.config["token"])
        self._published = {}

    def rows(self):
        return [{"id": row["id"], "created_time": row.get("created_time", ""),
            **{k: plain_property(v) for k, v in row["properties"].items()}}
            for row in self.client.rows(self.source)]

    def update(self, page_id: str, values: dict):
        properties = {}
        for name, value in values.items():
            if name in {"状态", "操作", "角色"}:
                properties[name] = select(value)
            elif name in {"阶段进度", "阶段完成", "阶段总数", "待整理"}:
                properties[name] = {"number": value}
            elif name == "取消请求":
                properties[name] = {"checkbox": bool(value)}
            else:
                properties[name] = rich_text(str(value or ""))
        properties["更新时间"] = date_property(datetime.now(UTC).isoformat())
        self.client.request("PATCH", f"/pages/{page_id}", {"properties": properties})

    def publish(self, page_id: str, values: dict):
        fingerprint = json.dumps(values, sort_keys=True, ensure_ascii=False)
        if self._published.get(page_id) == fingerprint:
            return
        self.update(page_id, values)
        self._published[page_id] = fingerprint
