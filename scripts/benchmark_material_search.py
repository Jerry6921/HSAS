"""Measure cold indexing and warm Agent evidence-query latency.

Usage:
    python scripts/benchmark_material_search.py RESOURCES QUERY [QUERY ...]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import time

from hsas.application.material_search import invalidate_material_index, search_materials


def _duration_ms(operation) -> tuple[float, object]:
    started = time.perf_counter()
    result = operation()
    return (time.perf_counter() - started) * 1_000, result


def benchmark(resources: Path, queries: list[str], iterations: int) -> dict[str, object]:
    invalidate_material_index(resources)
    cold_ms, cold_result = _duration_ms(lambda: search_materials(resources, queries[0]))
    samples: list[float] = []
    hit_samples: list[float] = []
    for index in range(iterations):
        query = queries[index % len(queries)]
        elapsed, result = _duration_ms(lambda query=query: search_materials(resources, query))
        samples.append(elapsed)
        if result.hits:
            hit_samples.append(elapsed)
    ordered = sorted(samples)

    def percentile_95(values: list[float]) -> float | None:
        if not values:
            return None
        ordered_values = sorted(values)
        position = max(0, min(len(ordered_values) - 1, round(0.95 * len(ordered_values)) - 1))
        return round(ordered_values[position], 3)

    return {
        "schema_version": "1.0",
        "resources": str(resources.resolve()),
        "iterations": iterations,
        "indexed_document_count": cold_result.indexed_document_count,
        "indexed_chunk_count": cold_result.indexed_chunk_count,
        "cold_index_and_query_ms": round(cold_ms, 3),
        "warm_query_median_ms": round(statistics.median(samples), 3),
        "warm_query_p95_ms": percentile_95(ordered),
        "first_evidence_p95_ms": percentile_95(hit_samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("resources", type=Path)
    parser.add_argument("query", nargs="+")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--max-cold-ms", type=float)
    parser.add_argument("--max-p95-ms", type=float)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    result = benchmark(args.resources, args.query, args.iterations)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    failures = []
    if args.max_cold_ms is not None and result["cold_index_and_query_ms"] > args.max_cold_ms:
        failures.append("cold index/query budget exceeded")
    if args.max_p95_ms is not None and result["warm_query_p95_ms"] > args.max_p95_ms:
        failures.append("warm query p95 budget exceeded")
    if failures:
        raise SystemExit("; ".join(failures))


if __name__ == "__main__":
    main()
