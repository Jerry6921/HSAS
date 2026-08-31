from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, HttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="MOODLE_", extra="ignore"
    )

    base_url: HttpUrl
    login_url: HttpUrl
    dashboard_url: HttpUrl
    selector_config: Path = Path("config/selectors.example.json")
    profile_dir: Path = Path(".moodle-profile")
    output_dir: Path = Path("output")
    headless: bool = True
    navigation_timeout_ms: int = Field(default=30_000, ge=1_000)
    max_download_bytes: int = Field(default=104_857_600, ge=1_024)
    download_concurrency: int = Field(default=3, ge=1, le=8)

    @model_validator(mode="after")
    def ensure_same_origin(self) -> "Settings":
        # A typo that sends an authenticated browser to another host should fail early.
        if self.base_url.host != self.dashboard_url.host:
            raise ValueError("base_url and dashboard_url must use the same host")
        return self

    def selectors(self) -> SelectorConfig:
        return SelectorConfig.load(self.selector_config)
