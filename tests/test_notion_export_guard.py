"""Notion export is a private-data write: it needs confirmation and a path boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from hsas.core.ports import HIQSPortError
from hsas.core.services.materials import MaterialQueryService
from hsas.core.services.notion import NotionDeliveryService
from hsas.domain.information import InformationStore
from hsas.infrastructure.storage.json_store import write_model


def _service(resources: Path) -> NotionDeliveryService:
    write_model(resources / "information.json", InformationStore())
    return NotionDeliveryService(
        resources_dir=resources,
        materials=MaterialQueryService(resources_dir=resources),
    )


def test_export_requires_confirmation(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(HIQSPortError, match="确认"):
        service.export({"destination": str(tmp_path / "exports" / "run")})


def test_export_refuses_agent_path_outside_exports_root(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(HIQSPortError, match="exports"):
        service.export(
            {"confirmed": True, "destination": str(tmp_path / "elsewhere")}
        )


def test_export_writes_inside_private_exports_root(tmp_path: Path) -> None:
    service = _service(tmp_path)
    destination = tmp_path / "exports" / "run"

    result = service.export({"confirmed": True, "destination": str(destination)})

    assert result["destination"] == str(destination.resolve())
    assert (destination / "notion-plan.json").is_file()
    assert (destination / "README.md").is_file()
