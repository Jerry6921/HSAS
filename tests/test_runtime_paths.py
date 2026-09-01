import json
from pathlib import Path
import subprocess

from hsas_runtime.migration import migrate_legacy_data
from hsas_runtime.paths import RuntimePaths, get_runtime_paths
from moodle_collector.settings import Settings
from updator.service import UpdateError, _validate_expected_commit, update_installation


def _runtime(root: Path) -> RuntimePaths:
    return RuntimePaths(
        data_dir=root,
        resources_dir=root / "resources",
        config_file=root / "config.toml",
        browser_profile_dir=root / "browser-profile",
        state_dir=root / "state",
        cache_dir=root / "cache",
        log_dir=root / "logs",
    )


def test_runtime_paths_honor_data_directory_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    custom = tmp_path / "personal-data"
    monkeypatch.setenv("HSAS_DATA_DIR", str(custom))

    paths = get_runtime_paths()

    assert paths.data_dir == custom.resolve()
    assert paths.resources_dir == custom.resolve() / "resources"
    assert paths.browser_profile_dir == custom.resolve() / "browser-profile"

    settings = Settings.load()
    assert str(settings.base_url).rstrip("/") == "https://moodle.hku.hk"
    assert settings.output_dir == custom.resolve() / "resources"
    assert settings.profile_dir == custom.resolve() / "browser-profile"


def test_https_update_requires_and_enforces_full_commit_pin() -> None:
    commit = "a" * 40
    try:
        _validate_expected_commit(
            commit,
            None,
            require_pin=True,
            dry_run=False,
        )
    except UpdateError as exc:
        assert "rerun with --commit" in str(exc)
    else:
        raise AssertionError("an unpinned HTTPS update should be rejected")

    _validate_expected_commit(
        commit,
        commit,
        require_pin=True,
        dry_run=False,
    )


def test_migration_copies_verifies_and_retains_legacy_data(tmp_path: Path) -> None:
    legacy = tmp_path / "checkout"
    destination = tmp_path / "user-data"
    resource = legacy / "src/resources/courses/1/course.json"
    profile = legacy / ".moodle-profile/Default/Cookies"
    resource.parent.mkdir(parents=True)
    profile.parent.mkdir(parents=True)
    resource.write_text('{"course": 1}', encoding="utf-8")
    profile.write_bytes(b"cookie database")
    (legacy / ".env").write_text(
        "MOODLE_BASE_URL=https://moodle.hku.hk\n"
        "MOODLE_HEADLESS=false\n",
        encoding="utf-8",
    )

    result = migrate_legacy_data(legacy, paths=_runtime(destination))

    assert result.copied_files == 2
    assert result.verified_files == 2
    assert resource.is_file()
    assert profile.is_file()
    assert (destination / "resources/courses/1/course.json").read_text() == '{"course": 1}'
    assert (destination / "browser-profile/Default/Cookies").read_bytes() == b"cookie database"
    assert "base_url" in (destination / "config.toml").read_text()
    report = json.loads((destination / "state/migration-report.json").read_text())
    assert report["verified_files"] == 2


def test_updater_preserves_resources_and_removes_manifest_obsolete_files(
    tmp_path: Path,
) -> None:
    release = tmp_path / "release"
    target = tmp_path / "installation"
    _write_project(release, command="new command")
    (release / "src/resources").mkdir(parents=True)
    (release / "src/resources/remote.json").write_text("remote")
    (release / "new.txt").write_text("new")
    _commit(release)

    _write_project(target, command="old command")
    (target / "src/resources").mkdir(parents=True)
    (target / "src/resources/personal.json").write_text("personal")
    (target / "old.txt").write_text("obsolete")
    state = tmp_path / "state"
    state.mkdir()
    (state / "update-manifest.json").write_text(
        json.dumps({"managed_files": ["old.txt"]})
    )

    result = update_installation(
        target,
        repository=str(release),
        branch="main",
        install_dependencies=False,
        state_dir=state,
    )

    assert result.dry_run is False
    assert (target / "src/command.py").read_text() == "VALUE = 'new command'\n"
    assert (target / "new.txt").read_text() == "new"
    assert not (target / "old.txt").exists()
    assert (target / "src/resources/personal.json").read_text() == "personal"
    assert not (target / "src/resources/remote.json").exists()


def test_updater_refuses_non_transactional_dependency_install_before_changes(
    tmp_path: Path,
) -> None:
    release = tmp_path / "release"
    target = tmp_path / "installation"
    _write_project(release, command="new command")
    _commit(release)
    _write_project(target, command="old command")
    state = tmp_path / "state"

    try:
        update_installation(
            target,
            repository=str(release),
            branch="main",
            install_dependencies=True,
            state_dir=state,
        )
    except Exception as exc:
        assert "not transactional" in str(exc)
    else:
        raise AssertionError("the simulated installer failure should abort the update")

    assert (target / "src/command.py").read_text() == "VALUE = 'old command'\n"
    assert not (state / "update-manifest.json").exists()


def _write_project(root: Path, *, command: str) -> None:
    (root / "src/updator").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "hku-study-assistance-system"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (root / "src/command.py").write_text(f"VALUE = {command!r}\n", encoding="utf-8")
    (root / "src/updator/service.py").write_text("VALUE = 'updater'\n", encoding="utf-8")


def _commit(repository: Path) -> None:
    commands = (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "tests@example.com"],
        ["git", "config", "user.name", "HSAS Tests"],
        ["git", "add", "."],
        ["git", "commit", "-m", "test release"],
    )
    for command in commands:
        subprocess.run(command, cwd=repository, check=True, capture_output=True)
