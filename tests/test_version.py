from pathlib import Path
import tomllib

from hsas import __version__


def test_package_versions_stay_in_sync() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert __version__ == project["project"]["version"] == "2.4.0"
