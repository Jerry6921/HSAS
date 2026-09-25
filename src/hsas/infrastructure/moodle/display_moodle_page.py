"""Display one authenticated Moodle page without exposing browser credentials."""

from __future__ import annotations

import base64
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .fetch_moodle import persistent_context
from .load_settings import Settings


class MoodlePreviewError(RuntimeError):
    """A safe failure while rendering an authenticated Moodle page."""


def _safe_display_url(value: str) -> str:
    parsed = urlparse(value)
    hidden = {"key", "sesskey", "token", "wstoken"}
    query = [(key, item) for key, item in parse_qsl(parsed.query) if key.lower() not in hidden]
    return urlunparse(parsed._replace(query=urlencode(query), fragment=""))


def validate_moodle_url(value: str, settings: Settings) -> str:
    """Allow navigation only to the configured HTTPS Moodle origin."""
    parsed = urlparse(value)
    allowed_host = settings.base_url.host
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.hostname.lower() != str(allowed_host).lower()
    ):
        raise MoodlePreviewError("只能在内置预览中打开当前配置的 Moodle 链接。")
    return value


async def preview_moodle_page(settings: Settings, value: str) -> dict[str, object]:
    """Navigate the shared profile and return a bounded visual/text preview."""
    target = validate_moodle_url(value, settings)
    async with persistent_context(settings, headless=True) as context:
        page = await context.new_page()
        try:
            await page.goto(target, wait_until="domcontentloaded")
            parsed_final = urlparse(page.url)
            if parsed_final.hostname != settings.base_url.host:
                raise MoodlePreviewError("Moodle 登录已过期，请先在资料中心完成登录或同步。")
            if parsed_final.path.rstrip("/").endswith("/login/index.php"):
                raise MoodlePreviewError("Moodle 登录已过期，请先在资料中心完成登录或同步。")
            title = (await page.title()).strip() or "Moodle 页面"
            text = " ".join((await page.locator("body").inner_text()).split())[:30_000]
            screenshot = await page.screenshot(type="jpeg", quality=82, full_page=False)
            return {
                "title": title,
                "preview_kind": "web",
                "final_url": _safe_display_url(page.url),
                "text": text,
                "screenshot_data_url": (
                    "data:image/jpeg;base64," + base64.b64encode(screenshot).decode("ascii")
                ),
            }
        finally:
            await page.close()


__all__ = ["MoodlePreviewError", "preview_moodle_page", "validate_moodle_url"]
