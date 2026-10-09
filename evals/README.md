# Evals — AI Newsroom Studio

Quality gate suite for the 10-agent pipeline. Every agent that classifies, judges, or generates text has a frozen golden dataset, a metric, and a threshold it must pass before changes ship.

## How to run

```bash
cd AI-Newsroom-Studio

# Unit evals only (deterministic, no API keys needed)
../multi-agent-env/bin/python evals/run_all.py

# Unit + content evals (needs GROQ_KEY in experiments/.env)
../multi-agent-env/bin/python evals/run_all.py --content

# Single agent eval (e.g. Agent 3)
../multi-agent-env/bin/python -m pytest evals/quality/ref_based/test_agent3.py -v
```

Exit code 0 = all pass. Non-zero = at least one failure.

---

## Phase A — Offline Quality Evals

Each task tests one agent against a human-labelled golden dataset. "Ref-based" means a correct answer exists and scoring is pure Python comparison; "ref-free" means no single correct answer exists, so an LLM judge scores the output on a rubric.

| Task | Agent | What it tests | Type | Metric | Gate | Score | Status |
|------|-------|--------------|------|--------|------|-------|--------|
| A1 | Agent 3 | Credibility labels (REAL/OPINION/SPAM) | ref-based | Macro-F1 | ≥ 0.70 | **0.990** | ✅ PASS |
| A2 | — | GroqJudge adapter for DeepEval | infra | — | — | — | ⚠️ Built, unused |
| A3 | Agent 6 | Judge calibration (human vs LLM agreement) | calibration | Verdict agreement | ≥ 80% | — | ⏳ Not yet run |
| A4 | Agent 4 | Dedup merge accuracy | ref-based | Micro-F1 | ≥ 0.70 | **0.333** | ❌ FAIL |
| A5 | Agent 6 | JUDGE section-flag agreement | ref-based | Micro-F1 | ≥ 0.60 | **0.615** | ✅ PASS |
| A6 | Agent 5 | Script generation quality (7 dimensions) | ref-free | Composite mean | ≥ 0.70 | **0.889** | ✅ PASS |
| A7 | — | Date humanizer unit test | unit | Exact match | all pass | — | ✅ PASS |

---

## File Map

### Scripts (what runs the eval)

| File | Task | What it does |
|------|------|-------------|
| `quality/ref_based/test_agent3.py` | A1 | Calls `llm_credibility_check()` on 30 golden stories, compares predicted label to human label, computes macro-F1 |
| `quality/groq_judge.py` | A2 | `GroqJudge(DeepEvalBaseLLM)` — routes DeepEval's judge calls to Groq instead of OpenAI. Built but not imported by any eval script yet |
| `calibration/run_calibration.py` | A3 | Runs Agent 6 JUDGE on 10 calibration scripts (`--judge`), then computes human–LLM agreement (`--agreement`) |
| `quality/ref_based/test_agent4.py` | A4 | Calls `deduplicate_stories()` on 10 title sets, compares merge groups to human-labelled pairs, computes micro-F1 |
| `quality/ref_based/test_agent6.py` | A5 | Calls `judge_script()` on 10 golden scripts, compares flagged sections to human labels, computes micro-F1 |
| `quality/ref_based/test_agent5.py` | A6 | Calls `write_script()` on 5 test inputs, scores output on 7 dimensions (3 deterministic + 4 LLM-judged), computes composite mean |
| `quality/ref_free/test_agent2.py` | — | Agent 2 background synthesis faithfulness eval (dataset ready, not yet run) |
| `run_all.py` | all | CI entry point — runs unit evals, optionally content evals. Returns exit code for CI |
| `content_evals.py` | all | Wraps quality eval functions + checkpoint-based evals (faithfulness, relevance, cost) into `run_all.py`'s interface |
| `unit_evals.py` | A7+ | Deterministic unit tests (date humanizer, word count, section presence, etc.) |

### Golden Datasets (frozen inputs + human labels)

| File | Task | n | Contents |
|------|------|---|---------|
| `golden_dataset/agent3_credibility_v1.json` | A1 | 30 | Story title + content + human-assigned label (REAL/OPINION/SPAM). Class distribution: 26 REAL / 4 OPINION / 0 SPAM |
| `golden_dataset/agent4_dedup_v1.json` | A4 | 10 sets (80 titles) | Title sets + expected merge pairs. 5 true pairs across 10 sets, 7 zero-pair trap sets |
| `golden_dataset/agent5_script_v1.json` | A6 | 5 | Test inputs (selected stories) for script generation. No "correct" output — scored on rubric |
| `golden_dataset/agent6_judge_v1.json` | A5 | 10 | Scripts with planted issues + human-labelled expected flags |
| `golden_dataset/agent2_context_v1.json` | — | — | Agent 2 background synthesis test inputs (not yet run) |
| `calibration/judge_calibration_v1.json` | A3 | 10 | Calibration scripts for human vs LLM judge comparison (not yet run) |

### Results (baseline run outputs)

| File | Task | Key finding |
|------|------|------------|
| `results/agent3_baseline.md` | A1 | Macro-F1 = 0.990 on both primary (gpt-oss-120b) and fallback (qwen2.5:7b). 1 failure: "Stolen Buttons" art project misclassified as SPAM |
| `results/agent4_baseline.md` | A4 | Micro-F1 = 0.333 — FAILING. Model misses product-family pairs, generates false merges from domain keywords |
| `results/agent5_baseline.md` | A6 | Composite = 0.889 ± 0.046 across 5 runs. CTA markdown contamination and generic hooks are the two fixable issues |
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

## Key Design Decisions

1. **Deterministic tasks never use an LLM** — word count, section presence, CTA exact match, label comparison are all pure Python
2. **Every model swap requires a multi-run reliability test (N≥5)** using real cached data before integration
3. **Ref-based evals (A1, A4, A5) use code-as-judge** — output is discrete (a label, a merge group, a flag list), so comparison is deterministic
4. **Ref-free evals (A6, Agent 2) use LLM-as-judge** — output is free-form text, needs rubric scoring
5. **Macro-F1 for imbalanced classes** (A1: 26 REAL / 4 OPINION) — protects minority class detection
6. **Micro-F1 for pooled decisions** (A4, A5) — each merge/flag decision weighted equally regardless of which set it belongs to
