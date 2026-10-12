# Agent 5 — Script Writer Quality Eval Baseline

**Date:** 2026-10-12 (expanded from 2026-10-08 baseline)
**Script:** `evals/quality/ref_based/test_agent5.py`
**Golden dataset:** `evals/golden_dataset/agent5_script_v1.json` (n=15 test input sets)
**Framework:** DeepEval (BaseMetric + custom ScriptQualityMetric)
**Gate metric:** Composite mean ≥ 0.70
**Judge model:** qwen/qwen3.8-27b via Groq
**Generation model:** llama-3.3-70b-versatile via Groq (Agent 5 primary)

---

## Eval Design

Reference-free generative eval — no "correct" script exists, so output quality is scored on a rubric across 7 dimensions:

**3 deterministic (pure Python):**
- `structure` — all expected sections present (10 for 3 stories, 8 for 2, 5 for 1)
- `word_count` — total words in 150–225 range
- `cta_exact` — CTA text is exactly one of the valid CTAs

**4 LLM-judged (qwen/qwen3.8-27b via Groq):**
- `hook_specificity` — HOOK names a specific technology/event, not generic
- `twist_quality` — each TWIST adds a genuine "so what" angle
- `faithfulness` — claims traceable to source material
- `story_alignment` — correct stories included, correct count

Composite = mean of all 7 dimension scores across all 15 test cases.

---

## Results — Expanded Run (15 test sets)

| ID | Diff | Struct | WC | CTA | Hook | Twist | Faith | Align | Comp |
|----|------|--------|----|-----|------|-------|-------|-------|------|
| t1 | easy | 1.000 | 1.000 | 1.000 | 0.900 | 0.900 | 1.000 | 1.000 | 0.971 |
| t2 | medium | 1.000 | 1.000 | 0.000 | 0.950 | 0.900 | 0.850 | 1.000 | 0.814 |
| t3 | medium | 1.000 | 1.000 | 1.000 | 0.800 | 0.900 | 1.000 | 1.000 | 0.957 |
| t4 | hard | 1.000 | 1.000 | 1.000 | 0.000 | 0.900 | 1.000 | 1.000 | 0.843 |
| t5 | hard | 1.000 | 1.000 | 1.000 | 0.900 | 0.800 | 0.950 | 1.000 | 0.950 |
| t6 | easy | 1.000 | 1.000 | 1.000 | 0.000 | 0.900 | 1.000 | 1.000 | 0.843 |
| t7 | easy | 1.000 | 1.000 | 1.000 | 0.900 | 0.900 | 1.000 | 1.000 | 0.971 |
| t8 | medium | 1.000 | 1.000 | 1.000 | 0.900 | 0.800 | 1.000 | 1.000 | 0.957 |
| t9 | hard | 1.000 | 1.000 | 1.000 | 0.900 | 0.900 | 1.000 | 1.000 | 0.971 |
| t10 | easy | 1.000 | 1.000 | 1.000 | 0.900 | 0.900 | 0.950 | 1.000 | 0.964 |
| t11 | medium | 1.000 | 0.000 | 1.000 | 0.400 | 0.900 | 0.850 | 1.000 | 0.736 |
| t12 | hard | 1.000 | 1.000 | 1.000 | 0.900 | 0.750 | 0.850 | 1.000 | 0.929 |
| t13 | hard | 1.000 | 1.000 | 1.000 | 1.000 | 0.900 | 1.000 | 1.000 | 0.986 |
| t14 | medium | 1.000 | 0.000 | 1.000 | 0.900 | 0.900 | 0.850 | 1.000 | 0.807 |
| t15 | medium | 1.000 | 0.000 | 0.000 | 0.800 | 0.900 | 0.850 | 1.000 | 0.650 |

**Composite: 0.890 (gate ≥ 0.70) — PASS**
**Tests: 15 succeeded, 0 errored**
**Runtime: 542s (~9 min)**

---

## Dimension Averages

| Dimension | Average | Status |
|-----------|---------|--------|
| structure | 1.000 | Perfect |
| word_count | 0.800 | 3 failures (t11, t14, t15) |
| cta_exact | 0.867 | 2 failures (t2, t15) |
| hook_spec | 0.743 | Weakest dimension, 2 zeroes |
| twist_qual | 0.877 | Solid |
| faithfulness | 0.943 | Strong |
| alignment | 1.000 | Perfect |

---

## Comparison: Original Baseline (n=5) vs Expanded (n=15)

| Metric | n=5 baseline (mean of 5 runs) | n=15 expanded | Delta |
|--------|-------------------------------|---------------|-------|
| Composite | 0.889 ± 0.046 | 0.890 | +0.001 |
| structure | 1.000 | 1.000 | — |
| word_count | 0.960 | 0.800 | -0.160 |
| cta_exact | 0.720 | 0.867 | +0.147 |
| hook_spec | 0.726 | 0.743 | +0.017 |
| twist_qual | 0.872 | 0.877 | +0.005 |
| faithfulness | 0.948 | 0.943 | -0.005 |
| alignment | 1.000 | 1.000 | — |

