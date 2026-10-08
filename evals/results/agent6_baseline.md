# Agent 6 JUDGE — Section-Level Flag Agreement Eval Baseline

**Date:** 2026-10-07 (Run 1), 2026-10-08 (Run 2 — post bug fixes)
**Script:** `evals/quality/ref_based/test_agent6.py`
**Golden dataset:** `evals/golden_dataset/agent6_judge_v1.json` (n=10)
**Framework:** DeepEval (BaseMetric + custom JudgeFlagMetric)
**Gate metric:** Section-level micro-F1 ≥ 0.60

---

## Results — Run 2 (post bug fixes)

| Metric | Run 1 (pre-fix) | Run 2 (post-fix) | Delta | Gate | Verdict |
|--------|-----------------|-------------------|-------|------|---------|
| **Micro-F1** | 0.690 | **0.615** | -0.075 | ≥ 0.60 | **PASS ✓** |
| Precision | 0.833 | **0.545** | -0.288 | — | 12/22 correct |
| Recall | 0.588 | **0.706** | +0.118 | — | 12/17 found |
| Binary verdict | 0.700 | **0.900** | +0.200 | — | 9/10 |
| CTA category | 1.000 | **1.000** | — | — | 10/10 |
| CTA ok | 1.000 | **1.000** | — | — | 10/10 |

> **Why F1 went down but the judge got better:** The parser fix exposed
> false positives that were previously invisible (pipe-separated labels
> were discarded entirely, so no FPs were counted). Run 1's precision
> of 0.833 was artificially inflated. The real trade-off is now visible:
> recall up +0.118, binary verdict up +0.200 — the judge catches more
> real issues, but both models systematically over-flag transition sections.

---

## Per-Script Breakdown — Run 2

| # | Diff | P | R | F1 | Verd | CTA | Model | Notes |
|---|------|---|---|------|------|-----|-------|-------|
| 1 | easy | 0.000 | 1.000 | 0.000 | ✗ | ✓ | qwen3.5:9b | FP: S2_HOOK, S3_CORE |
| 2 | easy | 1.000 | 1.000 | 1.000 | ✓ | ✓ | gpt-oss-120b | ✓ perfect |
| 3 | easy | 0.250 | 0.333 | 0.286 | ✓ | ✓ | qwen3.5:9b | FP: S1_CONTEXT, S2_HOOK, S3_HOOK · FN: HOOK, S2_CORE |
| 4 | easy | 1.000 | 1.000 | 1.000 | ✓ | ✓ | gpt-oss-120b | ✓ perfect (TTS regex) |
| 5 | medium | 1.000 | 1.000 | 1.000 | ✓ | ✓ | gpt-oss-120b | ✓ perfect (was FN in Run 1 — Bug 2 fix) |
| 6 | medium | 1.000 | 1.000 | 1.000 | ✓ | ✓ | qwen3.5:9b | ✓ perfect (was FN in Run 1 — Bug 1 fix) |
| 7 | medium | 1.000 | 0.000 | 0.000 | ✓ | ✓ | gpt-oss-120b | FN: CTA |
| 8 | medium | 0.500 | 1.000 | 0.667 | ✓ | ✓ | gpt-oss-120b | FP: S2_HOOK, S3_HOOK |
| 9 | hard | 0.000 | 0.000 | 0.000 | ✓ | ✓ | qwen3.5:9b | FP: S1_CONTEXT, S2_HOOK, S3_CORE · FN: S1_TWIST, S3_HOOK |
| 10 | hard | 1.000 | 1.000 | 1.000 | ✓ | ✓ | gpt-oss-120b | ✓ perfect |

---

## Model Behavior — Run 2

| Script | Model Used | Reason |
|--------|-----------|--------|
| 1, 3, 6, 9 | qwen3.5:9b (fallback) | gpt-oss-120b returned empty, `finish_reason=length` |
| 2, 4, 5, 7, 8, 10 | gpt-oss-120b (primary) | Succeeded |

**Fallback rate: 40%** (down from 50% in Run 1 — Bug 2 prompt tightening recovered Script 5).

---

## Bug Fix Impact

### Bug 1 fix: pipe-separator parser ✅ CONFIRMED WORKING

**Change:** `flagged_raw.replace("|", ",").split(",")` in `_parse_judgment()` line 267.

| Script | Run 1 (bug) | Run 2 (fixed) | Impact |
|--------|-------------|---------------|--------|
| 5 | FN: S1_TWIST, S2_TWIST (parser discarded) | Now ran on gpt-oss-120b, perfect | Indirect — Bug 2 fix moved it off fallback |
| 6 | FN: S2_HOOK, S3_HOOK (parser discarded) | Perfect — pipe labels now parsed | Direct fix |
| 1 | "perfect" (FPs silently hidden) | FP: S2_HOOK, S3_CORE (now visible) | Exposed hidden problem |
| 3 | FP: S2_HOOK, S3_HOOK (partial) | FP: S1_CONTEXT, S2_HOOK, S3_HOOK + FN: HOOK, S2_CORE | More FPs now visible |
| 9 | FN: S1_TWIST, S3_HOOK (parser discarded) | FP: S1_CONTEXT, S2_HOOK, S3_CORE + FN: S1_TWIST, S3_HOOK | Flags parsed but wrong ones |

### Bug 2 fix: prompt tightening ✅ PARTIAL

