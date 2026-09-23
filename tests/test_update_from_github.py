from pathlib import Path
import subprocess

import pytest

from hsas.infrastructure.update_from_github import (
    ApplicationUpdateError,
    GitHubUpdateService,
)


OFFICIAL_ORIGIN = "https://github.com/Jerry6921/HSAS.git\n"
TARGET_COMMIT = "1" * 40


def _completed(args: list[str], output: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args, returncode, stdout=output)


def test_update_status_reports_available_for_safe_checkout(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    def runner(args: list[str], _cwd: Path, _timeout: int):
        if args == ["git", "remote", "get-url", "origin"]:
            return _completed(args, OFFICIAL_ORIGIN)
        if args[:2] == ["git", "status"]:
            return _completed(args)
        if args[:2] == ["git", "ls-remote"]:
            return _completed(args, f"{TARGET_COMMIT}\trefs/heads/main\n")
        raise AssertionError(args)

    service = GitHubUpdateService(
        tmp_path,
        current_version="2.7.0",
        fetch_text=lambda _url: '__version__ = "2.8.0"',
        run_command=runner,
        system_name="Linux",
    )

    status = service.status()

    assert status["status"] == "available"
    assert status["latest_version"] == "2.8.0"
    assert status["target_commit"] == TARGET_COMMIT
    assert status["can_apply"] is True


def test_update_status_does_not_apply_over_local_changes(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    def runner(args: list[str], _cwd: Path, _timeout: int):
        if args == ["git", "remote", "get-url", "origin"]:
            return _completed(args, OFFICIAL_ORIGIN)
        if args[:2] == ["git", "status"]:
            return _completed(args, " M README.md\n")
        raise AssertionError(args)

    service = GitHubUpdateService(
        tmp_path,
        current_version="2.7.0",
        fetch_text=lambda _url: '__version__ = "2.8.0"',
        run_command=runner,
        system_name="Linux",
    )

    status = service.status()

    assert status["status"] == "available"
    assert status["can_apply"] is False
    assert "未提交修改" in str(status["message"])


def test_update_apply_fast_forwards_clean_official_checkout(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    commands: list[list[str]] = []

    def runner(args: list[str], _cwd: Path, _timeout: int):
        commands.append(args)
        if args == ["git", "remote", "get-url", "origin"]:
            return _completed(args, OFFICIAL_ORIGIN)
        if args[:2] == ["git", "status"]:
            return _completed(args)
        if args[:2] == ["git", "show"]:
            return _completed(args, '__version__ = "2.8.0"\n')
        if args[:2] == ["git", "rev-parse"]:
            return _completed(args, f"{TARGET_COMMIT}\n")
        return _completed(args)

    service = GitHubUpdateService(
        tmp_path,
        current_version="2.7.0",
        fetch_text=lambda _url: '__version__ = "2.8.0"',
        run_command=runner,
        system_name="Linux",
    )

    result = service.apply(confirmed=True, target_commit=TARGET_COMMIT)

    assert result["status"] == "updated"
    assert result["current_version"] == "2.8.0"
    assert result["restart_required"] is True
    assert ["git", "fetch", "origin", "main", "--quiet"] in commands
    assert ["git", "merge", "--ff-only", TARGET_COMMIT] in commands


def test_update_apply_requires_confirmation(tmp_path: Path) -> None:
    service = GitHubUpdateService(tmp_path, current_version="2.7.0")

    with pytest.raises(ApplicationUpdateError, match="确认"):
        service.apply(confirmed=False, target_commit=TARGET_COMMIT)


def test_update_apply_rejects_changed_remote_commit(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    def runner(args: list[str], _cwd: Path, _timeout: int):
        if args == ["git", "remote", "get-url", "origin"]:
            return _completed(args, OFFICIAL_ORIGIN)
        if args[:2] == ["git", "status"]:
            return _completed(args)
        if args[:2] == ["git", "rev-parse"]:
            return _completed(args, f"{'2' * 40}\n")
        return _completed(args)

    service = GitHubUpdateService(
        tmp_path,
        current_version="2.7.0",
        run_command=runner,
        system_name="Linux",
    )

    with pytest.raises(ApplicationUpdateError, match="已变化"):
        service.apply(confirmed=True, target_commit=TARGET_COMMIT)


def test_update_apply_rejects_dependency_changes_before_merge(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    commands: list[list[str]] = []

    def runner(args: list[str], _cwd: Path, _timeout: int):
        commands.append(args)
        if args == ["git", "remote", "get-url", "origin"]:
            return _completed(args, OFFICIAL_ORIGIN)
        if args[:2] == ["git", "status"]:
            return _completed(args)
        if args[:2] == ["git", "rev-parse"]:
            return _completed(args, f"{TARGET_COMMIT}\n")
        if args[:2] == ["git", "show"]:
            return _completed(args, '__version__ = "2.8.0"\n')
        if args[:2] == ["git", "diff"]:
            return _completed(args, "requirements.lock\n")
        return _completed(args)

    service = GitHubUpdateService(
        tmp_path,
        current_version="2.7.0",
        run_command=runner,
        system_name="Linux",
    )

    with pytest.raises(ApplicationUpdateError, match="依赖变更"):
        service.apply(confirmed=True, target_commit=TARGET_COMMIT)
    assert ["git", "merge", "--ff-only", TARGET_COMMIT] not in commands