The composite held steady at 0.890 with 3x more test cases — good sign that the original 5 weren't cherry-picked. Word count got worse because the new test sets (t11, t14, t15) exposed the expansion overshoot more.

---

## Systematic Issues (ranked by impact)

### 1. Word count expansion overshoot — 3/15 failures (20%)
**Affected:** t11 (299w), t14 (144w), t15 (269w)

Two failure modes:
- **Overshoot:** Initial gen is short (~136w), expansion blows past 225 to 269-299w (t11, t15)
- **Undershoot stuck:** Initial gen is very short (~112w), expansion only reaches 144w, still under 150 (t14)

Both exit via "accepting as-is (Agent 6 will review)" after 2 attempts.

**Root cause:** The expansion prompt doesn't specify a target word count — it just says "expand." The model either barely adds anything or rewrites the whole thing much longer.

**Fix:** Specify target in expansion prompt: "Expand to approximately 170 words" (midpoint of 150-225). Add a third attempt if still out of range.

### 2. CTA markdown contamination — 2/15 failures (13%)
**Affected:** t2 (`'** Follow for daily tech news'`), t15 (`'**\nFollow for daily tech news'`)

The model prepends bold markdown `**` to the CTA text. This was known from the original baseline and remains unfixed.

**Root cause:** Agent 5's `_parse_script()` doesn't strip markdown formatting from the CTA section.

**Fix:** Add `.lstrip('*').lstrip().strip()` to the CTA parsing in `agent5.py`.

### 3. Hook specificity zeroes — 2/15 failures (13%)
**Affected:** t4 (dense technical, 0.00), t6 (infrastructure, 0.00)

When stories are all deeply technical or infrastructure-focused, the model defaults to a generic umbrella hook instead of naming a specific technology.

**Root cause:** Prompt doesn't force the hook to name a specific story's technology.

**Fix:** Add to prompt: "Your HOOK must name a specific technology, product, or event from Story 1."

### 4. t11 weak hook (0.40) — not a zero but notably low
Security-focused stories (Cloudflare breach + Signal vulnerability) produced a hook that was partially specific but not sharp enough. Likely compounded by the word count blowout on this same test.

---

## Test Case Difficulty Profile (expanded)

| Test | Stories | Difficulty | Purpose | Composite |
|------|---------|------------|---------|-----------|
| t1 | 3, all high cred | easy | Standard baseline | 0.971 |
| t2 | 3, mixed cred | medium | Tone variation | 0.814 |
| t3 | 2 stories | medium | 8-section format | 0.957 |
| t4 | 3, dense technical | hard | Simplification challenge | 0.843 |
| t5 | 3, all low cred | hard | Cautious framing | 0.950 |
| t6 | 3, infrastructure | easy | Straightforward generation | 0.843 |
| t7 | 2, privacy/ethics | easy | 8-section + sensitive topics | 0.971 |
| t8 | 3, one very low cred | medium | Hedge-language stress test | 0.957 |
| t9 | 3, science/research | hard | Jargon simplification | 0.971 |
| t10 | 3, consumer/lifestyle | easy | Tone contrast from technical | 0.964 |
| t11 | 2, security focus | medium | Compact format + sensitive | 0.736 |
| t12 | 3, very short content | hard | Synthesis under minimal input | 0.929 |
| t13 | 3, policy/regulatory | hard | Factual accuracy priority | 0.986 |
| t14 | 3, all medium cred | medium | Balanced hedging | 0.807 |
| t15 | 3, hardware/maker | medium | Obscure topic simplification | 0.650 |

**Best:** t13 (0.986) — policy/regulatory content, perfect hook + faithfulness
**Worst:** t15 (0.650) — double failure (WC + CTA), only test below gate

---

## Improvement Paths (prioritized)

1. **Fix CTA stripping in agent5.py** — strip `**` and whitespace from parsed CTA. Eliminates 2 failures, raises cta_exact from 0.867 to ~0.933. Estimated composite lift: +0.02.

2. **Fix expansion prompt with target word count** — specify "expand to approximately 170 words" and add a 3rd attempt. Eliminates 3 failures, raises word_count from 0.800 to ~0.933. Estimated composite lift: +0.03.

3. **Force specific hook** — add "HOOK must name a specific technology from Story 1" to prompt. Addresses t4 and t6 zeroes. Estimated hook_spec lift from 0.743 to ~0.85.

4. **Combined impact:** All three fixes together would lift composite from 0.890 to ~0.940+.

---

## DeepEval Integration Notes

- ScriptQualityMetric subclasses BaseMetric with copy_metrics() guard pattern
- Judge model: qwen/qwen3.8-27b via Groq (upgraded from qwen2.5:7b via Ollama in original baseline)
- 1-second sleep between judge calls for rate limiting
- Runtime: ~36s per test case (generation + 4 judge calls)
