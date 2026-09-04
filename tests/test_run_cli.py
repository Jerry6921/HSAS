from pathlib import Path

from typer.testing import CliRunner

from hsas.interfaces.run_cli import app


def test_cli_exposes_only_information_workflow_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    command_names = {
        command.name or command.callback.__name__.replace("_", "-")
        for command in app.registered_commands
    }
    group_names = {group.name for group in app.registered_groups}
    assert result.exit_code == 0
    assert command_names == {"list-status", "login", "query", "sync-courses", "ui"}
    assert group_names == {"changes", "information", "materials"}


def test_sync_command_dispatches_single_or_all(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    class Result:
        course_title = "Demo"
        change_count = 0
        output_path = tmp_path / "course.json"
        succeeded_course_ids = ("1",)
        discovered_course_count = 1
        failures = ()
        report_path = tmp_path / "sync-report.json"

    class Service:
        def sync_all(self):
            calls.append("all")
            return Result()

        def sync_course(self, course: str):
            calls.append(f"single:{course}")
            return Result()

    monkeypatch.setattr("hsas.interfaces.run_cli._course_service", lambda _settings=None: Service())
    all_result = CliRunner().invoke(app, ["--resources", str(tmp_path), "sync-courses"])
    one_result = CliRunner().invoke(
        app, ["--resources", str(tmp_path), "sync-courses", "138907"]
    )
    assert all_result.exit_code == 0
    assert one_result.exit_code == 0
    assert calls == ["all", "single:138907"]


def test_status_initializes_resources_and_reports_empty_state(tmp_path: Path) -> None:
    resources = tmp_path / "resources"
    result = CliRunner().invoke(app, ["--resources", str(resources), "list-status"])
    assert result.exit_code == 0
    assert "Information: unavailable" in result.stdout
    assert "0 course archive(s)" in result.stdout
    assert (resources / "courses").is_dir()
