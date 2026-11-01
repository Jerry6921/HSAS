from pathlib import Path
import tomllib

from hsas import __version__


def test_package_versions_stay_in_sync() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert __version__ == project["project"]["version"]


def test_changelog_mentions_the_current_version() -> None:
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")

    assert f"## [{__version__}]" in changelog
