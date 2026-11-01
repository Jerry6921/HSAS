"""Apple Calendar and Reminders delivery; canonical facts remain unchanged."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
import fcntl
from pathlib import Path
import subprocess
from typing import Any
from collections.abc import Callable
from uuid import UUID, uuid4

from hsas.application.apple_projection import build_apple_projection
from hsas.application.ports.apple import AppleCalendarGateway
from hsas.core.ports import HIQSPortError
from hsas.infrastructure.apple.client import NativeAppleGateway
from hsas.infrastructure.apple.worker import set_worker, worker_status
from hsas.infrastructure.storage import JsonInformationRepository
from hsas.infrastructure.storage.json_store import read_json, write_json


@dataclass(slots=True)
class AppleDeliveryService:
    resources_dir: Path
    gateway: AppleCalendarGateway | None = field(default=None, repr=False)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC), repr=False)

    def _gateway(self):
        return self.gateway or NativeAppleGateway(self.resources_dir)

    def _config(self, *, required=True) -> dict:
        path = self.resources_dir / "apple/config.json"
        if not path.is_file():
            if required:
                raise ValueError("Apple sync is not configured; run hsas apple connect first")
            return {}
        value = read_json(path)
        if not isinstance(value, dict) or not isinstance(value.get("namespace"), str):
            raise ValueError("Invalid saved Apple identity; configuration was retained")
        UUID(value["namespace"])
        if value.get("account_mode") not in {"icloud", "local", "default"}:
            raise ValueError("Invalid saved Apple account mode; configuration was retained")
        return value

    def _state(self) -> dict:
        path = self.resources_dir / "apple/state.json"
        value = read_json(path) if path.is_file() else {}
        if not isinstance(value, dict):
            raise ValueError("Invalid Apple receipt; retained for reconciliation")
        return value

    def _save_config(self, config):
        path = write_json(self.resources_dir / "apple/config.json", config)
        path.chmod(0o600)

    def status(self) -> dict[str, Any]:
        try:
            config, state = self._config(required=False), self._state()
            return {"configured": bool(config), "account_mode": config.get("account_mode"),
                    "last_sync": state.get("report"), "worker": worker_status(self.resources_dir)}
        except (OSError, ValueError, KeyError) as exc:
            raise HIQSPortError(f"Apple status failed: {type(exc).__name__}") from exc

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("Apple account configuration requires confirmation")
        mode = payload.get("account_mode", "icloud")
        if mode not in {"icloud", "local", "default"}:
            raise HIQSPortError("account_mode must be icloud, local or default")
        try:
            with self._lock():
                existing = self._config(required=False)
                if existing and existing["account_mode"] != mode:
                    raise ValueError("Account migration requires reconciliation; existing Apple configuration was retained")
                config = existing or {"namespace": str(uuid4()), "account_mode": mode}
                self._save_config(config)  # Identity persists before the first external write.
                return {"configured": True, "account_mode": mode,
                        "authorization": self._gateway().execute({"operation": "authorize"})}
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise HIQSPortError(str(exc)) from exc

    def projection(self) -> dict[str, Any]:
        try:
            config = self._config()
            store = JsonInformationRepository().load(self.resources_dir / "information.json")
            return build_apple_projection(store, config["namespace"], self._state(), now=self.clock())
        except (OSError, ValueError, KeyError) as exc:
            raise HIQSPortError(str(exc)) from exc

    def check(self) -> dict[str, Any]:
        try:
            with self._lock():
                return self._gateway().execute({"operation": "inventory"})
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise HIQSPortError(str(exc)) from exc

    def synchronize(self) -> dict[str, Any]:
        # Hold the process lock while saving both success and failure receipts;
        # a busy caller must not overwrite another worker's in-flight state.
        try:
            with self._lock():
                return self._synchronize_locked()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise HIQSPortError(str(exc)) from exc

    def _synchronize_locked(self):
        try:
            config = self._config()
            plan = self.projection()
            # Persist the query window before any native write. After a timeout,
            # even a changed source can find and reconcile older written rows.
            write_json(self.resources_dir / "apple/state.json", {
                "window_start": plan["window_start"], "window_end": plan["window_end"],
                "report": {"status": "running", "source_updated_at": plan["source_updated_at"]}})
            result = self._gateway().execute({"operation": "sync", "config": config, "plan": plan})
            if result.get("config"):
                saved = result.pop("config")
                if saved.get("namespace") != config["namespace"] or saved.get("account_mode") != config["account_mode"]:
                    raise ValueError("Apple receipt changed the configured account identity")
                self._save_config(saved)
            verification = result.get("verification", {})
            expected = plan["counts"]["events"] + plan["counts"]["reminders"]
            if result.get("status") == "complete" and (
                verification.get("status") != "verified" or verification.get("expected") != expected
                or verification.get("matched") != expected or result.get("errors")
            ):
                result["status"] = "partial"
                result.setdefault("errors", []).append({"reason": "incomplete_native_receipt"})
            report = {**result, "source_updated_at": plan["source_updated_at"],
                      "delivery_policy": plan["delivery_policy"], "as_of": plan["as_of"], "excluded": plan["excluded"],
                      "finished_at": datetime.now(UTC).isoformat(), "cloud_delivery_verified": False}
            # EventKit readback cannot prove another device has received iCloud changes.
            write_json(self.resources_dir / "apple/state.json", {
                "window_start": plan["window_start"], "window_end": plan["window_end"], "report": report})
            return report
        except (OSError, ValueError, subprocess.SubprocessError, HIQSPortError) as exc:
            try:
                previous = self._state()
                write_json(self.resources_dir / "apple/state.json", {**previous, "report": {
                    "status": "failed", "reason": type(exc).__name__, "finished_at": datetime.now(UTC).isoformat()}})
            except (OSError, ValueError):
                pass  # Preserve a corrupted receipt rather than silently dropping its query scope.
            raise

    def worker(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirmed") is not True:
            raise HIQSPortError("Apple background sync configuration requires confirmation")
        try:
            enabled = payload.get("enabled", True)
            if not isinstance(enabled, bool):
                raise ValueError("enabled must be a boolean")
            if enabled:
                self._config()
                report = self._state().get("report", {})
                if report.get("status") != "complete" or report.get("verification", {}).get("status") != "verified":
                    raise ValueError("Complete and verify the first Apple sync before enabling automatic sync")
            return set_worker(self.resources_dir, enabled=enabled, interval=int(payload.get("interval_seconds", 300)))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise HIQSPortError(str(exc)) from exc

    @contextmanager
    def _lock(self):
        directory = self.resources_dir / "apple"
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        with (directory / "sync.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Another Apple synchronization is already running") from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
