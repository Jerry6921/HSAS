from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin

from playwright.async_api import BrowserContext, Page


class MoodleAjaxError(RuntimeError):
    pass


def _decode_json_strings(value: Any) -> Any:
    """Decode Moodle methods that return JSON inside a JSON string."""
    for _ in range(3):
        if not isinstance(value, str):
            break
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            break
    return value


def decode_ajax_response(payload: Any) -> dict[str, Any]:
    """Unwrap service.php's list/result/data envelope and double-encoded data."""
    payload = _decode_json_strings(payload)
    if isinstance(payload, list):
        if not payload:
            raise MoodleAjaxError("Moodle returned an empty AJAX response")
        payload = payload[0]

    if isinstance(payload, dict) and payload.get("error"):
        exception = payload.get("exception") or {}
        message = exception.get("message") if isinstance(exception, dict) else None
        raise MoodleAjaxError(message or "Moodle AJAX method returned an error")

    if isinstance(payload, dict) and "data" in payload:
        payload = _decode_json_strings(payload["data"])

    if not isinstance(payload, dict):
        raise MoodleAjaxError("Unexpected Moodle AJAX response shape")
    if not {"course", "section", "cm"}.issubset(payload):
        raise MoodleAjaxError("Course state is missing course, section, or cm data")
    return payload


async def get_live_sesskey(page: Page) -> str:
    # Read the live value; never put sesskey in .env, source code, logs, or output.
    value = await page.evaluate(
        "() => (window.M && M.cfg && M.cfg.sesskey) ? M.cfg.sesskey : null"
    )
    if not isinstance(value, str) or not value:
        raise MoodleAjaxError(
            "Could not read M.cfg.sesskey. Confirm the course page is logged in."
        )
    return value


async def fetch_course_state(
    context: BrowserContext,
    page: Page,
    *,
    base_url: str,
    course_id: str,
) -> dict[str, Any]:
    sesskey = await get_live_sesskey(page)
    service_url = urljoin(base_url.rstrip("/") + "/", "lib/ajax/service.php")
    request_body = [
        {
            "index": 0,
            "methodname": "core_courseformat_get_state",
            "args": {"courseid": int(course_id)},
        }
    ]
    response = await context.request.post(
        service_url,
        params={
            "sesskey": sesskey,
            "info": "core_courseformat_get_state",
        },
        data=request_body,
        fail_on_status_code=False,
    )
    if not response.ok:
        raise MoodleAjaxError(
            f"Moodle AJAX request failed with HTTP {response.status}"
        )
    try:
        payload = await response.json()
    except Exception as exc:
        raise MoodleAjaxError("Moodle AJAX response was not JSON") from exc
    return decode_ajax_response(payload)
