import json
from pathlib import Path

from hsas.infrastructure.moodle.load_settings import DEFAULT_CONFIG, DEFAULT_SELECTORS, Settings
from hsas.infrastructure.runtime.resolve_paths import RuntimePaths, ensure_resources_layout, get_runtime_paths


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


def test_runtime_paths_honor_data_directory_override(tmp_path: Path, monkeypatch) -> None:
    custom = tmp_path / "personal-data"
    monkeypatch.setenv("HSAS_DATA_DIR", str(custom))
    paths = get_runtime_paths()
    assert paths.resources_dir == custom.resolve() / "resources"
    assert Settings.load().output_dir == paths.resources_dir


def test_packaged_defaults_match_public_templates() -> None:
    root = Path(__file__).parents[1]
    assert DEFAULT_CONFIG.read_text(encoding="utf-8") == (root / "config/defaults.toml").read_text(encoding="utf-8")
    assert json.loads(DEFAULT_SELECTORS.read_text(encoding="utf-8")) == json.loads((root / "config/selectors.example.json").read_text(encoding="utf-8"))


def test_runtime_create_builds_private_layout(tmp_path: Path) -> None:
    paths = _runtime(tmp_path / "personal-data").create()
    assert (paths.resources_dir / "courses").is_dir()
    assert paths.browser_profile_dir.is_dir()


def test_resources_layout_resolves_custom_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    resources = ensure_resources_layout(Path("custom-resources"))
    assert resources == (tmp_path / "custom-resources").resolve()
    assert (resources / "courses").is_dir()
