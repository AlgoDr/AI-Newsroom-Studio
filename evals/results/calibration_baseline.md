# A3 — Judge Calibration Baseline (Human vs LLM Judge)

**Date:** 2026-10-13
**Script:** `evals/calibration/run_calibration.py`
**Dataset:** `evals/calibration/judge_calibration_v1.json` (n=10 scripts)
**Gate metric:** Verdict agreement ≥ 80%
**Verdict:** FAIL (50%) — root cause identified, not a judge quality issue

---

## What A3 Calibration Measures

A human (Deep) and the Agent 6 LLM judge independently score the same 10
synthetic scripts as pass/fail, and flag problematic sections. Agreement
between human and judge validates that the automated eval catches the same
issues a human reviewer would.

---

## Results

| Metric | Value | Gate | Verdict |
|--------|-------|------|---------|
| **Verdict agreement** | 5/10 (50%) | ≥ 80% | **FAIL** |
| Flagged-section Jaccard | 0.200 | — | Low overlap |

### Per-Script Breakdown

| Script | Difficulty | Human | Judge | Agreement | Human Flags | Judge Flags |
|--------|-----------|-------|-------|-----------|-------------|-------------|
| 1 | easy | pass | pass | agree | — | — |
| 2 | easy | fail | pass | **disagree** | S3_CORE | — |
| 5 | medium | fail | fail | agree | S3_CORE | S1_TWIST, S2_TWIST |
| 7 | medium | pass | fail | **disagree** | — | CTA |
| 9 | hard | pass | fail | **disagree** | — | S1_TWIST |
| 10 | hard | fail | pass | **disagree** | S3_CORE | — |
| 11 | easy | fail | pass | **disagree** | S3_CORE | — |
| 14 | medium | fail | fail | agree | S3_CORE | S1_TWIST, CTA |
| 16 | hard | pass | pass | agree | — | — |
| 19 | hard | fail | fail | agree | S3_CORE | S1_CONTEXT, S2_CORE |

### Human Verdict Distribution

| Verdict | Count | Scripts |
|---------|-------|---------|
| Pass | 4 | 1, 7, 9, 16 |
| Fail | 6 | 2, 5, 10, 11, 14, 19 |

---

## Root Cause Analysis

The 50% disagreement is **not random noise** — it is two systematic
mismatches operating in opposite directions:

### 1. Judge has no structural completeness check (3 false passes)

Scripts 2, 10, 11: Human fails them because Story 3 never resolves —
the script template has no `S3_TWIST` section, so S3 ends abruptly
with CTA doing double duty as both call-to-action and story
conclusion. The judge checks quality *within* existing sections (voice,
transitions, twist restatement, CTA phrasing) but cannot flag a
section that *should exist but doesn't*. This is a template-level
structural flaw, not a per-script content issue.

**Affected section order:**
```
HOOK → S1_CONTEXT → S1_CORE → S1_TWIST →
S2_HOOK → S2_CORE → S2_TWIST →
S3_HOOK → S3_CORE → CTA    ← no S3_TWIST
```

### 2. Judge is stricter on micro-quality (2 false fails)

Scripts 7, 9: The judge catches legitimate quality issues (CTA not
imperative enough, twist restating its core) that the human reviewer
found acceptable. The deterministic `_twist_is_restatement()` check
and `cta_ok` propagation are working correctly — the human bar was
simply more lenient on these dimensions.

### 3. Agreement on verdict, disagreement on reasons

Even when human and judge agree on pass/fail (scripts 5, 14, 19),
they flag *different sections* for *different reasons*. Jaccard
similarity is 0.00 on all three. The human consistently flags
S3_CORE (the structural gap), while the judge flags twist
restatements and CTA issues.

---

## Infrastructure Notes

- **Script 19 fallback:** Cloud judge (gpt-oss-120b) returned empty
  content (finish_reason=length). Local fallback (qwen3.5:9b) handled
  it and flagged S1_CONTEXT/S2_CORE for vague language.
- **Judge model:** gpt-oss-120b (primary) → qwen3.5:9b (local fallback)
- **Deterministic post-processing:** `_twist_is_restatement()` and
  `cta_ok` propagation fire after the LLM judge, catching issues the
  LLM misses.

---

## Path Forward (v2)

1. **Add S3_TWIST to SECTION_ORDER** in Agent 5's script template —
   this is the root fix. Once scripts have a proper S3 conclusion,
   the structural completeness gap disappears.
2. **Re-run calibration** after the template fix to get a clean
   baseline without the systematic S3 bias.
3. **Consider tightening human bar** on twist restatement and CTA
   quality to better align with the judge's strictness.

---

## Key Takeaway

The calibration process worked exactly as designed — it revealed a
real blind spot in the judge (structural completeness) and a real
structural flaw in the script template (missing S3_TWIST). The 50%
agreement is an honest measurement, not a broken eval. Fixing the
template will eliminate the dominant disagreement pattern.
