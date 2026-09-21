from pathlib import Path

import pytest

from hsas.core import HIQSCore, HIQSPort, HIQSPortError, build_port


def test_core_implements_public_port(tmp_path: Path) -> None:
    core = HIQSCore(resources_dir=tmp_path)

    assert isinstance(core, HIQSPort)
    assert core.resources_dir == tmp_path


def test_build_port_uses_explicit_resources_directory(tmp_path: Path) -> None:
    port = build_port(tmp_path)

    assert isinstance(port, HIQSPort)
    assert port.resources_dir == tmp_path


def test_core_exposes_information_schema_and_empty_material_manifest(tmp_path: Path) -> None:
    core = HIQSCore(resources_dir=tmp_path)

    schema = core.information_update_schema()
    manifest = core.materials_manifest()

    assert schema["title"] == "InformationUpdate"
    assert manifest["document_count"] == 0
    assert manifest["documents"] == []


def test_core_rejects_string_as_course_id_list(tmp_path: Path) -> None:
    core = HIQSCore(resources_dir=tmp_path)

    with pytest.raises(HIQSPortError, match="list of strings"):
        core.search_materials({"query": "calculus", "course_ids": "142655"})
