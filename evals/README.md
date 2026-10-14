# Evals — AI Newsroom Studio

Quality gate suite for the 10-agent pipeline. Three layers of testing,
zero LLM calls at the unit level, frozen golden datasets at the quality
level, and human-vs-machine agreement at the calibration level.

**CI entry point:** `python evals/run_all.py` — exit 0 = all pass, exit 1 = failure.

**Current result:** 10/11 passed, 0 skipped, 1 known data issue.

---

## The Three Layers

### Layer 1 — Unit Evals (deterministic, no API, <2 seconds)

Pure Python assertions against frozen checkpoint data. These verify
structural contracts — "is the data shaped right?" — not content quality.
They run on every commit, cost nothing, and catch regressions instantly.

**Entry point:** `python evals/run_all.py`

| # | Eval | Agent | What it checks |
|---|------|-------|----------------|
| 1 | `eval_checkpoint_integrity` | — | Golden checkpoint has 8 stories, a script, shots, SEO, and video fields |
| 2 | `eval_stories_cache` | — | 178 cached stories, 161 with both content and background |
| 3 | `eval_selected_stories_have_editorial` | A4 | 3 selected stories each have an editorial justification string |
| 4 | `eval_agent1_velocity_ranking` | A1 | Velocity formula ranks stories in the correct order |
| 5 | `eval_agent2_looks_like_real_content` | A2 | Trafilatura extracts non-empty text from 5 real cached URLs |
| 6 | `eval_agent2_strip_citation_artifacts` | A2 | Citation markers like `[1]` are stripped cleanly from extracted text |
| 7 | `eval_agent6_humanize_dates` | A6 | All 12 time buckets (today → 4+ years ago) produce correct human-readable strings |
| 8 | `eval_agent6_qc_script_compliance` | A6 | Script word count is within [150, 225] and all required sections present |
| 9 | `eval_agent7_shot_list_integrity` | A7 | 10 shots exist and their duration shares sum to exactly 1.00 |
| 10 | `eval_agent9_tags_fallback` | A9 | Fallback tag generation produces valid tags when primary fails |
| 11 | `eval_seo_completeness` | A9 | SEO title, description, and tags are all present and non-empty |

**Known failure:** #8 (`eval_agent6_qc_script_compliance`) — the golden
checkpoint contains a script with word_count=131, below the 150 minimum.
This is a data provenance issue (the checkpoint was saved from a run where
QC approved a too-short script), not an eval bug. Fix: re-run the pipeline
to produce a compliant checkpoint.

**SKIP handling:** Evals that can't import a dependency (e.g. trafilatura)
return `SKIPPED` and are excluded from the pass/fail count. With the
project venv (`../multi-agent-env/bin/python`), all 11 evals run with 0
skips.

---

### Layer 2 — Quality Evals (frozen golden datasets, LLM-judged or ref-based)

Each agent that classifies, judges, or generates text has a frozen golden
dataset — inputs where the correct output is already known. The eval runs
the agent on these inputs and compares its output to the human-labelled
answer.

**Entry point:** `python -m pytest evals/quality/ref_based/test_<agent>.py -v`

| Task | Agent | What it tests | Type | Metric | Gate | Score | Status |
|------|-------|--------------|------|--------|------|-------|--------|
| A1 | Agent 3 (Fact Checker) | Credibility labels: REAL / OPINION / SPAM | ref-based | Macro-F1 | ≥ 0.70 | **0.990** | PASS |
| A4 | Agent 4 (Editorial) | Dedup merge accuracy on planted duplicate pairs | ref-based | Micro-F1 | ≥ 0.70 | **0.800** | PASS |
| A5 | Agent 6 (Script QC) | JUDGE section-flag agreement on 10 scripts (some deliberately broken) | ref-based | Micro-F1 | ≥ 0.60 | **0.615** | PASS |
| A6 | Agent 5 (Script Writer) | Script generation quality across 7 dimensions (15 frozen story triples) | ref-free | Composite mean | ≥ 0.70 | **0.890** | PASS |

**Why two scoring types:**
- **Ref-based** (A1, A4, A5): a correct answer exists (the right label, the right merge group, the right flags). Scoring is pure Python comparison — exact match, F1, precision/recall.
- **Ref-free** (A6): no single correct script exists for a set of stories. An LLM judge (qwen3.8-27b on Groq) scores the output on a rubric across 7 dimensions (structure, word count, CTA, hook specificity, twist quality, faithfulness, story alignment).

