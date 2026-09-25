from pathlib import Path

import pytest

from hsas.core import HIQSCore, HIQSPortError
from hsas.infrastructure.moodle.load_settings import Settings
from hsas.infrastructure.moodle.display_moodle_page import (
    MoodlePreviewError,
    validate_moodle_url,
)


def settings(tmp_path: Path) -> Settings:
    return Settings(output_dir=tmp_path, profile_dir=tmp_path / "browser-profile")


def test_moodle_preview_accepts_only_configured_https_origin(tmp_path: Path) -> None:
    configured = settings(tmp_path)
    assert validate_moodle_url("https://moodle.hku.hk/mod/assign/view.php?id=1", configured)
    with pytest.raises(MoodlePreviewError, match="当前配置"):
        validate_moodle_url("https://example.com/mod/assign/view.php?id=1", configured)
    with pytest.raises(MoodlePreviewError, match="当前配置"):
        validate_moodle_url("http://moodle.hku.hk/mod/assign/view.php?id=1", configured)


def test_moodle_preview_does_not_compete_with_active_sync(tmp_path: Path) -> None:
    core = HIQSCore(resources_dir=tmp_path)
    core.sync_controller.job["state"] = "running"

    with pytest.raises(HIQSPortError, match="同步正在使用浏览器"):
        core.moodle_page_preview({"url": "https://moodle.hku.hk/mod/assign/view.php?id=1"})
