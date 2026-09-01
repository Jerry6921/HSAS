from io import StringIO

from rich.console import Console

from hsas.infrastructure.moodle.display_progress import SyncProgress


def test_sync_progress_renders_stage_and_completion() -> None:
    output = StringIO()
    console = Console(file=output, color_system=None, force_terminal=False, width=120)

    with SyncProgress(console=console) as progress:
        task = progress.add_course("138907", "Demo Course", stages=1)
        with progress.stage(task, "AssessmentParser", "Structuring assessments"):
            pass
        progress.finish_course(task, "Demo Course")

    rendered = output.getvalue()
    assert "138907 complete" in rendered
    assert "Demo Course" in rendered
