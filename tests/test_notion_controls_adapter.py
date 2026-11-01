"""The Notion control page is the only surface a non-technical user touches.

The adapter turns the status packet into Notion property objects. A wrong type
there is not a crash: Notion silently rejects or blanks the property, so the page
looks fine and reports nothing. The payload shape is therefore the contract.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hsas.infrastructure.notion import controls as controls_module
from hsas.infrastructure.notion.controls import NotionControlsAdapter


class _FakeClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.rows_payload: list[dict] = []

    def request(self, method: str, path: str, payload: dict | None = None, **_kwargs):
        self.requests.append((method, path, payload or {}))
        return {}

    def rows(self, _source: str) -> list[dict]:
        return self.rows_payload


def _adapter(tmp_path: Path, monkeypatch, *, source: str | None = "ds-controls"):
    client = _FakeClient()
    monkeypatch.setattr(
        controls_module,
        "load_config",
        lambda _resources: {"token": "secret", "data_sources": {"controls": source}},
    )
    monkeypatch.setattr(controls_module, "NotionClient", lambda _token: client)
    return NotionControlsAdapter(tmp_path), client


def test_an_unconfigured_control_source_fails_instead_of_writing_elsewhere(
    tmp_path: Path, monkeypatch,
) -> None:
    with pytest.raises(ValueError, match="controls data source is not configured"):
        _adapter(tmp_path, monkeypatch, source=None)


def test_each_field_maps_to_the_notion_property_type_the_page_defines(
    tmp_path: Path, monkeypatch,
) -> None:
    adapter, client = _adapter(tmp_path, monkeypatch)

    adapter.update(
        "page-1",
        {
            "状态": "运行中",
            "操作": "同步课程",
            "角色": "请求",
            "阶段进度": 0.4,
            "阶段完成": 2,
            "阶段总数": 5,
            "待整理": 4,
            "取消请求": 1,
            "阶段": "Moodle 课程资料",
            "任务 ID": "",
        },
    )

    method, path, payload = client.requests[-1]
    properties = payload["properties"]
    assert (method, path) == ("PATCH", "/pages/page-1")
    assert properties["状态"] == {"select": {"name": "运行中"}}
    assert properties["操作"] == {"select": {"name": "同步课程"}}
    assert properties["角色"] == {"select": {"name": "请求"}}
    assert properties["阶段进度"] == {"number": 0.4}
    assert properties["阶段完成"] == {"number": 2}
    assert properties["阶段总数"] == {"number": 5}
    assert properties["待整理"] == {"number": 4}
    assert properties["取消请求"] == {"checkbox": True}
    assert "rich_text" in properties["阶段"]
    assert properties["任务 ID"]["rich_text"] == []
    assert datetime.fromisoformat(properties["更新时间"]["date"]["start"])


def test_publishing_the_same_state_twice_does_not_write_twice(
    tmp_path: Path, monkeypatch,
) -> None:
    adapter, client = _adapter(tmp_path, monkeypatch)
    values = {"状态": "运行中", "待整理": 3}

    adapter.publish("page-1", values)
    adapter.publish("page-1", values)
    assert len(client.requests) == 1

    adapter.publish("page-1", {"状态": "完成", "待整理": 0})
    assert len(client.requests) == 2

    adapter.publish("page-2", values)
    assert len(client.requests) == 3, "a different page is a different fingerprint"


def test_rows_expose_plain_values_instead_of_notion_property_objects(
    tmp_path: Path, monkeypatch,
) -> None:
    adapter, client = _adapter(tmp_path, monkeypatch)
    client.rows_payload = [
        {
            "id": "row-1",
            "created_time": "2026-11-02T00:00:00Z",
            "properties": {
                "名称": {"title": [{"text": {"content": "HIQS 同步状态"}}]},
                "待整理": {"number": 4},
                "状态": {"select": {"name": "运行中"}},
                "取消请求": {"checkbox": False},
            },
        }
    ]

    rows = adapter.rows()

    assert rows == [
        {
            "id": "row-1",
            "created_time": "2026-11-02T00:00:00Z",
            "名称": "HIQS 同步状态",
            "待整理": 4,
            "状态": "运行中",
            "取消请求": False,
        }
    ]
