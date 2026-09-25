import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from hsas.infrastructure.moodle.activity_downloader import (
    _file_candidates,
    _page_candidates,
    _google_workspace_export_url,
    _is_storable,
    _save_response,
    download_activity_files,
)
from hsas.domain.courses.models import (
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


class GenericFileResponse:
    url = "https://moodle.example.edu/pluginfile.php/1/example.ipynb"
    headers = {"content-type": "application/octet-stream"}


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


class RecursiveResponse:
    def __init__(self, url: str, body: bytes, content_type: str) -> None:
        self.url = url
        self.status = 200
        self.ok = True
        self.headers = {"content-type": content_type, "content-length": str(len(body))}
        self._body = body

    async def text(self) -> str:
        return self._body.decode("utf-8")

    async def body(self) -> bytes:
        return self._body

    async def dispose(self) -> None:
        return None


class RecursiveRequest:
    async def get(self, url: str, **_kwargs):
        pages = {
            "https://moodle.example.edu/mod/url/view.php?id=7&redirect=1": (
                '<a href="/mod/url/view.php?id=8">details</a>', "text/html"
            ),
            "https://moodle.example.edu/mod/url/view.php?id=8": (
                '<a href="/mod/resource/view.php?id=9">resource</a>', "text/html"
            ),
            "https://moodle.example.edu/mod/resource/view.php?id=9": (
                '<a href="/pluginfile.php/1/tutorial.pdf">file</a>', "text/html"
            ),
            "https://moodle.example.edu/pluginfile.php/1/tutorial.pdf": (
                "%PDF-1.7 tutorial", "application/pdf"
            ),
        }
        body, content_type = pages[url]
        return RecursiveResponse(url, body.encode() if isinstance(body, str) else body, content_type)


class RecursiveContext:
    def __init__(self) -> None:
        self.request = RecursiveRequest()


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


def test_staged_previous_file_does_not_force_numeric_suffix(tmp_path: Path) -> None:
    body = b"%PDF- current"
    destination = tmp_path / "courses/1/files/10-slides"
    path = destination / "slides.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF- copied previous snapshot")
    activity = CourseActivity(
        module_id="10",
        name="Slides",
        category="resource",
        module="resource",
    )

    stored = asyncio.run(
        _save_response(
            FakeResponse(body),
            activity=activity,
            index=1,
            destination_dir=destination,
            storage_root=tmp_path,
            max_download_bytes=1024,
            claimed_paths=set(),
        )
    )

    assert stored is not None
    assert stored.relative_path == path.relative_to(tmp_path).as_posix()
    assert path.read_bytes() == body
    assert not (destination / "slides-1.pdf").exists()


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

    assert activity.download_status == "downloaded", activity.download_error
    assert activity.files[0].relative_path == previous.relative_path
    assert activity.files[0].validated_at is not None
    _, kwargs = context.request.calls[0]
    assert kwargs["headers"] == {
        "If-None-Match": '"slides-v1"',
        "If-Modified-Since": "Sat, 01 Aug 2026 00:00:00 GMT",
    }


def test_generic_moodle_files_and_google_workspace_exports_are_supported() -> None:
    assert _is_storable(GenericFileResponse()) is True
    assert _google_workspace_export_url(
        "https://docs.google.com/document/d/doc_123/edit?usp=sharing"
    ) == "https://docs.google.com/document/d/doc_123/export?format=docx"
    assert _google_workspace_export_url(
        "https://docs.google.com/presentation/d/slides-456/edit"
    ) == "https://docs.google.com/presentation/d/slides-456/export/pptx"
    assert _google_workspace_export_url("https://example.com/document/d/123") is None
    assert _file_candidates(
        '<a href="https://docs.google.com/document/d/doc_123/edit">Brief</a>',
        "https://moodle.example.edu/mod/url/view.php?id=7",
        "https://moodle.example.edu",
    ) == ["https://docs.google.com/document/d/doc_123/export?format=docx"]


def test_recursive_page_candidates_follow_content_but_not_moodle_navigation() -> None:
    html = """
    <a href="/mod/url/view.php?id=8">Tutorial details</a>
    <a href="/course/view.php?id=123">Course home</a>
    <a href="/my/">Dashboard</a>
    <a href="/mod/forum/discuss.php?d=12">Forum discussion</a>
    <a href="/mod/assign/view.php?id=9">Assignment workflow</a>
    <a href="https://external.example/file.pdf">External PDF</a>
    <a href="/pluginfile.php/1/handout.pdf">Handout</a>
    """

    assert _page_candidates(
        html,
        "https://moodle.example.edu/mod/url/view.php?id=7",
        "https://moodle.example.edu",
    ) == ["https://moodle.example.edu/mod/url/view.php?id=8"]


def test_download_activity_recursively_collects_files_through_html_pages(tmp_path: Path) -> None:
    activity = CourseActivity(
        module_id="7",
        name="Tutorial Information",
        category="url",
        module="url",
        url="https://moodle.example.edu/mod/url/view.php?id=7",
        download_status="pending",
    )

    destination = tmp_path / "files"
    destination.mkdir()
    asyncio.run(download_activity_files(
        RecursiveContext(),
        activity,
        base_url="https://moodle.example.edu",
        destination_dir=destination,
        storage_root=tmp_path,
        max_download_bytes=1024 * 1024,
        timeout_ms=1000,
        max_link_depth=6,
    ))

    assert activity.download_status == "downloaded", activity.download_error
    assert [str(file.source_url) for file in activity.files] == [
        "https://moodle.example.edu/pluginfile.php/1/tutorial.pdf"
    ]
    assert len(activity.linked_pages) == 3
    assert [page.depth for page in activity.linked_pages] == [0, 1, 2]
    assert activity.linked_pages[2].content_text == "file"
