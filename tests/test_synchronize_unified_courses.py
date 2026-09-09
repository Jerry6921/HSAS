import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from hsas.application.synchronize_unified_courses import UnifiedCourseSyncService
from hsas.infrastructure.manage_browser_session import BrowserSessionBroker


def test_unified_sync_uses_one_session_and_runs_collectors_concurrently() -> None:
    class Session:
        def __init__(self) -> None:
            self.active = 0
            self.maximum_active = 0
            self.all_started = asyncio.Event()

        async def _run(self, name: str):
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            if self.active == 3:
                self.all_started.set()
            await asyncio.wait_for(self.all_started.wait(), timeout=1)
            self.active -= 1
            return name

        async def sync_moodle(self, courses, **_kwargs):
            assert courses == [{"course_code": "BMED2206"}]
            return await self._run("moodle")

        async def sync_sis_course_info(self, courses, **_kwargs):
            assert courses == [{"course_code": "BMED2206"}]
            return await self._run("sis")

        async def sync_timetable(self, **_kwargs):
            return await self._run("timetable")

    class Broker:
        def __init__(self) -> None:
            self.open_count = 0
            self.session = Session()

        @asynccontextmanager
        async def open(self):
            self.open_count += 1
            yield self.session

    broker = Broker()
    result = asyncio.run(
        UnifiedCourseSyncService(broker).synchronize(
            [{"course_code": "BMED2206"}]
        )
    )

    assert broker.open_count == 1
    assert broker.session.maximum_active == 3
    assert result.values == ("moodle", "sis", "timetable")


def test_unified_sync_returns_source_errors_without_cancelling_other_sources() -> None:
    class Session:
        async def sync_moodle(self, _courses, **_kwargs):
            raise RuntimeError("moodle unavailable")

        async def sync_sis_course_info(self, _courses, **_kwargs):
            return "sis"

        async def sync_timetable(self, **_kwargs):
            return "timetable"

    class Broker:
        @asynccontextmanager
        async def open(self):
            yield Session()

    result = asyncio.run(UnifiedCourseSyncService(Broker()).synchronize([]))

    assert isinstance(result.moodle, RuntimeError)
    assert result.sis_course_info == "sis"
    assert result.timetable == "timetable"


def test_browser_broker_restores_and_saves_one_shared_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    context = object()
    lifecycle: list[tuple[str, object]] = []

    @asynccontextmanager
    async def fake_persistent_context(_settings, *, headless):
        assert headless is True
        lifecycle.append(("open", context))
        yield context
        lifecycle.append(("close", context))

    async def fake_restore(value, _path):
        lifecycle.append(("restore", value))

    async def fake_save(value, _path):
        lifecycle.append(("save", value))

    monkeypatch.setattr(
        "hsas.infrastructure.manage_browser_session.persistent_context",
        fake_persistent_context,
    )
    monkeypatch.setattr(
        "hsas.infrastructure.manage_browser_session.restore_sis_session",
        fake_restore,
    )
    monkeypatch.setattr(
        "hsas.infrastructure.manage_browser_session.save_sis_session",
        fake_save,
    )
    settings = SimpleNamespace(profile_dir=tmp_path / "browser-profile")
    broker = BrowserSessionBroker(resources_dir=tmp_path, settings=settings)

    async def run() -> None:
        async with broker.open() as session:
            assert session.context is context
            assert session.moodle.settings is settings
            assert session.sis.profile_dir == settings.profile_dir
            assert session.planner.profile_dir == settings.profile_dir

    asyncio.run(run())

    assert lifecycle == [
        ("open", context),
        ("restore", context),
        ("save", context),
        ("close", context),
    ]
