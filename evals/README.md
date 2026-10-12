# Evals — AI Newsroom Studio

Quality gate suite for the 10-agent pipeline. Every agent that classifies, judges, or generates text has a frozen golden dataset, a metric, and a threshold it must pass before changes ship.

## How to run

```bash
cd /path/to/AI-Newsroom-Studio

# Unit evals only (deterministic, no API keys needed)
python evals/run_all.py

# Unit + content evals (needs GROQ_KEY in experiments/.env)
python evals/run_all.py --content

# Single agent eval via pytest
python -m pytest evals/quality/ref_based/test_agent3.py -v
python -m pytest evals/quality/ref_based/test_agent5.py -v
python -m pytest evals/quality/ref_based/test_agent6.py -v
```

Exit code 0 = all pass. Non-zero = at least one failure.

---

## Phase A — Offline Quality Evals (current status)

Each task tests one agent against a human-labelled golden dataset. "Ref-based" means a correct answer exists and scoring is pure Python comparison; "ref-free" means no single correct answer exists, so an LLM judge scores the output on a rubric.

| Task | Agent | What it tests | Type | Metric | Gate | Score | Status |
|------|-------|--------------|------|--------|------|-------|--------|
| A1 | Agent 3 | Credibility labels (REAL/OPINION/SPAM) | ref-based | Macro-F1 | ≥ 0.70 | **0.990** | PASS |
| A2 | — | GroqJudge adapter for DeepEval | infra | — | — | — | Built, unused |
| A3 | Agent 6 | Judge calibration (human vs LLM agreement) | calibration | Verdict agreement | ≥ 80% | — | Not yet run |
| A4 | Agent 4 | Dedup merge accuracy | ref-based | Micro-F1 | ≥ 0.70 | **0.333** | FAIL |
| A5 | Agent 6 | JUDGE section-flag agreement | ref-based | Micro-F1 | ≥ 0.60 | **0.615** | PASS |
| A6 | Agent 5 | Script generation quality (7 dimensions) | ref-free | Composite mean | ≥ 0.70 | **0.890** | PASS |
| A7 | — | Date humanizer unit test | unit | Exact match | all pass | — | PASS |

---

## Recent Fixes (2026-10-12)

### Agent 5 (`experiments/agents/agent5.py`) — 3 fixes

1. **CTA markdown stripping** — `_parse_script()` now strips bold markdown artifacts (`**`) from CTA text. Eliminated 2/15 eval failures (t2, t15).

2. **Word count expansion prompt** — Expansion prompt now specifies "approximately 170 words" (midpoint of 150–225) instead of just "at least 150." `MAX_ATTEMPTS` bumped from 2 to 3. Addresses 3/15 word count failures (t11, t14, t15).

3. **Hook specificity** — Added "Your HOOK must name a specific technology, product, or event from Story 1" to the generation prompt. Addresses 2/15 hook specificity zeroes (t4, t6).

### Agent 6 (`experiments/agents/agent6.py`) — 2 fixes ported from test wrapper

1. **TWIST restatement detection** — Deterministic post-processing in `_judge_script()`: signal-phrase detection + SequenceMatcher word-overlap (≥0.50) catches restatements the LLM judge misses. Previously only ran in the eval test wrapper (`test_agent6.py`), now in production.

2. **CTA propagation** — When `cta_ok=False`, CTA is now added to `flagged_sections` so the binary verdict and rewrite loop both act on it. Previously the LLM judge detected bad CTAs but the flag never propagated to the rewrite stage.

Both evals re-verified PASS after fixes (Agent 5: 538s, Agent 6: 238s).

---

## Eval Architecture

### Deterministic vs LLM-judged

The pipeline separates concerns strictly:

- **Deterministic scoring** (pure Python): word count range, section presence, CTA exact match, label comparison, date humanization. These never use an LLM — they are reliable, reproducible, and free.
- **LLM-judged scoring** (qwen/qwen3.8-27b via Groq): hook specificity, twist quality, faithfulness, story alignment. These score free-form text on a rubric where no single correct answer exists.

### F1 metric choices

- **Macro-F1** for imbalanced classes (A1: 26 REAL / 4 OPINION / 0 SPAM) — protects minority class detection
- **Micro-F1** for pooled decisions (A4, A5) — each merge/flag decision weighted equally

### Model swap policy

Every model swap requires a multi-run reliability test (N ≥ 5) using real cached data before integration. No model is trusted on a single sample.

---

## File Map

### Scripts (what runs the eval)

