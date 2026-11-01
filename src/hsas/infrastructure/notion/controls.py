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
        self._prompt_block = None
        self._home_prompt_block = None
        self._last_prompt = None

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

    def publish(self, page_id: str, values: dict, *, prompt_page: bool = False):
        fingerprint = json.dumps(values, sort_keys=True, ensure_ascii=False)
        if self._published.get(page_id) == fingerprint:
            return
        self.update(page_id, values)
        prompt = values.get("AI 整理提示词")
        if prompt_page and prompt and prompt != self._last_prompt:
            if self._prompt_block is None:
                blocks = self.client.children(page_id)
                block = next((b for b in blocks if b.get("type") == "code"), None)
                if block:
                    self._prompt_block = block["id"]
            if self._prompt_block:
                self.client.request("PATCH", f"/blocks/{self._prompt_block}", {"code": {
                    "language": "plain text",
                    "rich_text": rich_text(prompt)["rich_text"]}})
            if self._home_prompt_block is None:
                home = self.client.children(self.config["parent_page_id"])
                for block in home:
                    if block.get("type") != "toggle":
                        continue
                    label = "".join(v.get("plain_text") or v.get("text", {}).get("content", "")
                                    for v in block["toggle"].get("rich_text", []))
                    if "复制 AI 整理提示词" not in label:
                        continue
                    nested = self.client.children(block["id"])
                    code = next((b for b in nested if b.get("type") == "code"), None)
                    if code:
                        self._home_prompt_block = code["id"]
            if self._home_prompt_block:
                self.client.request("PATCH", f"/blocks/{self._home_prompt_block}", {"code": {
                    "language": "plain text", "rich_text": rich_text(prompt)["rich_text"]}})
            self._last_prompt = prompt
        self._published[page_id] = fingerprint
