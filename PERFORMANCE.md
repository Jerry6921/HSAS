# Performance acceptance

HIQS measures the complete local Agent evidence path rather than an isolated SQL
statement. The release benchmark includes archive loading, chunk indexing, FTS5
lookup, evidence shaping, and the time until the first evidence packet is ready.

## Release smoke budget

The deterministic CI corpus contains 200 Moodle activities. On supported CI
hardware the cold index-and-query path must complete within 10 seconds, while
warm-query and first-evidence p95 must remain below 500 ms. These deliberately
wide limits catch major regressions without turning normal runner variance into
release failures.

For a real library, run:

```console
python scripts/benchmark_material_search.py /path/to/resources \
  "calculus tutorial" "assignment deadline" \
  --iterations 30 --max-cold-ms 10000 --max-p95-ms 500
```

The JSON result is suitable for retaining as a release artifact. Compare the
same corpus and machine when investigating smaller changes; cross-machine timing
is not a reliable microbenchmark.
