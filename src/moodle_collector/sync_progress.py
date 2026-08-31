from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .transformation.common.course_schema import CourseActivity, CourseSummary


class SyncProgress:
    """CLI progress UI for Moodle acquisition and transformation stages."""

    def __init__(self, *, console: Console | None = None) -> None:
        self.console = console or Console()
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("{task.fields[detail]}"),
            TimeElapsedColumn(),
            console=self.console,
        )

    def __enter__(self) -> "SyncProgress":
        self._progress.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._progress.stop()

    def add_course(self, course_id: str, title: str, *, stages: int) -> TaskID:
        return self._progress.add_task(
            f"[bold]{course_id}[/]",
            total=stages,
            detail=title,
            course_id=course_id,
        )

    def add_operation(self, component: str, detail: str) -> TaskID:
        return self._progress.add_task(
            f"[cyan]{component}[/]",
            total=None,
            detail=detail,
        )

    def add_batch(self, total: int) -> TaskID:
        return self._progress.add_task(
            "[bold magenta]All courses[/]",
            total=total,
            detail="waiting",
        )

    @contextmanager
    def stage(
        self,
        task_id: TaskID,
        component: str,
        detail: str,
    ) -> Iterator[None]:
        course_id = self._progress.tasks[task_id].fields.get("course_id", "")
        self._progress.update(
            task_id,
            description=f"[bold]{course_id}[/] [cyan]{component}[/]",
            detail=detail,
        )
        try:
            yield
        except Exception as exc:
            self._progress.update(
                task_id,
                description=f"[bold]{course_id}[/] [red]{component} failed[/]",
                detail=f"{type(exc).__name__}: {str(exc)[:120]}",
            )
            raise
        else:
            self._progress.advance(task_id)

    def finish_course(self, task_id: TaskID, detail: str) -> None:
        task = self._progress.tasks[task_id]
        self._progress.update(
            task_id,
            completed=task.total,
            description=f"[bold green]{task.fields.get('course_id', '')} complete[/]",
            detail=detail,
        )

    def finish_operation(self, task_id: TaskID, detail: str) -> None:
        self._progress.update(
            task_id,
            total=1,
            completed=1,
            detail=detail,
        )

    def advance_batch(self, task_id: TaskID, detail: str) -> None:
        self._progress.update(task_id, detail=detail, advance=1)

    def update_discovery(
        self,
        task_id: TaskID,
        index: int,
        total: int,
        course: CourseSummary,
    ) -> None:
        self._progress.update(
            task_id,
            total=total,
            completed=index - 1,
            detail=f"{course.course_id or '?'} {course.title}",
        )

    def download_callback(
        self,
        task_id: TaskID,
    ) -> Callable[[str, CourseActivity, int, int], None]:
        def update(
            event: str,
            activity: CourseActivity,
            completed: int,
            total: int,
        ) -> None:
            status = "downloading" if event == "start" else activity.download_status
            self._progress.update(
                task_id,
                detail=f"{completed}/{total} {status}: {activity.name}",
            )

        return update

    def print(self, message: str) -> None:
        self._progress.console.print(message)
