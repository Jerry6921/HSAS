import json
from pathlib import Path
import subprocess

from hsas.infrastructure.runtime.migrate_data import migrate_legacy_data
from hsas.infrastructure.runtime.resolve_paths import RuntimePaths, ensure_resources_layout, get_runtime_paths
from hsas.infrastructure.moodle.load_settings import (
    DEFAULT_CONFIG,
    DEFAULT_SELECTORS,
    Settings,
)
from hsas.infrastructure.updates.update_installation import UpdateError, _validate_expected_commit, update_installation


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


def test_packaged_moodle_defaults_are_loadable_and_match_public_templates() -> None:
    root = Path(__file__).parents[1]
    settings = Settings()
    selectors = settings.selectors()

    assert selectors.dashboard_ready
    assert selectors.course_links
    assert DEFAULT_CONFIG.read_text(encoding="utf-8") == (
        root / "config/defaults.toml"
    ).read_text(encoding="utf-8")
    assert json.loads(DEFAULT_SELECTORS.read_text(encoding="utf-8")) == json.loads(
        (root / "config/selectors.example.json").read_text(encoding="utf-8")
    )


def test_runtime_create_builds_the_stable_directory_layout(tmp_path: Path) -> None:
    paths = _runtime(tmp_path / "personal-data").create()

    assert paths.data_dir.is_dir()
    assert (paths.resources_dir / "courses").is_dir()
    assert paths.browser_profile_dir.is_dir()
    assert paths.state_dir.is_dir()
    assert paths.cache_dir.is_dir()
    assert paths.log_dir.is_dir()


def test_resources_layout_expands_and_resolves_custom_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    resources = ensure_resources_layout(Path("custom-resources"))

    assert resources == (tmp_path / "custom-resources").resolve()
    assert resources.is_dir()
    assert (resources / "courses").is_dir()


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
    assert (target / "src/hsas/interfaces/run_cli.py").read_text() == "VALUE = 'new command'\n"
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

    assert (target / "src/hsas/interfaces/run_cli.py").read_text() == "VALUE = 'old command'\n"
    assert not (state / "update-manifest.json").exists()


def _write_project(root: Path, *, command: str) -> None:
    (root / "src/hsas/interfaces").mkdir(parents=True)
    (root / "src/hsas/infrastructure/updates").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "hku-study-assistance-system"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (root / "src/hsas/interfaces/run_cli.py").write_text(
        f"VALUE = {command!r}\n",
        encoding="utf-8",
    )
    (root / "src/hsas/infrastructure/updates/update_installation.py").write_text(
        "VALUE = 'updater'\n",
        encoding="utf-8",
    )


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
