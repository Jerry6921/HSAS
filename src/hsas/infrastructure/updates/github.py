"""Check and safely fast-forward a source installation from the HIQS repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import platform
import re
import ssl
import subprocess
from typing import Callable
from urllib.request import Request, urlopen

from hsas import __version__


GITHUB_REPOSITORY_URL = "https://github.com/Jerry6921/HSAS"
REMOTE_VERSION_URL = (
    "https://raw.githubusercontent.com/Jerry6921/HSAS/main/src/hsas/__init__.py"
)
SUPPORTED_ORIGINS = {
    "https://github.com/Jerry6921/HSAS.git",
    "git@github.com:Jerry6921/HSAS.git",
    "ssh://git@github.com/Jerry6921/HSAS.git",
}
VERSION_PATTERN = re.compile(r"__version__\s*=\s*['\"]([0-9]+(?:\.[0-9]+){2})['\"]")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")


class ApplicationUpdateError(RuntimeError):
    """A safe, user-facing updater failure."""


CommandRunner = Callable[[list[str], Path, int], subprocess.CompletedProcess[str]]
TextFetcher = Callable[[str], str]


def _fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/plain",
            "Cache-Control": "no-cache",
            "User-Agent": f"HIQS/{__version__}",
        },
    )
    system_ca = Path("/etc/ssl/cert.pem")
    context = (
        ssl.create_default_context(cafile=str(system_ca))
        if platform.system() == "Darwin" and system_ca.is_file()
        else None
    )
    with urlopen(  # noqa: S310 - fixed HTTPS URL
        request,
        timeout=5,
        context=context,
    ) as response:
        return response.read(64 * 1024).decode("utf-8")


def _run_command(args: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )


def _version_from_source(source: str) -> str:
    match = VERSION_PATTERN.search(source)
    if match is None:
        raise ApplicationUpdateError("GitHub 版本文件格式无法识别。")
    return match.group(1)


def _version_key(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ApplicationUpdateError(f"无法比较版本号：{value}")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


@dataclass(slots=True)
class GitHubUpdateService:
    project_root: Path
    current_version: str = __version__
    fetch_text: TextFetcher = _fetch_text
    run_command: CommandRunner = _run_command
    system_name: str = platform.system()

    def status(self) -> dict[str, object]:
        checked_at = datetime.now(UTC).isoformat()
        try:
            latest_version = _version_from_source(self.fetch_text(REMOTE_VERSION_URL))
            checkout = self._checkout_state()
            target_commit = self._remote_main_commit() if checkout["can_apply"] else None
            comparison = _version_key(latest_version) > _version_key(self.current_version)
            if comparison:
                status = "available"
                message = f"发现 HIQS {latest_version}。"
                if not checkout["can_apply"]:
                    message += f" {checkout['reason']}"
            elif _version_key(latest_version) == _version_key(self.current_version):
                status = "current"
                message = "已是最新版本。"
            else:
                status = "ahead"
                message = "本机版本高于 GitHub 当前版本。"
            return {
                "status": status,
                "current_version": self.current_version,
                "latest_version": latest_version,
                "target_commit": target_commit,
                "update_available": comparison,
                "can_apply": bool(comparison and checkout["can_apply"]),
                "message": message,
                "checked_at": checked_at,
                "repository_url": GITHUB_REPOSITORY_URL,
            }
        except Exception as exc:
            return {
                "status": "error",
                "current_version": self.current_version,
                "latest_version": None,
                "target_commit": None,
                "update_available": False,
                "can_apply": False,
                "message": f"暂时无法检查更新：{type(exc).__name__}",
                "checked_at": checked_at,
                "repository_url": GITHUB_REPOSITORY_URL,
            }

    def apply(self, *, confirmed: bool, target_commit: str) -> dict[str, object]:
        if not confirmed:
            raise ApplicationUpdateError("请先确认更新 HIQS。")
        if COMMIT_PATTERN.fullmatch(target_commit) is None:
            raise ApplicationUpdateError("更新目标 commit 无效，请重新检查更新。")
        checkout = self._checkout_state()
        if not checkout["can_apply"]:
            raise ApplicationUpdateError(str(checkout["reason"]))

        self._command(["git", "fetch", "origin", "main", "--quiet"], timeout=120)
        fetched_commit = self._command(
            ["git", "rev-parse", "origin/main^{commit}"], timeout=30
        ).stdout.strip()
        if fetched_commit != target_commit:
            raise ApplicationUpdateError("GitHub main 已变化，请重新检查并确认新的 commit。")
        remote_source = self._command(
            ["git", "show", f"{target_commit}:src/hsas/__init__.py"], timeout=30
        ).stdout
        latest_version = _version_from_source(remote_source)
        if _version_key(latest_version) <= _version_key(self.current_version):
            return {
                "status": "current",
                "previous_version": self.current_version,
                "current_version": self.current_version,
                "restart_required": False,
                "message": "已是最新版本。",
            }

        ancestor = self.run_command(
            ["git", "merge-base", "--is-ancestor", "HEAD", target_commit],
            self.project_root,
            30,
        )
        if ancestor.returncode != 0:
            raise ApplicationUpdateError("本机分支与 GitHub main 已分叉，请交给 Agent 检查。")

        dependency_changes = self._command(
            [
                "git",
                "diff",
                "--name-only",
                f"HEAD..{target_commit}",
                "--",
                "requirements.lock",
                "pyproject.toml",
            ],
            timeout=30,
        ).stdout.splitlines()
        if dependency_changes:
            raise ApplicationUpdateError(
                "此版本包含依赖变更，已停止原地更新；请交给 Agent 在独立步骤中升级。"
            )
        self._command(["git", "merge", "--ff-only", target_commit], timeout=120)

        if self.system_name == "Darwin":
            builder = self.project_root / "scripts" / "build_macos_app.sh"
            if builder.is_file():
                try:
                    self._command([str(builder)], timeout=180)
                except ApplicationUpdateError as exc:
                    raise ApplicationUpdateError(
                        f"源码已更新至 {latest_version}，但 HIQS.app 重建失败：{exc}"
                    ) from exc

        return {
            "status": "updated",
            "previous_version": self.current_version,
            "current_version": latest_version,
            "target_commit": target_commit,
            "restart_required": True,
            "message": f"已更新至 HIQS {latest_version}，请退出并重新打开应用。",
        }

    def _checkout_state(self) -> dict[str, object]:
        if not (self.project_root / ".git").exists():
            return {
                "can_apply": False,
                "reason": "当前安装不是 Git 源码目录，请由 Agent 更新。",
            }
        try:
            origin = self._command(["git", "remote", "get-url", "origin"], timeout=15)
            if origin.stdout.strip() not in SUPPORTED_ORIGINS:
                return {
                    "can_apply": False,
                    "reason": "origin 不是官方 HIQS 仓库，请由 Agent 检查。",
                }
            dirty = self._command(
                ["git", "status", "--porcelain", "--untracked-files=normal"], timeout=30
            ).stdout.strip()
            if dirty:
                return {
                    "can_apply": False,
                    "reason": "工作树存在未提交修改，请先交给 Agent 整理。",
                }
        except ApplicationUpdateError as exc:
            return {"can_apply": False, "reason": str(exc)}
        return {"can_apply": True, "reason": ""}

    def _remote_main_commit(self) -> str:
        result = self._command(
            ["git", "ls-remote", "--exit-code", "origin", "refs/heads/main"],
            timeout=30,
        )
        commit = result.stdout.strip().split(maxsplit=1)[0]
        if COMMIT_PATTERN.fullmatch(commit) is None:
            raise ApplicationUpdateError("无法确认 GitHub main commit。")
        return commit

    def _command(self, args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        try:
            result = self.run_command(args, self.project_root, timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ApplicationUpdateError(f"更新命令无法完成：{type(exc).__name__}") from exc
        if result.returncode != 0:
            detail = (result.stdout or "").strip().splitlines()
            suffix = detail[-1][:200] if detail else f"exit {result.returncode}"
            raise ApplicationUpdateError(f"更新命令失败：{suffix}")
        return result
