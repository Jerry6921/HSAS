"""Official Notion REST transport. Credentials never appear in reports."""

from __future__ import annotations

import json
import math
import mimetypes
from pathlib import Path
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4
import certifi


class NotionAPIError(RuntimeError):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code
        super().__init__(f"Notion HTTP {status}: {code}")


class NotionClient:
    version = "2026-03-11"
    _read_retry_attempts = 3
    _read_retry_base_delay = 0.5
    _pace_lock = threading.Lock()
    _last_request = 0.0

    def __init__(self, token: str, *, timeout: int = 90):
        if not token or "\n" in token or "\r" in token:
            raise ValueError("A local Notion integration token is required")
        self._token = token
        self.timeout = timeout
        self._tls = ssl.create_default_context(cafile=certifi.where())

    def request(self, method: str, path: str, payload: dict | None = None,
                *, body: bytes | None = None, content_type: str = "application/json") -> dict:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Notion API paths must be relative")
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode()
        read = self._is_idempotent_read(method, path)
        attempts = self._read_retry_attempts if read else 1
        for attempt in range(attempts):
            self._pace()
            request = Request("https://api.notion.com/v1" + path, data=body, method=method,
                headers={"Authorization": f"Bearer {self._token}",
                    "Notion-Version": self.version, "Content-Type": content_type})
            try:
                with urlopen(request, timeout=self.timeout, context=self._tls) as response:
                    return json.load(response)
            except HTTPError as exc:
                code = self._error_code(exc)
                if read and exc.code in {429, *range(500, 600)} and attempt + 1 < attempts:
                    time.sleep(self._retry_delay(exc, attempt))
                    continue
                # Failed writes are not replayed: timeout/5xx can have committed.
                # The next sync reconciles by stable IDs before another mutation.
                if exc.code == 429:
                    time.sleep(self._retry_after(exc))
                raise NotionAPIError(exc.code, code) from None
            except (URLError, TimeoutError, OSError):
                raise NotionAPIError(0, "network_error") from None
        raise AssertionError("unreachable read retry state")

    @staticmethod
    def _is_idempotent_read(method: str, path: str) -> bool:
        verb = method.upper()
        clean_path = path.split("?", 1)[0]
        return verb == "GET" or (verb == "POST" and clean_path.endswith("/query"))

    @staticmethod
    def _error_code(exc: HTTPError) -> str:
        try:
            return json.load(exc).get("code", "api_error")
        except (ValueError, OSError):
            return "api_error"

    @classmethod
    def _retry_after(cls, exc: HTTPError) -> float:
        try:
            return min(60, max(1, float(exc.headers.get("Retry-After", "1"))))
        except (TypeError, ValueError):
            return 1.0

    @classmethod
    def _retry_delay(cls, exc: HTTPError, attempt: int) -> float:
        exponential = cls._read_retry_base_delay * (2 ** attempt)
        raw_retry_after = exc.headers.get("Retry-After")
        if raw_retry_after is None:
            return exponential
        try:
            retry_after = min(60, max(1, float(raw_retry_after)))
        except (TypeError, ValueError):
            retry_after = 1.0
        return max(exponential, retry_after)

    @staticmethod
    def _pace() -> None:
        # One process remains below Notion's average 3 requests/second limit.
        with NotionClient._pace_lock:
            time.sleep(max(0, 0.35 - (time.monotonic() - NotionClient._last_request)))
            NotionClient._last_request = time.monotonic()

    def rows(self, data_source_id: str) -> list[dict]:
        values, cursor = [], None
        while True:
            payload = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            response = self.request("POST", f"/data_sources/{data_source_id}/query", payload)
            values.extend(response["results"])
            if not response.get("has_more"):
                return values
            cursor = response["next_cursor"]

    def children(self, page_id: str) -> list[dict]:
        values, cursor = [], None
        while True:
            suffix = f"?page_size=100&start_cursor={cursor}" if cursor else "?page_size=100"
            result = self.request("GET", f"/blocks/{page_id}/children{suffix}")
            values.extend(result["results"])
            if not result.get("has_more"):
                return values
            cursor = result["next_cursor"]

    def upload(self, path: Path) -> str:
        """Upload original bytes, using multipart above 20 MiB (plan caps apply)."""
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunk_size = 10 * 1024 * 1024
        size = path.stat().st_size
        parts = math.ceil(size / chunk_size) if size > 20 * 1024 * 1024 else 1
        payload = {"filename": path.name, "content_type": mime,
                   "mode": "multi_part" if parts > 1 else "single_part"}
        if parts > 1:
            payload["number_of_parts"] = parts
        upload = self.request("POST", "/file_uploads", payload)
        with path.open("rb") as stream:
            for number in range(1, parts + 1):
                boundary = "hiqs-" + uuid4().hex
                data = stream.read(chunk_size) if parts > 1 else stream.read()
                # Filename is sent through the create endpoint; multipart uses a
                # conservative ASCII filename to prevent header injection.
                body = f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="original"\r\nContent-Type: {mime}\r\n\r\n'.encode() + data + b"\r\n"
                if parts > 1:
                    body += f'--{boundary}\r\nContent-Disposition: form-data; name="part_number"\r\n\r\n{number}\r\n'.encode()
                body += f"--{boundary}--\r\n".encode()
                self.request("POST", f"/file_uploads/{upload['id']}/send", body=body,
                             content_type=f"multipart/form-data; boundary={boundary}")
        if parts > 1:
            self.request("POST", f"/file_uploads/{upload['id']}/complete", {})
        return upload["id"]
