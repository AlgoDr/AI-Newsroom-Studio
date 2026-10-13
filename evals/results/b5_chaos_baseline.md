# B5 — Chaos Checks Baseline

**Date**: 2026-10-13
**Script**: `evals/ops/chaos_checks.py`

## Results

| Test | Scenario | Checks | Result |
|------|----------|--------|--------|
| 1 | Groq 429 → local fallback | No crash, score returned (0.1), fallback fired | ✓ PASS |
| 2 | Exa down → DDG fallback | No crash, neutral returned, Exa failure detected | ✓ PASS |
| 3 | DDG timeout + Exa down → neutral | No crash, safe neutral (verified=False, contradicted=False) | ✓ PASS |

## Verdicts

| Check | Result |
|-------|--------|
| groq_429_no_crash | PASS |
| groq_429_fallback_fired | PASS |
| exa_down_no_crash | PASS |
| exa_down_fallback_fired | PASS |
| both_down_neutral | PASS |
| both_down_no_crash | PASS |
| **Overall** | **6/6 — HEALTHY** |

## What This Proves

- **Groq outage**: Agent 3 falls back to qwen3.5:9b local — returns a usable
  credibility score (0.1 = OPINION), pipeline continues
- **Exa outage**: cross-verification falls back to DDG — safe neutral, no crash
- **Total verification outage** (Exa + DDG both down): returns neutral
  (verified=False, contradicted=False) — never falsely penalizes a story,
  pipeline continues without cross-verification signal
- **No failure mode crashes the pipeline** — every external dependency has a
  safe default
