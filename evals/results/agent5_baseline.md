# Agent 5 — Script Writer Quality Eval Baseline

**Date:** 2026-10-08
**Script:** `evals/quality/ref_based/test_agent5.py`
**Golden dataset:** `evals/golden_dataset/agent5_script_v1.json` (n=5 test input sets)
**Framework:** DeepEval (BaseMetric + custom ScriptQualityMetric)
**Gate metric:** Composite mean ≥ 0.70
**Model:** qwen/qwen3.8-27b via Groq (primary)

---

## Eval Design

Reference-free generative eval — no "correct" script exists, so output quality is scored on a rubric across 7 dimensions:

**3 deterministic (pure Python):**
- `structure` — all expected sections present (10 for 3 stories, 8 for 2, 5 for 1)
- `word_count` — total words in 150–225 range
- `cta_exact` — CTA text is exactly "Follow for daily tech news"

**4 LLM-judged (qwen2.5:7b via Ollama):**
- `hook_specificity` — HOOK names a specific technology/event, not generic
- `twist_quality` — each TWIST adds a genuine "so what" angle
- `faithfulness` — claims traceable to source material
- `story_alignment` — correct stories included, correct count

Composite = mean of all 7 dimension scores across all 5 test cases.

---

## Results — 5 Runs

| Run | Struct | WC | CTA | Hook | Twist | Faith | Align | Composite | Verdict |
|-----|--------|----|-----|------|-------|-------|-------|-----------|---------|
| 1 | 1.000 | 0.800 | 0.400 | 0.710 | 0.870 | 0.900 | 1.000 | **0.811** | PASS |
| 2 | 1.000 | 1.000 | 0.800 | 0.740 | 0.880 | 0.950 | 1.000 | **0.910** | PASS |
| 3 | 1.000 | 1.000 | 1.000 | 0.720 | 0.880 | 0.980 | 1.000 | **0.940** | PASS |
| 4 | 1.000 | 1.000 | 0.800 | 0.740 | 0.880 | 0.950 | 1.000 | **0.910** | PASS |
| 5 | 1.000 | 1.000 | 0.600 | 0.720 | 0.850 | 0.960 | 1.000 | **0.876** | PASS |

**Mean composite: 0.889 ± 0.046**
**All 5 runs PASS (gate ≥ 0.70)**

---

## Per-Test Breakdown (Run 5 — representative)

| ID | Diff | Struct | WC | CTA | Hook | Twist | Faith | Align | Comp |
|----|------|--------|----|-----|------|-------|-------|-------|------|
| t1 | easy | 1.000 | 1.000 | 1.000 | 0.900 | 0.900 | 1.000 | 1.000 | 0.971 |
| t2 | medium | 1.000 | 1.000 | 0.000 | 1.000 | 0.900 | 0.950 | 1.000 | 0.836 |
| t3 | medium | 1.000 | 1.000 | 1.000 | 0.800 | 0.800 | 1.000 | 1.000 | 0.943 |
| t4 | hard | 1.000 | 1.000 | 1.000 | 0.000 | 0.900 | 1.000 | 1.000 | 0.843 |
| t5 | hard | 1.000 | 1.000 | 0.000 | 0.900 | 0.750 | 0.850 | 1.000 | 0.786 |

---

## Consistent Patterns Across All Runs

### Always perfect (5/5 runs)
- **structure: 1.000** — Agent 5 always produces the correct section count
- **alignment: 1.000** — always includes the right stories

### Stable strengths
- **faithfulness: 0.900–0.980** — rarely hallucinates claims
- **twist_quality: 0.850–0.880** — generally adds genuine "so what" angles
- **word_count: 0.800–1.000** — usually hits the 150–225 window (t5 occasionally overshoots on expansion)

### Consistent weaknesses

#### 1. CTA markdown contamination (Agent 5 bug)
**cta_exact: 0.400–1.000 (high variance)**

The model intermittently prepends `**` to the CTA text, producing `'** Follow for daily tech news'` or `'**\nFollow for daily tech news'` instead of the exact expected string. This appears most often on t2 (mixed credibility) and t5 (low credibility) — the harder inputs where the model needs expansion attempts.

**Root cause:** Agent 5's prompt or parsing doesn't strip markdown bold markers from the CTA section. This is an `agent5.py` bug, not an eval issue.

**Impact:** When it hits, cta_exact drops to 0.000 for that test case, pulling the composite down ~0.14 per affected test.

#### 2. t4 hook always generic
**hook_specificity: 0.000 on t4 in all 5 runs**

Dense technical content (Linux kernel CVE, MLX framework, quantum computing) consistently produces a generic hook like "Three stories pushing tech forward" instead of naming a specific technology.

**Root cause:** When all 3 stories are deeply technical and unrelated, the model defaults to a safe umbrella hook rather than picking one story to lead with.

#### 3. t5 occasionally over-expands
In Run 1, t5 hit 267 words (out of range), causing word_count = 0.000. The model's expansion logic sometimes overshoots when the initial generation is very short (119–135 words on low-credibility cautious content).

---

## Test Case Difficulty Profile

| Test | Stories | Difficulty | Purpose | Typical Composite |
|------|---------|------------|---------|-------------------|
| t1 | 3, all high cred | easy | Standard baseline | 0.96–0.97 |
| t2 | 3, mixed cred | medium | Tone variation (confident vs hedged) | 0.81–0.99 (CTA variance) |
| t3 | 2 stories | medium | 8-section format compliance | 0.94–0.96 |
| t4 | 3, dense technical | hard | Simplification + hook specificity | 0.68–0.84 (hook=0 always) |
| t5 | 3, all low cred | hard | Cautious framing + word count | 0.66–0.95 (CTA + WC variance) |

---

## DeepEval Integration Notes

- **copy_metrics() issue (fixed):** DeepEval's `assert_test()` internally calls `copy_metrics()` which creates a new metric instance via `type(metric)(**vars(metric))`. The `__init__()` must accept keyword args matching all instance attributes, or the copy starts fresh and re-runs the entire eval.
- **Runtime:** ~2.5 min per run (5 test inputs × ~20s each for generation + LLM judging)
- **No PytestCollectionWarning:** Dataclass renamed from `TestResult` to `EvalResult`

---

## Improvement Paths (not yet attempted)

1. **Fix CTA contamination in agent5.py** — strip markdown `**` from parsed CTA section before returning. This alone would raise mean composite by ~0.05–0.10.
2. **Improve t4 hook specificity** — add a fallback instruction: "If stories are all technical, lead with the most impactful one by name." Or add a second prompt attempt for hooks that score below 0.5.
3. **Tune expansion logic** — t5's overshoot suggests the expansion prompt should cap more aggressively (e.g., "expand to exactly 160 words" rather than just "expand").
4. **Test fallback model (gemma4:12b-mlx)** — not yet evaluated; needs a dedicated multi-run reliability test per project policy.

---

## Key Takeaway

Agent 5 (qwen/qwen3.8-27b via Groq) is a strong script writer with a stable composite of **0.889 ± 0.046**, comfortably above the 0.70 gate. The two fixable issues — CTA markdown contamination and t4 generic hooks — are both addressable in `agent5.py` without model changes. Structure, alignment, and faithfulness are near-perfect across all runs.