**Golden datasets** (frozen, committed to git, never change):

| File | Agent | n | Contents |
|------|-------|---|---------|
| `golden_dataset/agent3_credibility_v1.json` | A3 | 30 | Stories + human label (REAL/OPINION/SPAM) |
| `golden_dataset/agent4_dedup_v1.json` | A4 | 10 sets (80 titles) | Title sets + expected merge pairs |
| `golden_dataset/agent5_script_v1.json` | A5 | 15 | Story triples as script generation inputs |
| `golden_dataset/agent6_judge_v2.json` | A6 | 10 | Scripts with planted issues + expected flags |

---

### Layer 3 — Judge Calibration (human vs LLM agreement)

The Layer 2 evals for Agent 5 use an LLM as the judge. But can we trust
the LLM judge? Calibration answers this: a human and the judge
independently score the same scripts, and we measure how often they agree.

**Entry point:**
```bash
python evals/calibration/run_calibration.py --judge      # LLM scores 10 scripts
python evals/calibration/run_calibration.py --agreement   # compare human vs LLM
```

| Metric | Value | Gate | Verdict |
|--------|-------|------|---------|
| Verdict agreement | 5/10 (50%) | ≥ 80% | **FAIL** |
| Flagged-section Jaccard | 0.200 | — | Low overlap |

**Root cause (structural, not random):**

The script template's `SECTION_ORDER` has no `S3_TWIST` — Story 3 never
resolves. The human catches this every time (flags S3_CORE on 6/10
scripts). The LLM judge only checks quality *within* existing sections,
so it can't flag a section that should exist but doesn't. This creates
3 false passes. Separately, the judge is stricter on micro-quality
(twist restatements, CTA phrasing), creating 2 false fails.

**Path forward:** Add S3_TWIST to the template, then re-calibrate.

**Dataset:** `calibration/judge_calibration_v1.json` (10 scripts, both
human and judge verdicts stored).

---

---

### Layer 4 — Operational Evals (infrastructure health, real network, no LLM judging)

Probes that test the pipeline's operational plumbing — API latency, tier
routing, fallback resilience, quota math, and chaos recovery. These answer
"will the pipeline survive a real run?" rather than "is the output good?"

**Entry point:** Individual scripts in `evals/ops/` (see `evals/ops/README.md`)

| Task | Script | What it tests | Verdict |
|------|--------|--------------|---------|
| B1 | `ops/ops_probe.py` | Agent 1 HN API latency + story count (×20 runs) | HEALTHY |
| B2 | `ops/tool_access_replay.py` | Agent 2 tier distribution on 40 cached URLs | HEALTHY |
| B3 | `ops/fallback_stress.py` | Agent 3 local fallback (qwen3.5:9b ×30 stories) | HEALTHY |
| B4 | `ops/quota_table.md` | Groq + YouTube quota arithmetic (static doc) | 2/day fits |
| B5 | `ops/chaos_checks.py` | Groq 429, Exa timeout, DDG timeout resilience | 6/6 HEALTHY |
| B6 | — | Fixes applied from B1–B3 findings | ✅ verified |

**B6 fixes applied:**
- Agent 1: concurrent HN fetches + over-fetch for non-story items
- Agent 2: `return_tier` parameter for clean tier-name returns

## How the Layers Connect

```
Layer 1: Unit evals (structural contracts, pure Python)
    ↓ all pass?
Layer 2: Quality evals (agent output vs frozen golden answers)
    ↓ all above threshold?
Layer 3: Calibration (can we trust the LLM judge used in Layer 2?)
    ↓ agreement ≥ 80%?
Layer 4: Operational evals (latency, fallback, chaos)
    ↓ all healthy?
CI gate (GitHub Actions — blocks PRs on failure)
```