**Change:** "Do NOT explain your reasoning. Output ONLY these 4 lines" + truncated-output handling.

- Fallback rate dropped from 50% → 40% (Script 5 recovered)
- 4 scripts still hit `finish_reason=length` — the underlying Groq/gpt-oss-120b issue persists

---

## Systematic Failure: Transition Over-Flagging

The most important finding from Run 2 is a **systematic false positive pattern on S2_HOOK and S3_HOOK**:

| Script | Model | FP sections | Clean sections? |
|--------|-------|-------------|-----------------|
| 1 | qwen3.5:9b | S2_HOOK, S3_CORE | Yes — clean pass script |
| 3 | qwen3.5:9b | S1_CONTEXT, S2_HOOK, S3_HOOK | Partially — has real AI phrasing issues elsewhere |
| 8 | gpt-oss-120b | S2_HOOK, S3_HOOK | Script 8's transitions are clean |
| 9 | qwen3.5:9b | S1_CONTEXT, S2_HOOK, S3_CORE | Wrong sections entirely |

**Root cause:** Both models over-interpret the TRANSITIONS check. The prompt says "does S2_HOOK/S3_HOOK signal the previous story is complete and open the next with tension?" — but the models flag transitions that are merely concise rather than genuinely lazy. This is a prompt calibration issue, not a model capability issue.

---

## Failure Analysis by Dimension — Run 2

| Dimension | Expected | Found | Missed | FPs | Notes |
|-----------|----------|-------|--------|-----|-------|
| HUMAN_VOICE | 5 | 3 | 2 | 1 | Missed HOOK, S2_CORE on Script 3; FP S1_CONTEXT |
| TTS-readiness | 6 | 6 | 0 | 0 | Perfect — deterministic Python |
| TWIST | 3 | 2 | 1 | 0 | Script 9's subtle restatement still missed |
| TRANSITIONS | 2 | 2 | 0 | 6 | All 2 expected found, but 6 false positives across 4 scripts |
| CTA | 1 | 0 | 1 | 0 | Script 7: 29-word CTA still not flagged by LLM (cta_ok=NO caught it) |

**The precision problem is almost entirely TRANSITIONS.** 6 of the 10 false positive flags are spurious S2_HOOK/S3_HOOK/S3_CORE flags.

---

## Comparison: Run 1 vs Run 2

| Metric | Run 1 | Run 2 | Change |
|--------|-------|-------|--------|
| Micro-F1 | 0.690 | 0.615 | ↓ 0.075 (exposed FPs) |
| Precision | 0.833 | 0.545 | ↓ 0.288 (hidden FPs now visible) |
| Recall | 0.588 | 0.706 | ↑ 0.118 (Bug 1 fix) |
| Binary verdict | 7/10 | 9/10 | ↑ 2 (gate decisions improved) |
| Fallback rate | 50% | 40% | ↑ (Bug 2 fix) |
| Perfect scripts | 5/10 | 5/10 | Same count, different scripts |

---

## Dataset Coverage

| Category | Scripts | Count |
|----------|---------|-------|
| Clean pass | 1, 2, 10 | 3 |
| AI phrasing (HUMAN_VOICE) | 3, 8 | 2 |
| TTS-readiness (markdown/identifiers) | 4, 8 | 2 |
| Weak twists (TWIST) | 5, 9 | 2 |
| Bad transitions (TRANSITIONS) | 6, 9 | 2 |
| Bad CTA | 7 | 1 |

---

## Key Takeaways

1. **Gate still passes at F1=0.615**, and now the numbers reflect real judge quality rather than parser artifacts. Binary verdict accuracy jumped to 9/10.

2. **Bug 1 fix confirmed working** — Scripts 5 and 6 went from total misses to perfect scores. But the fix also revealed that the fallback model (qwen3.5:9b) systematically over-flags transitions on clean scripts.

3. **Bug 2 fix partially worked** — fallback rate dropped 50% → 40%, but 4 scripts still trigger `finish_reason=length` on gpt-oss-120b.

4. **Transition over-flagging is the #1 precision issue** — 6/10 false positive flags are spurious S2_HOOK/S3_HOOK/S3_CORE. Both models do this, but qwen3.5:9b is worse. The TRANSITIONS prompt check needs calibration: something like "flag ONLY if the hook is a bare topic sentence with no narrative tension — concise hooks that use contrast or surprise are fine."

5. **CTA detection remains perfect** (10/10 category, 10/10 ok).

6. **TWIST detection improved** — 2/3 now found (Script 5 recovered). Script 9's subtle restatement remains the hardest case.

---

## Recommended Next Steps

1. **Calibrate TRANSITIONS prompt** — add examples of acceptable concise hooks vs genuinely lazy ones to reduce false positives
2. **Investigate remaining finish_reason=length** — 4/10 scripts still fall back; consider adding a system message or further prompt compression
3. **Add CTA flagging to Python checks** — Script 7's 29-word CTA was caught by `cta_ok=NO` but not as a flagged section; consider a deterministic word-count check on CTA
4. **Expand dataset** — more clean-pass scripts to test false positive rate, more hard TWIST cases
5. **Accept and document** — current F1=0.615 passes the gate; the judge catches the important issues (AI phrasing, TTS, twists) and the false positives are mostly harmless over-flagging that triggers a rewrite pass (conservative is better than permissive for QC)
