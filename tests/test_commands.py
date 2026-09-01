import asyncio
import json
from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

from command import app
from integrated_planner.profile_schema import StudentProfile
from hsas_application import assess_plan_freshness
from moodle_collector.workflow import _persist_course, _resolve_course_target
from moodle_collector.sync_report import record_sync_operation
from moodle_collector.settings import Settings
from moodle_collector.storage.local_store import write_json, write_model
from moodle_collector.transformation.assessment.schema import AssessmentOverview
from moodle_collector.transformation.common.course_mapper import build_course_archive


ROOT = Path(__file__).parents[1]


def test_cli_exposes_only_the_unified_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    command_names = {
        command.name or command.callback.__name__.replace("_", "-")
        for command in app.registered_commands
    }
    group_names = {group.name for group in app.registered_groups}

    assert result.exit_code == 0
    assert command_names == {
        "list-status",
        "login",
        "migrate-data",
        "sync-courses",
        "update-hsas",
        "update-plan",
    }
    assert group_names == {"profile", "execution", "materials"}


def test_sync_target_accepts_an_id_or_same_origin_url() -> None:
    base_url = "https://moodle.example.edu"

    assert _resolve_course_target("123", base_url) == (
        "123",
        "https://moodle.example.edu/course/view.php?id=123",
    )
    assert _resolve_course_target(
        "https://moodle.example.edu/course/view.php?id=456",
        base_url,
    ) == ("456", "https://moodle.example.edu/course/view.php?id=456")


def test_unified_sync_command_dispatches_single_or_all(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("command.sync_all", lambda _settings: calls.append("all"))
    monkeypatch.setattr(
        "command.sync_course",
        lambda course, _settings: calls.append(f"single:{course}"),
    )

    all_result = CliRunner().invoke(app, ["sync-courses"])
    single_result = CliRunner().invoke(app, ["sync-courses", "138907"])

    assert all_result.exit_code == 0
    assert single_result.exit_code == 0
    assert calls == ["all", "single:138907"]


def test_profile_cli_requires_confirmation_then_applies_valid_patch(
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "student_profile.json"
    patch_path = tmp_path / "profile-patch.json"
    write_model(profile_path, StudentProfile())
    write_json(patch_path, {"identity": {"preferred_name": "Jerry"}})

    rejected = CliRunner().invoke(
        app,
        ["profile", "apply", str(patch_path), "--profile", str(profile_path)],
    )
    applied = CliRunner().invoke(
        app,
        [
            "profile",
            "apply",
            str(patch_path),
            "--profile",
            str(profile_path),
            "--confirmed",
        ],
    )
    profile = StudentProfile.model_validate_json(profile_path.read_text())

    assert rejected.exit_code != 0
    assert applied.exit_code == 0
    assert profile.identity.preferred_name == "Jerry"
    assert profile.provenance.confirmed_by_user is True


def test_global_resources_override_reaches_agent_subcommands(tmp_path: Path) -> None:
    write_model(tmp_path / "student_profile.json", StudentProfile())

    result = CliRunner().invoke(
        app,
        ["--resources", str(tmp_path), "profile", "validate"],
    )

    assert result.exit_code == 0
    assert "Profile valid" in result.stdout


def test_confirmed_profile_mutation_replans_canonical_resources(tmp_path: Path) -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    archive = build_course_archive(
        state,
        course_title="Demo Course",
        raw_state_path="courses/138907/raw/course-state.json",
    )
    write_model(tmp_path / "student_profile.json", StudentProfile())
    write_model(tmp_path / "courses/138907/course.json", archive)
    patch = tmp_path / "patch.json"
    write_json(patch, {"identity": {"preferred_name": "Jerry"}})
    record_sync_operation(
        tmp_path,
        scope="single",
        discovered_course_count=1,
        course_results=[
            {"course_id": "138907", "course": "Demo Course", "succeeded": True}
        ],
    )

    result = CliRunner().invoke(
        app,
        [
            "--resources",
            str(tmp_path),
            "profile",
            "apply",
            str(patch),
            "--confirmed",
        ],
    )

    assert result.exit_code == 0
    assert "Plan refreshed and validated" in result.stdout
    assert assess_plan_freshness(tmp_path).current is True


def test_shared_sync_flow_always_runs_assessment_parser(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = json.loads((ROOT / "tests/fixtures/course_state.json").read_text())
    settings = Settings(
        base_url="https://moodle.example.edu",
        login_url="https://moodle.example.edu/login/index.php",
        dashboard_url="https://moodle.example.edu/my/",
        selector_config=ROOT / "config/selectors.example.json",
        profile_dir=tmp_path / "profile",
        output_dir=tmp_path / "output",
    )
    calls: list[str] = []
    stages: list[str] = []
    download_events: list[str] = []

    class RecordingProgress:
        @contextmanager
        def stage(self, _task_id, component: str, _detail: str):
            stages.append(component)
            yield

        def download_callback(self, _task_id):
            def update(event, _activity, _completed, _total) -> None:
                download_events.append(event)

            return update

    async def fake_download(*_args, **kwargs) -> None:
        calls.append("download")
        callback = kwargs.get("progress_callback")
        if callback:
            callback("start", _args[1].sections[0].activities[0], 0, 1)

    def fake_pdf_analysis(*_args, **_kwargs) -> None:
        calls.append("pdf_analysis")

    def fake_assessment_parser(index, **_kwargs) -> AssessmentOverview:
        assert index.archive.course.course_id == "138907"
        calls.append("assessment_parser")
        return AssessmentOverview()

    monkeypatch.setattr(
        "moodle_collector.workflow.download_course_files",
        fake_download,
    )
    monkeypatch.setattr(
        "moodle_collector.workflow.analyze_course_pdfs",
        fake_pdf_analysis,
    )
    monkeypatch.setattr(
        "moodle_collector.workflow.build_assessment_overview",
        fake_assessment_parser,
    )

    progress = RecordingProgress()
    archive, changes, output_path = asyncio.run(
        _persist_course(
            object(),
            settings,
            course_id="138907",
            course_title="Demo Course",
            state=state,
            progress=progress,
            progress_task=1,
        )
    )

    assert calls == ["download", "pdf_analysis", "assessment_parser"]
    assert stages == [
        "StateMapper",
        "FileStore",
        "Downloader",
        "PdfAnalyzer",
        "AssessmentParser",
        "ChangeDetector",
        "FileStore",
    ]
    assert download_events == ["start"]
    assert archive.course.course_id == "138907"
    assert changes.initial_sync is True
    assert output_path.exists()
