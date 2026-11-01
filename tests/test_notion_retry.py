"""Notion reads retry bounded transient failures; writes are never replayed."""

from __future__ import annotations

import io
import json

import pytest

from hsas.infrastructure.notion import client as client_module
from hsas.infrastructure.notion.client import NotionAPIError, NotionClient


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def json(self) -> dict:
        return self._payload


def _http_error(status: int, *, retry_after: str | None = None) -> Exception:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return client_module.HTTPError(
        "https://api.notion.com",
        status,
        "error",
        headers,
        io.BytesIO(json.dumps({"code": "rate_limited"}).encode()),
    )


def _install(monkeypatch, outcomes: list[object]):
    calls: list[str] = []

    def fake_urlopen(request, timeout=None, context=None):  # noqa: ANN001
        calls.append(request.get_method())
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(client_module.time, "sleep", lambda *_args: None)
    NotionClient._last_request = 0.0
    return calls


def test_read_retries_rate_limit_then_succeeds(monkeypatch) -> None:
    calls = _install(
        monkeypatch,
        [_http_error(429, retry_after="1"), _Response({"results": []})],
    )

    payload = NotionClient("token").request("GET", "/users/me")

    assert payload == {"results": []}
    assert len(calls) == 2


def test_read_retries_server_errors_until_exhausted(monkeypatch) -> None:
    calls = _install(
        monkeypatch,
        [_http_error(500), _http_error(503), _http_error(502)],
    )

    with pytest.raises(NotionAPIError) as excinfo:
        NotionClient("token").request("GET", "/users/me")

    assert excinfo.value.status == 502
    assert len(calls) == 3


def test_read_does_not_retry_client_errors(monkeypatch) -> None:
    calls = _install(monkeypatch, [_http_error(404)])

    with pytest.raises(NotionAPIError) as excinfo:
        NotionClient("token").request("GET", "/users/me")

    assert excinfo.value.status == 404
    assert len(calls) == 1


def test_write_is_never_replayed(monkeypatch) -> None:
    calls = _install(monkeypatch, [_http_error(429, retry_after="1")])

    with pytest.raises(NotionAPIError):
        NotionClient("token").request("POST", "/pages", {"parent": {}})

    assert len(calls) == 1