**All four layers are built.** Phase C (CI regression gate) from the
Production Plan is complete — see `.github/workflows/evals.yml`.
Phase D (Langfuse tracing) is in progress — see
[Phase D — Langfuse Tracing](#phase-d--langfuse-tracing-in-progress) below.

### CI/CD — GitHub Actions (`evals.yml`)

The gate runs on every push to `main`, on PRs, and nightly at
00:30 UTC (06:00 IST). Manual trigger via `workflow_dispatch` is
also supported.

| Job | What it runs | Trigger | Behaviour |
|-----|-------------|---------|-----------|
| **fast-gate** | `evals/run_all.py` (11 unit evals) + `evals/ops/chaos_checks.py` (B5 — Groq 429, Exa timeout, DDG timeout) | Every push & PR | No API keys needed; blocks merge on any regression |
| **quality-gate** | `evals/run_all.py --content` — all unit evals + LLM-judge content evals (Agents 2-6 via `pytest evals/quality/`) | Nightly + manual + push to main | Needs `GROQ_KEY` GitHub secret; nightly runs save scored logs as artifacts (90-day retention) |

**Key design decisions:**
- Quality evals **SKIP** (not fail) on infra unavailability — when
  Ollama is absent on CI or Groq is rate-limited, the eval raises
  `RuntimeError("SKIPPED: ...")` which the wrapper catches and marks
  as a skip. Infra conditions never block a merge; only real quality
  regressions do.
- Chaos checks (B5) run in fast-gate because they mock network errors
  locally — no API keys, no external calls, under 2 minutes.
- Nightly quality runs log scores to `evals/results/nightly_*.log`
  and upload them as GitHub Actions artifacts for trend tracking.

### Phase C status — complete

| Task | Status | What exists |
|------|--------|-------------|
| C1 — requirements files | ✅ Done | `requirements.txt` (runtime) and `requirements-dev.txt` (adds pytest, deepeval, pytest-asyncio; includes `requirements.txt`) |
| C2 — `evals.yml` with two tiers | ✅ Done | `.github/workflows/evals.yml`: fast-gate (unit evals + chaos checks, no keys) on every push and PR; quality-gate (content evals, `GROQ_KEY`) nightly, on manual trigger, and on push to `main` |
| C3 — check local fallback models before a model swap | ✅ Done | Quality evals skip when Ollama is absent (as on CI), so running `python evals/run_all.py --content` on the Mac exercises the local models. There is no separate `--local` flag |
| C4 — keep each nightly score | ✅ Done | The nightly job writes `evals/results/nightly_<date>.log` and uploads it as a GitHub Actions artifact (90-day retention). Scores are not committed back to the repo |

---

## Phase D — Langfuse Tracing (in progress)

Status as of 2026-10-15: **D1–D5 done. Remaining from the plan's "done when": one daily run as a single trace (arrives with Phase E1).** The plan's
"done when" for Phase D (one daily run = one trace) is **not yet met** —
see *Known gaps*.

| Task | Status | What exists |
|------|--------|-------------|
| D1 — Langfuse Cloud + keys | ✅ Done | Account created, keys in `experiments/.env`, `langfuse==4.17.0` pinned in `requirements.txt` and `requirements-dev.txt` |
| D2 — trace one function | ✅ Done | Agent 5's script call traced first; model name and token usage confirmed in the UI |
| D3 — spans and generations for every agent | ✅ Done | Agents 1–10 emit spans/generations (table below), model + tokens on every LLM call, fallback generations visible, calls grouped by `session_id` per run (single trace arrives with Phase E1) |
| D4 — metadata (fallback fired, Agent 2 tier, story count, retries) | ✅ Done (verified on session `20261015_000939`) | `add_metadata` / `mark_issue` on every agent span: fallback fired, Agent 2 tier, story/shot/chunk counts, retries. Fallbacks show as WARNING, total failures as ERROR. Verify: filter the session by Level in the Langfuse UI |
| D5 — DeepEval scores into Langfuse | ✅ Done (verified: trace `eval-run:unit` + 12 scores in session `20261015_000939`) | `evals/langfuse_scores.py` (`EvalRunReporter`): `run_all.py` sends one BOOLEAN score per eval plus `eval/pass_rate`; `evals/conftest.py` sends pass/fail per DeepEval test; Agent 2 also sends `agent2/faithfulness_mean`. Each run is trace `eval-run:*` in session `eval-<timestamp>`, or in a pipeline session via `EVAL_SESSION_ID=<run_id>`. No-op without Langfuse keys |

### What is instrumented (D3)

| Agent | Span | Generations (model) |
|-------|------|---------------------|
| 1 Trend Hunter | `Agent-1:fetch-trends` | — |
| 2 Context Researcher | `Agent-2:fetch-trend-background` | `extract-keyword-ollama-local` (llama3.2:3b), `synthesize-groq-cloud` (openai/gpt-oss-20b, groq/compound-mini), `synthesize-local(ollama call)` (qwen3.5:9b) |
| 3 Fact Checker | `Agent-3:check-credibility` | `classify-groq-cloud` (openai/gpt-oss-120b), `check_contradiction-groq-cloud` (no model/tokens recorded in the run — see findings), local fallback call |
| 4 Editorial | `Agent-4:editorial-node` | `topic-clustering-ollama-local` (granite4.2:8b) |
| 5 Script Writer | `Agent-5:script-writer` | `script-generation-groq-cloud` (qwen/qwen3.8-27b); word-count correction call; local fallback call |
| 6 Script QC | `Agent-6:script-qc` | `judge-groq-cloud` (openai/gpt-oss-120b), `rewrite-groq-cloud` (qwen/qwen3.8-27b); local fallback calls |
| 6.1 Voice-Over | `Agent-6.1:voice-over` | — (Kokoro runs as a subprocess) |
| 7 Video Prompt | `Agent-7:video-assembly-prompt` | `stock-query-ollama-local` (qwen3.5:4b-mlx) |
| 8 Video Assembler | `Agent-8:video-assembler` → `Agent-8:render-and-mux` | — |
| 9 SEO | `Agent-9:seo-optimizer` | `tag-extraction-ollama-local` (qwen3.5:4b-mlx) |
| 10 Publisher | `Agent-10:publisher` → `upload-video`, `set-thumbnail` | — (upload inputs are not captured) |

Only the Groq and Ollama calls that actually ran in the verification run
were confirmed in the export; the fallback and correction generations are
instrumented in code but did not fire.

### Shared helper and configuration

`experiments/agent_tools/trace_utils.py` is the one place tracing helpers
live: it calls `load_dotenv()` before `get_client()`, and
`log_generation(model, input_tokens, output_tokens)` attaches model and
usage to the current generation. It never raises — a logging failure
prints a `[trace]` line and the pipeline continues.

| Variable | Purpose | Status |
|----------|---------|--------|
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | Selects the Langfuse project the traces go to | Set in `experiments/.env` |
| `LANGFUSE_TRACING_ENVIRONMENT` | Label stamped on every trace so runs can be filtered (`dev`, `ci`, `live`) | `dev` set in `.env`; CI and LIVE are not wired yet |
| `LANGFUSE_TRACING_ENABLED` | Kill switch (`false` turns tracing off) | Name confirmed in the `langfuse` 4.17.0 source; not yet exercised |
| `LANGFUSE_TIMEOUT` | Seconds the SDK waits when uploading traces (default 5). Short-lived scripts (evals, daily run) hit `Failed to export spans batch due to timeout` at 5s once; set to `30` in `experiments/.env` | Set to `30` |
| `EVAL_SESSION_ID` | Attach an eval run's scores to a pipeline session (e.g. `20261015_000939`) instead of a new `eval-<timestamp>` session | Optional |
| `EVAL_LIVE_CHECKPOINT` | `1` = evals read the latest live checkpoint instead of the frozen fixture | Optional; default is the fixture |

The last cell of `experiments/workflow.ipynb` calls `get_client().flush()`
so scheduled (papermill) runs do not exit with traces unsent.

### Verification

- **Full pipeline run, 2026-10-14:** Agents 1–10 in one run, 16m22s wall
  clock, 25 traces, 76 observations. Model name and token usage are present
  on every LLM call that returned a response, except the three Agent 3
  `check_contradiction` calls. Agent 10 uploaded a real video and set its
  thumbnail.
- **Evals with the instrumented agents:** `python evals/run_all.py` 11/11
  passed; `python evals/ops/chaos_checks.py` 6/6 passed (HEALTHY).
- **No-op without keys:** `trace_utils.py` with `langfuse==4.17.0` and no
  keys set returned normally from an `@observe` generation and from
  `flush()`, with no exception (Langfuse prints that the client is
  disabled). That test ran in an isolated environment. The 11/11 and 6/6
  eval run above had the `.env` keys loaded, so a strictly keyless run of
  the full eval suite is still to be done.

### First traced run — measured findings

Sum of top-level agent spans was 968s of 982s wall clock.

| Agent | Time | Share |
|-------|------|-------|
| 2 | 530s | 55% |
| 8 | 266s | 27.5% |
| 6.1 | 42s | 4% |
| 7 | 39s | 4% |
| 9 | 28s | 3% |
| 3 | 20s | 2% |
| 4 | 17s | 2% |
| 10 | 17s | 1.7% |
| 6 | 7s | 0.7% |
| 1 | 2s | 0.2% |
| 5 | 1s | 0.1% |

- **Agent 6's rewrite changed nothing.** The judge flagged `S1_CONTEXT` for
  marketing language in both rounds; both rewrites returned the same
  sentence (only the apostrophe differed). Cause not yet isolated — to be
  tested with an N=5 run on cached data before any prompt or model change.
- **Agent 2 cloud synthesis:** 1 of 5 attempts returned text; 4 returned
  empty in about 0.6s with no error recorded, and 3 stories made no cloud
  attempt. The one success logged 340,042 input tokens in a single
  `gpt-oss-20b` call. The cause of the empty returns is unknown because
  the exception is swallowed (this is what D4 is meant to expose).
- **Local model latency:** every local call has a floor of about 3–5s even
  for 3–5 output tokens, and `qwen3.5:9b` synthesis ran at roughly 2.5
  tokens/s (40–99s per story). Model loading or swapping between
  `llama3.2:3b` and `qwen3.5:9b` is a hypothesis, not a finding; Ollama's
  `load_duration` and `eval_duration` need to be logged to confirm.
- **Payload size:** each node span stores the whole pipeline state as input
  and output (about 60 KB each; 1.24 MB for the run).
- **Agent 3 `check_contradiction` appears to fail silently.** The function
  does call `log_generation`, yet all three calls in the run have no model or
  tokens, returned `false`, and took 2.0–2.1s — the length of its own
  `time.sleep(2)`. That points to the Groq call raising and the safe default
  (`False`) being returned. Cause unconfirmed: the printed
  `[verify] contradiction check failed (...)` line in the run output would
  show it. Its span name also does not follow the `classify-…` style.

### Known gaps

- Single trace per daily run is not done (Phase E1); each agent call is still its own trace, grouped by session.
- A daily run is 25 flat traces with an empty `sessionId`, not one trace.
  Grouping needs a session id (the existing run id is the candidate).
- `LANGFUSE_TRACING_ENVIRONMENT` is only set for `dev`. CI (`evals.yml`)
  and the daily runner (`run-notebook-daily.py`) do not set their own
  values yet, so a scheduled run would also be labelled `dev`.
- CI has no Langfuse secrets, so the fast-gate traces nothing (intended)
  and the quality-gate does not send traces yet.
- Node spans capture full state; should be replaced with small summaries
  once D4 metadata exists.

---

## File Map

### Infrastructure

| File | Purpose |
|------|---------|
| `run_all.py` | CI entry point — runs unit evals (+ content evals with `--content`), prints table, exit 0 or 1 |
| `unit_evals.py` | 11 deterministic eval functions (Layer 1) |
| `content_evals.py` | Content-level eval wrappers — bridges `pytest` quality evals into `run_all.py` for CI |
| `config.py` | Shared constants: TARGET_MIN_WORDS, TARGET_MAX_WORDS, SECTION_ORDER, paths |
| `dataset.py` | Golden data loaders: `load_golden_checkpoint()`, `load_stories_cache()`, `golden_script()`, `selected_stories()` |
| `__init__.py` | Package marker |

### CI Workflow

| File | Purpose |
|------|---------|
| `.github/workflows/evals.yml` | GitHub Actions — fast-gate (unit + chaos) and quality-gate (content evals), nightly cron |

### Quality Eval Scripts (Layer 2)

| File | Agent | What it does |
|------|-------|-------------|
| `quality/ref_free/test_agent2.py` | A2 | Calls `synthesize_background()` on 15 stories, G-Eval faithfulness judge (threshold ≥ 0.70) |
| `quality/ref_based/test_agent3.py` | A3 | Calls `llm_credibility_check()` on 30 stories, computes macro-F1 |
| `quality/ref_based/test_agent4_v3.py` | A4 | Calls `deduplicate_stories()` on 10 title sets, computes micro-F1 |
| `quality/ref_based/test_agent4_granite_n5.py` | A4 | Granite 4.2:8b variant (n=5 subset) |
| `quality/ref_based/test_agent5.py` | A5 | Calls `script_writer_node()` on 15 inputs, scores 7 dimensions |
| `quality/ref_based/test_agent6.py` | A6 | Calls `_judge_script()` on 10 scripts, computes micro-F1 |
| `quality/groq_judge.py` | — | GroqJudge adapter for DeepEval (routes judge calls to Groq) |
| `quality/__init__.py` | — | Package marker |
| `quality/ref_based/__init__.py` | — | Package marker |
| `quality/ref_free/__init__.py` | — | Package marker |

### Calibration (Layer 3)

| File | Purpose |
|------|---------|
| `calibration/run_calibration.py` | Runs LLM judge on calibration scripts (`--judge`) and computes agreement (`--agreement`) |
| `calibration/judge_calibration_v1.json` | 10 scripts with human + judge verdicts and flags |

### Operational Evals (Layer 4)

| File | Task | Purpose |
|------|------|---------|
| `ops/README.md` | — | Layer 4 documentation and run instructions |
| `ops/ops_probe.py` | B1 | Agent 1 HN API latency + story count (×20 runs) |
| `ops/tool_access_replay.py` | B2 | Agent 2 tier distribution on 40 cached URLs |
| `ops/fallback_stress.py` | B3 | Agent 3 local fallback stress test (qwen3.5:9b ×30 stories) |
| `ops/quota_table.md` | B4 | Groq + YouTube quota arithmetic (static doc) |
| `ops/chaos_checks.py` | B5 | Groq 429, Exa timeout, DDG timeout resilience (runs in CI fast-gate) |

### Golden Datasets

| File | Agent | Contents |
|------|-------|----------|
| `golden_dataset/agent2_context_v1.json` | A2 | 15 stories with title, content, snippets for faithfulness eval |
| `golden_dataset/agent3_credibility_v1.json` | A3 | 30 stories with human-labelled credibility |
| `golden_dataset/agent4_dedup_v1.json` | A4 | 10 title sets with human-labelled duplicates |
| `golden_dataset/agent5_script_v1.json` | A5 | 15 frozen inputs for script generation eval |
| `golden_dataset/agent6_judge_v2.json` | A6 | 10 scripts with human-labelled judge verdicts |
| `golden_dataset/LABELING_GUIDE.md` | — | Instructions for labelling golden datasets |
| `golden_dataset/label_helper.py` | — | Helper script for labelling workflow |
| `golden_dataset/pull_candidates.py` | — | Pulls candidate stories from cache for golden set construction |

### Fixtures

| File | Purpose |
|------|---------|
| `fixtures/golden_checkpoint.json` | Frozen pipeline checkpoint for deterministic unit evals |
| `fixtures/stories_cache.json` | Frozen story cache for deterministic unit evals |

### Baseline Results

| File | Key finding |
|------|-------------|
| `results/unit_evals_baseline.md` | 10/11 passed, 0 skipped, 1 known data issue |
| `results/agent3_baseline.md` | Macro-F1 = 0.990, 29/30 correct |
| `results/agent4_baseline.md` | Micro-F1 = 0.800 (granite4.2:8b), PASS |
| `results/agent5_baseline.md` | Composite = 0.890 (n=15), PASS |
| `results/agent6_baseline.md` | Micro-F1 = 0.615, PASS |
| `results/calibration_baseline.md` | 50% verdict agreement, root cause = missing S3_TWIST |
| `results/b1_probe_baseline.md` | HN API latency + story count baseline |
| `results/b2_replay_baseline.md` | Tier distribution replay baseline |
| `results/b3_fallback_baseline.md` | Fallback stress test baseline |
| `results/b5_chaos_baseline.md` | Chaos checks baseline (6/6 HEALTHY) |
| `results/b6_fixes_baseline.md` | Fixes applied from B1–B3 findings |

---

## Design Principles

1. **Deterministic where possible.** Word count, section presence, velocity
   ranking, date formatting — these are pure Python, never delegated to an
   LLM. Reliable, reproducible, free.

2. **Frozen inputs.** Golden datasets are committed to git and never change.
   If an agent's behavior changes, the eval catches it.

3. **Model swap policy.** Every model swap requires a multi-run reliability
   test (N ≥ 5) using real cached data before integration.

4. **Honest baselines.** A 50% calibration score is documented as-is with
   root cause analysis, not swept under the rug. The eval system's job is
   to reveal problems, not hide them.
