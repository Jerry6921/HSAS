"""Runtime operations kept behind the stable CORE facade."""

from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from hsas.core.ports import HIQSPortError
from hsas.infrastructure.documents.ocr import run_ocr_queue
from hsas.infrastructure.moodle.page_preview import MoodlePreviewError, preview_moodle_page
from hsas.infrastructure.moodle.settings import Settings
from hsas.infrastructure.moodle.session_store import load_moodle_session_status
from hsas.infrastructure.runtime import hku_portal_profile_dir
from hsas.infrastructure.updates.github import ApplicationUpdateError


class ApplicationLifecycleService:
    def __init__(
        self,
        updater: Any,
        mutation_lock: Lock,
        sync_status: Callable[[], dict[str, Any]],
    ) -> None:
        self._updater = updater
        self._mutation_lock = mutation_lock
        self._sync_status = sync_status

    def status(self) -> dict[str, object]:
        return self._updater.status()

    def apply(self, payload: dict[str, Any]) -> dict[str, object]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("请先确认更新 HIQS。")
        target_commit = payload.get("target_commit")
        if not isinstance(target_commit, str):
            raise HIQSPortError("缺少已确认的更新 commit，请重新检查更新。")
        if self._sync_status().get("state") == "running":
            raise HIQSPortError("课程同步正在运行，请完成或取消同步后再更新。")
        with self._mutation_lock:
            try:
                return self._updater.apply(confirmed=True, target_commit=target_commit)
            except ApplicationUpdateError as exc:
                raise HIQSPortError(str(exc)) from exc


class LocalEvidenceOperationService:
    def __init__(
        self,
        resources_dir: Path,
        mutation_lock: Lock,
        sync_status: Callable[[], dict[str, Any]],
        moodle_service_factory: Callable[[Path], Any],
    ) -> None:
        self._resources_dir = resources_dir
        self._mutation_lock = mutation_lock
        self._sync_status = sync_status
        self._moodle_service_factory = moodle_service_factory

    def verify_moodle_session(self) -> dict[str, Any]:
        if not self._mutation_lock.acquire(blocking=False):
            return {
                **load_moodle_session_status(self._resources_dir),
                "verification_deferred": True,
            }
        try:
            result = self._moodle_service_factory(self._resources_dir).check_login_status()
        except Exception as exc:
            return {
                **load_moodle_session_status(self._resources_dir),
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }
        finally:
            self._mutation_lock.release()
        return {
            **load_moodle_session_status(self._resources_dir),
            "error": result.error,
            "verification_deferred": False,
        }

    def process_ocr_queue(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("请先确认开始本地批量 OCR。")
        with self._mutation_lock:
            try:
                return run_ocr_queue(self._resources_dir)
            except (OSError, ValueError) as exc:
                raise HIQSPortError(
                    f"OCR 处理失败：{type(exc).__name__}: {str(exc)[:300]}"
                ) from exc

    def moodle_page_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get("url", "")).strip()
        if not url:
            raise HIQSPortError("缺少 Moodle 链接。")
        if self._sync_status().get("state") == "running":
            raise HIQSPortError("课程同步正在使用浏览器；请在同步完成后再次打开该证据。")
        if not self._mutation_lock.acquire(blocking=False):
            raise HIQSPortError("共享浏览器正在执行另一项操作，请稍后重试。")
        try:
            settings = Settings.load(
                output_dir=self._resources_dir,
                profile_dir=hku_portal_profile_dir(self._resources_dir),
            )
            return asyncio.run(preview_moodle_page(settings, url))
        except MoodlePreviewError as exc:
            raise HIQSPortError(str(exc)) from exc
        except Exception as exc:
            raise HIQSPortError(
                f"无法打开 Moodle 页面：{type(exc).__name__}: {str(exc)[:240]}"
            ) from exc
        finally:
            self._mutation_lock.release()
