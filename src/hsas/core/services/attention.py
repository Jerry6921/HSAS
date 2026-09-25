"""CORE adapter for deterministic attention projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from hsas.application.attention import build_attention_snapshot


@dataclass(slots=True)
class AttentionService:
    snapshot_provider: Callable[[], dict[str, Any]]
    clock: Callable[[], datetime]

    def snapshot(self, horizon_days: int = 14) -> dict[str, Any]:
        return build_attention_snapshot(
            self.snapshot_provider(),
            now=self.clock(),
            horizon_days=horizon_days,
        )
