import asyncio
from pathlib import Path

from hsas.application.ports.gateways import CourseCatalogEntry, SyncCourseResult
from hsas.infrastructure.browser.session import BrowserSyncSession


def test_moodle_sync_collects_every_course_shell_with_the_same_course_code(
    tmp_path: Path,
) -> None:
    class Moodle:
        calls: list[str] = []

        async def sync_course_in_context(self, _context, course_id: str, **_kwargs):
            self.calls.append(course_id)
            return SyncCourseResult(
                course_id=course_id,
                course_title=f"MATH1851 archive {course_id}",
                change_count=0,
                output_path=tmp_path / "courses" / course_id / "course.json",
            )

    moodle = Moodle()
    session = BrowserSyncSession(
        context=object(),
        resources_dir=tmp_path,
        moodle=moodle,
        sis=object(),
        planner=object(),
    )
    session._available_by_code["MATH1851"] = [
        CourseCatalogEntry(
            course_id="142655",
            title="MATH1851 Section 1B",
            url=None,
            downloaded=True,
        ),
        CourseCatalogEntry(
            course_id="146267",
            title="MATH1851_1AB shared materials",
            url=None,
            downloaded=True,
        ),
    ]
    session._moodle_catalog_ready.set()

    result = asyncio.run(
        session.sync_moodle(
            [{"course_code": "MATH1851", "title": "Calculus"}],
            progress_callback=None,
            cancel_requested=None,
        )
    )

    assert moodle.calls == ["142655", "146267"]
    assert result == {"completed": 1, "failures": []}
