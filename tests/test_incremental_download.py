import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from moodle_collector.acquisition.file_downloader import (
    _save_response,
    download_activity_files,
)
from moodle_collector.transformation.common.course_schema import (
    CourseActivity,
    StoredFile,
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.url = "https://moodle.example.edu/pluginfile.php/1/slides.pdf"
        self.headers = {
            "content-type": "application/pdf",
            "content-length": str(len(body)),
        }

    async def body(self) -> bytes:
        return self._body


class NotModifiedResponse:
    status = 304
    ok = False
    url = "https://moodle.example.edu/pluginfile.php/1/slides.pdf"
    headers = {}

    async def dispose(self) -> None:
        return None


class FakeRequest:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return NotModifiedResponse()


class FakeContext:
    def __init__(self) -> None:
        self.request = FakeRequest()


def test_incremental_download_reuses_unchanged_file_and_path(tmp_path: Path) -> None:
    body = b"%PDF- unchanged"
    destination = tmp_path / "courses/1/files/10-slides"
    path = destination / "slides.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(body)
    old_time = datetime(2026, 8, 1, tzinfo=timezone.utc)
    previous = StoredFile(
        filename="slides.pdf",
        relative_path=path.relative_to(tmp_path).as_posix(),
        source_url="https://moodle.example.edu/pluginfile.php/1/slides.pdf",
        content_type="application/pdf",
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        downloaded_at=old_time,
    )
    activity = CourseActivity(
        module_id="10",
        name="Slides",
        category="resource",
        module="resource",
    )

    stored = asyncio.run(_save_response(
        FakeResponse(body),
        activity=activity,
        index=1,
        destination_dir=destination,
        storage_root=tmp_path,
        max_download_bytes=1024,
        previous_files={str(previous.source_url): previous},
    ))

    assert stored is not None
    assert stored.relative_path == previous.relative_path
    assert stored.downloaded_at == old_time
    assert list(destination.iterdir()) == [path]


def test_conditional_get_reuses_local_file_on_http_304(tmp_path: Path) -> None:
    body = b"%PDF- cached"
    destination = tmp_path / "courses/1/files/10-slides"
    path = destination / "slides.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(body)
    previous = StoredFile(
        filename="slides.pdf",
        relative_path=path.relative_to(tmp_path).as_posix(),
        source_url="https://moodle.example.edu/pluginfile.php/1/slides.pdf",
        content_type="application/pdf",
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
        downloaded_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        etag='"slides-v1"',
        last_modified="Sat, 01 Aug 2026 00:00:00 GMT",
    )
    old_activity = CourseActivity(
        module_id="10",
        name="Slides",
        category="resource",
        module="resource",
        files=[previous],
        download_status="downloaded",
    )
    activity = CourseActivity(
        module_id="10",
        name="Slides",
        category="resource",
        module="resource",
        url="https://moodle.example.edu/mod/resource/view.php?id=10",
        download_status="pending",
    )
    context = FakeContext()

    asyncio.run(download_activity_files(
        context,
        activity,
        base_url="https://moodle.example.edu",
        destination_dir=destination,
        storage_root=tmp_path,
        max_download_bytes=1024,
        timeout_ms=1000,
        previous_activity=old_activity,
    ))

    assert activity.download_status == "downloaded"
    assert activity.files[0].relative_path == previous.relative_path
    assert activity.files[0].validated_at is not None
    _, kwargs = context.request.calls[0]
    assert kwargs["headers"] == {
        "If-None-Match": '"slides-v1"',
        "If-Modified-Since": "Sat, 01 Aug 2026 00:00:00 GMT",
    }
