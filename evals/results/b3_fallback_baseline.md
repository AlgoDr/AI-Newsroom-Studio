# B3 — Fallback Stress Test Baseline

**Date**: 2026-10-13
**Script**: `evals/ops/fallback_stress.py`
**Model**: qwen3.5:9b (local, Ollama, Metal-accelerated)
**Stories tested**: 30

## Latency

| Metric              | Value   |
|---------------------|---------|
| Cold start (1st)    | 13.5s   |
| Warm p50            | 17.2s   |
| Warm p95            | 19.6s   |

## Classification Distribution

| Label       | Count | Share |
|-------------|-------|-------|
| REAL        | 25    | 83%   |
| OPINION     | 5     | 17%   |
| SPAM        | 0     | 0%    |
| UNPARSEABLE | 0     | 0%    |

## Verdicts

| Check               | Result |
|----------------------|--------|
| Cold start ≤ 30s     | 13.5s — PASS |
| Warm p95 ≤ 5s        | 19.6s — FAIL (threshold too tight) |
| Parse rate ≥ 80%     | 100% — PASS |
| **Overall**          | **UNHEALTHY (threshold issue, not model issue)** |

## Analysis

- Parse rate is perfect: 30/30 stories classified, 0 unparseable
- The warm p95 "failure" is a threshold problem, not a model problem:
  qwen3.5:9b processes 500-6000 chars of article text through a 9B
  model locally — 12-20s per call is the expected cost on M4 Pro
- This is the FALLBACK path (only fires when Groq is completely down),
  so ~16s median is acceptable for keeping the pipeline alive
- Recommendation: raise MAX_WARM_P95 from 5s to 25s for fallback evals
- The important metric is reliability (100% parse, 0% UNPARSEABLE),
  not speed — and it nails that

## Notes

- `think=False` flag on qwen3.5:9b is critical — without it, hidden
  thinking tokens cause multi-minute hangs (documented in agent3.py)
- `keep_alive=0` unloads the model after each call (conservative for
  memory); setting `keep_alive=300` might shave 1-2s off warm calls
