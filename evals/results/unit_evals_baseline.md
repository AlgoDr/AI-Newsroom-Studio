# Unit Evals Baseline

**Date:** 2026-10-13
**Script:** `evals/run_all.py` (CI entry point)
**Tests:** `evals/unit_evals.py` (11 deterministic evals)
**Gate:** All non-skipped tests pass
**Verdict:** 8/9 passed (2 skipped) — 1 known data issue

---

## What Unit Evals Cover

Deterministic checks that verify pipeline output structure, agent
logic, and data integrity. No LLM calls — pure Python assertions
against golden checkpoint data and agent functions.

---

## Results

| # | Eval | Agent | Status | Detail |
|---|------|-------|--------|--------|
| 1 | eval_checkpoint_integrity | — | PASS | 8 stories, script(131w), shots/seo/video present |
| 2 | eval_stories_cache | — | PASS | 178 stories, 161 with content+background |
| 3 | eval_selected_stories_have_editorial | A4 | PASS | 3 selected stories with editorial justification |
| 4 | eval_agent1_velocity_ranking | A1 | PASS | Velocity formula ranks correctly |
| 5 | eval_agent2_looks_like_real_content | A2 | SKIP | Missing trafilatura dependency |
| 6 | eval_agent2_strip_citation_artifacts | A2 | SKIP | Missing trafilatura dependency |
| 7 | eval_agent6_humanize_dates | A6 | PASS | All 12 time buckets correct |
| 8 | eval_agent6_qc_script_compliance | A6 | **FAIL** | word_count=131, below 150 minimum |
| 9 | eval_agent7_shot_list_integrity | A7 | PASS | 10 shots, shares sum to 1.00 |
| 10 | eval_agent9_tags_fallback | A9 | PASS | Fallback tags generated correctly |
| 11 | eval_seo_completeness | A9 | PASS | SEO title, description, tags present |

---

## Failure Analysis

### eval_agent6_qc_script_compliance — KNOWN DATA ISSUE

The golden checkpoint (`till-agent9.json`) contains a script with
word_count=131, below the 150-word minimum enforced by Agent 6 QC.
The eval is correct — the pipeline approved a too-short script at
some point during development.

**Root cause:** The checkpoint was saved from a pipeline run where
the script was approved despite being under the word count minimum.
This is a data provenance issue, not an eval bug.

**Fix:** Re-run the pipeline to produce a checkpoint with a
compliant script (150–225 words), then re-baseline.

### SKIPs (2)

Both Agent 2 evals skip when `trafilatura` is not installed. These
pass when run with the project venv (`../multi-agent-env/bin/python`)
which has trafilatura. The bridge shell uses system Python without it.

---

## Infrastructure

- **Entry point:** `python evals/run_all.py` (unit only) or
  `python evals/run_all.py --content` (unit + content evals)
- **SKIP handling:** Evals that can't import agent dependencies
  return `(False, "SKIPPED: ...")` and are excluded from the
  pass/fail count. The harness distinguishes real failures from
  environment-dependent skips.
- **Data sources:** `experiments/data/checkpoints/till-agent9.json`
  (golden checkpoint), `experiments/data/stories_cache.json`
  (178 cached stories)
- **Config:** `evals/config.py` holds shared constants
  (TARGET_MIN_WORDS=150, TARGET_MAX_WORDS=225, SECTION_ORDER, etc.)
- **Dataset loader:** `evals/dataset.py` provides
  `load_golden_checkpoint()`, `load_stories_cache()`,
  `golden_script()`, `selected_stories()`
