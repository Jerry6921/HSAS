"""Convert execution history into progress and conservative effort calibration."""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from .execution_schema import ExecutionLog


MIN_TYPE_SAMPLES = 2
MIN_GLOBAL_SAMPLES = 3
MIN_FACTOR = 0.5
MAX_FACTOR = 2.0


class FeedbackIndex:
    def __init__(self, log: ExecutionLog | None = None) -> None:
        self.log = log or ExecutionLog()
        self._records_by_item = defaultdict(list)
        ratios_by_type: dict[str, list[float]] = defaultdict(list)
        all_ratios: list[float] = []
        for record in self.log.records:
            self._records_by_item[record.plan_item_id].append(record)
            progress = record.progress_minutes or 0
            if progress > 0:
                ratio = record.actual_minutes / progress
                if ratio > 0:
                    ratios_by_type[record.item_type].append(ratio)
                    all_ratios.append(ratio)
        self._factors: dict[str, float] = {}
        for item_type, ratios in ratios_by_type.items():
            if len(ratios) >= MIN_TYPE_SAMPLES:
                self._factors[item_type] = _bounded_median(ratios)
        self._global_factor = (
            _bounded_median(all_ratios)
            if len(all_ratios) >= MIN_GLOBAL_SAMPLES
            else 1.0
        )

    @property
    def record_count(self) -> int:
        return len(self.log.records)

    @property
    def total_actual_minutes(self) -> int:
        return sum(record.actual_minutes for record in self.log.records)

    @property
    def calibration_factors(self) -> dict[str, float]:
        return dict(self._factors)

    def factor_for(self, item_type: str) -> float:
        return self._factors.get(item_type, self._global_factor)

    def adjust_estimate(self, item_type: str, minutes: int) -> tuple[int, float]:
        factor = self.factor_for(item_type)
        return max(round(minutes * factor), 1), factor

    def estimate_for_item(
        self,
        item_type: str,
        plan_item_id: str,
        base_minutes: int,
    ) -> tuple[int, float, bool]:
        """Calibrate an estimate and extend it if the budget was used before completion."""
        total, factor = self.adjust_estimate(item_type, base_minutes)
        progress = self.progress_minutes(plan_item_id)
        extended = progress > 0 and progress >= total and not self.item_completed(plan_item_id)
        if extended:
            total = progress + max(round(base_minutes * 0.25), 15)
        return total, factor, extended

    def progress_minutes(self, plan_item_id: str) -> int:
        return sum(
            record.progress_minutes or 0
            for record in self._records_by_item.get(plan_item_id, [])
        )

    def actual_minutes(self, plan_item_id: str) -> int:
        return sum(
            record.actual_minutes
            for record in self._records_by_item.get(plan_item_id, [])
        )

    def item_completed(self, plan_item_id: str) -> bool:
        return any(
            record.item_completed
            for record in self._records_by_item.get(plan_item_id, [])
        )


def _bounded_median(values: list[float]) -> float:
    return round(min(max(float(median(values)), MIN_FACTOR), MAX_FACTOR), 2)