| File | Task | What it does |
|------|------|-------------|
| `quality/ref_based/test_agent3.py` | A1 | Calls `llm_credibility_check()` on 30 golden stories, compares predicted label to human label, computes macro-F1 |
| `quality/groq_judge.py` | A2 | `GroqJudge(DeepEvalBaseLLM)` — routes DeepEval's judge calls to Groq instead of OpenAI. Built but not imported by any eval script yet |
| `calibration/run_calibration.py` | A3 | Runs Agent 6 JUDGE on 10 calibration scripts (`--judge`), then computes human–LLM agreement (`--agreement`) |
| `quality/ref_based/test_agent4_v3.py` | A4 | Calls `deduplicate_stories()` on 10 title sets, compares merge groups to human-labelled pairs, computes micro-F1 |
| `quality/ref_based/test_agent6.py` | A5 | Calls `_judge_script()` on 10 golden scripts via patched wrapper (TWIST restatement + CTA propagation), compares flagged sections to human labels, computes micro-F1 |
| `quality/ref_based/test_agent5.py` | A6 | Calls `script_writer_node()` on 15 test inputs, scores output on 7 dimensions (3 deterministic + 4 LLM-judged), computes composite mean |
| `quality/ref_free/test_agent2.py` | — | Agent 2 background synthesis faithfulness eval (dataset ready, not yet run) |
| `run_all.py` | all | CI entry point — runs unit evals, optionally content evals. Returns exit code for CI |
| `content_evals.py` | all | Wraps quality eval functions + checkpoint-based evals into `run_all.py`'s interface |
| `unit_evals.py` | A7+ | Deterministic unit tests (date humanizer, word count, section presence, velocity formula, etc.) |

### Golden Datasets (frozen inputs + human labels)

| File | Task | n | Contents |
|------|------|---|---------|
| `golden_dataset/agent3_credibility_v1.json` | A1 | 30 | Story title + content + human-assigned label (REAL/OPINION/SPAM) |
| `golden_dataset/agent4_dedup_v1.json` | A4 | 10 sets (80 titles) | Title sets + expected merge pairs |
| `golden_dataset/agent5_script_v1.json` | A6 | 15 | Test inputs (selected stories) for script generation. No "correct" output — scored on rubric |
| `golden_dataset/agent6_judge_v2.json` | A5 | 10 | Scripts with planted issues + human-labelled expected flags |
| `golden_dataset/agent2_context_v1.json` | — | — | Agent 2 background synthesis test inputs (not yet run) |
| `calibration/judge_calibration_v1.json` | A3 | 10 | Calibration scripts for human vs LLM judge comparison (not yet run) |

### Results (baseline run outputs)

| File | Task | Key finding |
|------|------|------------|
| `results/agent3_baseline.md` | A1 | Macro-F1 = 0.990. Both primary (gpt-oss-120b) and fallback (qwen2.5:7b) pass. 1 failure: "Stolen Buttons" art project misclassified as SPAM |
| `results/agent4_baseline.md` | A4 | Micro-F1 = 0.333 — FAILING. Model misses product-family pairs, generates false merges from domain keywords |
| `results/agent5_baseline.md` | A6 | Composite = 0.890 (n=15, expanded from n=5). Systematic issues: word count expansion (20%), CTA markdown (13%), hook specificity (13%) |
| `results/agent6_baseline.md` | A5 | Micro-F1 = 0.615 (post bug fixes). Binary verdict 9/10. Transition over-flagging is the #1 precision issue |

### Tooling

| File | Purpose |
|------|---------|
| `golden_dataset/LABELING_GUIDE.md` | Instructions for manually labelling golden datasets |
| `golden_dataset/label_helper.py` | Helper script for labelling workflow |
| `golden_dataset/pull_candidates.py` | Pulls candidate stories from cache for golden set construction |
| `config.py` | Shared config — judge model, thresholds, max tokens |
| `dataset.py` | Data loading helpers for checkpoint-based evals |

---

## Agent 5 Eval Details (A6)

**Composite: 0.890 | Gate: ≥ 0.70 | PASS**

7 scoring dimensions:

| Dimension | Type | Average | Notes |
|-----------|------|---------|-------|
| structure | deterministic | 1.000 | All expected sections present |
| word_count | deterministic | 0.800 | 3 failures (expansion overshoot/undershoot) |
| cta_exact | deterministic | 0.867 | 2 failures (markdown contamination) |
| hook_specificity | LLM-judged | 0.743 | Weakest dimension, 2 zeroes on dense technical inputs |
| twist_quality | LLM-judged | 0.877 | Solid |
| faithfulness | LLM-judged | 0.943 | Strong |
| story_alignment | LLM-judged | 1.000 | Perfect |

Best test: t13 (0.986) — policy/regulatory content, perfect hook + faithfulness.
Worst test: t15 (0.650) — double failure (WC + CTA), only test below gate.

---

## Agent 6 JUDGE Eval Details (A5)

**Micro-F1: 0.615 | Gate: ≥ 0.60 | PASS**

Post-processing fixes (TWIST restatement detection + CTA propagation) lifted F1 from 0.615 to 0.755 in the test wrapper; these are now ported to production `agent6.py`.

Key findings:
- **Transition over-flagging** is the #1 precision issue — 6/10 false positive flags are spurious S2_HOOK/S3_HOOK
- **CTA detection** is perfect (10/10 category, 10/10 ok)
- **Fallback rate**: 40% of scripts fall back to qwen3.5:9b when gpt-oss-120b returns `finish_reason=length`

---

## Known Issues & Next Steps

1. **A4 is FAILING** (F1 = 0.333) — Agent 4 dedup needs a fundamentally different approach
2. **A3 judge calibration** — blocked on manual scoring of 10 scripts (~1 hour)
3. **Transition over-flagging** — prompt calibration needed to reduce false positives on S2_HOOK/S3_HOOK
4. **Agent 2 eval** — dataset ready, test script built, not yet run
5. **`run_all.py --content`** — needs all content evals wired up for CI
