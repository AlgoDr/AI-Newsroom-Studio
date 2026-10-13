# B1 — Agent 1 Probe Baseline

**Date**: 2026-10-13
**Script**: `evals/ops/ops_probe.py`
**Runs**: 20

## Results

| Metric            | Value  |
|-------------------|--------|
| Runs completed    | 20/20  |
| p50 latency       | 6.0s   |
| p95 latency       | 6.4s   |
| Stories per run    | 8      |
| Empty URL rate    | 0.0%   |
| **Verdict**       | HEALTHY |

## Thresholds

- MAX_P95_LATENCY: 15.0s
- MAX_EMPTY_URL_RATE: 10%
- EXPECTED_STORIES: 8

## Notes

- ~6s latency explained by 9 sequential HTTP requests (1 for IDs + 8 for items)
- Zero empty URLs across all 20 runs — HN API is highly reliable
- B6 optimization candidate: asyncio/aiohttp could cut latency to ~1-2s
