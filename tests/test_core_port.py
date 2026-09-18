from pathlib import Path

from hsas.core import HIQSCore, HIQSPort, build_port


def test_core_implements_public_port(tmp_path: Path) -> None:
    core = HIQSCore(resources_dir=tmp_path)

    assert isinstance(core, HIQSPort)
    assert core.resources_dir == tmp_path


def test_build_port_uses_explicit_resources_directory(tmp_path: Path) -> None:
    port = build_port(tmp_path)

    assert isinstance(port, HIQSPort)
    assert port.resources_dir == tmp_path
