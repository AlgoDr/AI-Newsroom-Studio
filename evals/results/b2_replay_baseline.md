# B2 — Agent 2 Tool-Access Replay Baseline

**Date**: 2026-10-13
**Script**: `evals/ops/tool_access_replay.py`
**URLs tested**: 40

## Tier Distribution

| Tier         | Count | Share | p50(s) | p95(s) |
|--------------|-------|-------|--------|--------|
| trafilatura  | 31    | 78%   | 0.8    | 2.2    |
| jina         | 8     | 20%   | 4.8    | 6.1    |
| tavily       | 0     | 0%    | —      | —      |
| none         | 1     | 2%    | 7.8    | 7.8    |

## Verdicts

| Check                    | Result |
|--------------------------|--------|
| Empty content rate       | 2.5% ≤ 25% — PASS |
| Primary tier (trafilatura) share | 78% ≥ 50% — HEALTHY |
| **Overall**              | **HEALTHY** |

## Thresholds

- MAX_EMPTY_RATE: 25%
- Primary tier warning: < 50%

## Notes

- trafilatura handles ~4 out of 5 URLs — fast (sub-1s median) and free
- jina picks up the rest at ~5s median — mostly sites that block scrapers
- tavily (paid tier) never triggered — good for cost
- 1 unfetchable URL: `neow.in/cWsyMTV3` (short-link/redirect, all 3 tiers failed)
- No Tavily API cost incurred during this test run
