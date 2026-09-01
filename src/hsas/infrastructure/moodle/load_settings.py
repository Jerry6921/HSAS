from __future__ import annotations

import json
import os
from pathlib import Path
import tomllib

from dotenv import dotenv_values
from pydantic import BaseModel, Field, HttpUrl, model_validator

from hsas.infrastructure.runtime import get_runtime_paths


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = PROJECT_ROOT / "config/defaults.toml"
ENV_FIELDS = {
    "MOODLE_BASE_URL": "base_url",
    "MOODLE_LOGIN_URL": "login_url",
    "MOODLE_DASHBOARD_URL": "dashboard_url",
    "MOODLE_SELECTOR_CONFIG": "selector_config",
    "MOODLE_HEADLESS": "headless",
    "MOODLE_NAVIGATION_TIMEOUT_MS": "navigation_timeout_ms",
    "MOODLE_MAX_DOWNLOAD_BYTES": "max_download_bytes",
    "MOODLE_DOWNLOAD_CONCURRENCY": "download_concurrency",
}


class SelectorConfig(BaseModel):
    dashboard_ready: list[str] = Field(min_length=1)
    course_links: list[str] = Field(min_length=1)
    course_title: list[str] = Field(min_length=1)
    sections: list[str] = Field(min_length=1)
    section_title: list[str] = Field(min_length=1)
    activity_links: list[str] = Field(min_length=1)
    activity_name: list[str] = Field(min_length=1)
    activity_description: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "SelectorConfig":
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))


class Settings(BaseModel):
    base_url: HttpUrl = HttpUrl("https://moodle.hku.hk")
    login_url: HttpUrl = HttpUrl("https://moodle.hku.hk/login/index.php")
    dashboard_url: HttpUrl = HttpUrl("https://moodle.hku.hk/my/")
    selector_config: Path = PROJECT_ROOT / "config/selectors.example.json"
    profile_dir: Path = Field(
        default_factory=lambda: get_runtime_paths().browser_profile_dir
    )
    output_dir: Path = Field(default_factory=lambda: get_runtime_paths().resources_dir)
    headless: bool = True
    navigation_timeout_ms: int = Field(default=30_000, ge=1_000)
    max_download_bytes: int = Field(default=104_857_600, ge=1_024)
    download_concurrency: int = Field(default=3, ge=1, le=8)

    @classmethod
    def load(cls, **overrides) -> "Settings":
        """Load public defaults, user config, optional .env, and environment."""
        paths = get_runtime_paths()
        values: dict[str, object] = {
            "profile_dir": paths.browser_profile_dir,
            "output_dir": paths.resources_dir,
            "selector_config": PROJECT_ROOT / "config/selectors.example.json",
        }
        values.update(_read_moodle_toml(DEFAULT_CONFIG))
        user_values = _read_moodle_toml(paths.config_file)
        selector = user_values.get("selector_config")
        if isinstance(selector, str) and not Path(selector).is_absolute():
            user_values["selector_config"] = paths.data_dir / selector
        values.update(user_values)

        dotenv = dotenv_values(PROJECT_ROOT / ".env")
        for environment_name, field_name in ENV_FIELDS.items():
            raw = os.environ.get(environment_name, dotenv.get(environment_name))
            if raw is not None and str(raw).strip():
                values[field_name] = raw
        selector_value = values.get("selector_config")
        if selector_value is not None and not Path(selector_value).is_absolute():
            values["selector_config"] = PROJECT_ROOT / Path(selector_value)
        values.update(overrides)
        return cls.model_validate(values)

    @model_validator(mode="after")
    def ensure_same_origin(self) -> "Settings":
        # A typo that sends an authenticated browser to another host should fail early.
        if self.base_url.host != self.dashboard_url.host:
            raise ValueError("base_url and dashboard_url must use the same host")
        return self

    def selectors(self) -> SelectorConfig:
        return SelectorConfig.load(self.selector_config)


def _read_moodle_toml(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"invalid HSAS config {path}: {exc}") from exc
    moodle = value.get("moodle", {})
    if not isinstance(moodle, dict):
        raise ValueError(f"invalid HSAS config {path}: [moodle] must be a table")
    return moodle
