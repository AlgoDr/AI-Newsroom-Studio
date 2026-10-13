# Phase B — Offline Operational Evals

Operational probes that test the pipeline's **infrastructure health** — latency,
fallback resilience, tier distribution, quota math, and chaos recovery. No LLM
quality judgments; everything here is timing, counting, and exception handling.

**Run from repo root** (all scripts expect `experiments/` on the path):

\`\`\`bash
python evals/ops/ops_probe.py              # B1 — Agent 1 HN probe
python evals/ops/tool_access_replay.py     # B2 — Agent 2 tier replay
python evals/ops/fallback_stress.py        # B3 — Agent 3 local fallback stress
python evals/ops/chaos_checks.py           # B5 — chaos/failure-mode checks
# B4 (quota_table.md) is a static arithmetic doc — no runner
\`\`\`

---

## Tasks

### B1 — Agent 1 HN API Probe (`ops_probe.py`)

Calls `fetch_trends()` N times (default 20), measures wall-clock latency,
story count, and empty-URL rate.

| Metric | Threshold | Baseline (2026-10-13) |
|--------|-----------|-----------------------|
| p95 latency | ≤ 15s | 11.5s |
| Stories/call | = 8 | 8 (100%) |
| Empty URLs | ≤ 10% | 0% |
| Verdict | | **HEALTHY** |

### B2 — Agent 2 Tier Replay (`tool_access_replay.py`)

Replays `fetch_url_content(url, return_tier=True)` on cached URLs from
`stories_cache.json`. Records which tier served each (trafilatura → jina →
tavily → none) and the empty-content rate.

| Metric | Threshold | Baseline (2026-10-13) |
|--------|-----------|-----------------------|
| Empty rate | ≤ 25% | 2.5% |
| Trafilatura share | — (info) | 78% |
| Jina share | — (info) | 20% |
| Tavily share | — (info) | 0% |
| Verdict | | **HEALTHY** |

### B3 — Fallback Stress Test (`fallback_stress.py`)

Forces Agent 3 onto local `qwen3.5:9b` (Ollama) for N stories (default 30).
Measures cold-start latency, warm p50/p95, and label parse rate.

| Metric | Threshold | Baseline (2026-10-13) |
|--------|-----------|-----------------------|
| Cold start | ≤ 30s | 13.5s |
| Warm p95 | ≤ 25s | 19.6s |
| Parse rate | ≥ 80% | 100% |
| Verdict | | **HEALTHY** |

Note: warm p95 threshold set to 25s — a 9B model processing full articles
on fallback is inherently slower than the cloud primary. 5s was unrealistic.

### B4 — Quota Table (`quota_table.md`)

Static arithmetic doc — Groq token limits per model, YouTube API quota budget.
No runner; the numbers are the deliverable.

**Key finding:** 2 videos/day = 16% of every quota. First hard wall is YouTube
at 6 videos/day (1,600 units × 6 = 9,600 of 10,000). First Groq wall is
gpt-oss-120b at ~12 pipeline runs/day.

### B5 — Chaos Checks (`chaos_checks.py`)

Monkeypatches failure modes into Agents 2–3 and verifies graceful degradation:

| # | Scenario | What's patched | Expected behavior |
|---|----------|----------------|-------------------|
| 1 | Groq 429 | `agent3.groq_client` → raises RateLimitError | Falls back to local qwen3.5:9b |
| 2 | Exa timeout | `agent3._get_exa_client` → raises ConnectionError | Falls back to DDG search |
| 3 | DDG timeout | `DDGS` class → `news()` raises TimeoutError | Returns neutral cross-verify |
| 4 | Groq 429 (verify) | Same as #1, checks label output | Label is REAL/OPINION/SPAM |
| 5 | Exa timeout (verify) | Same as #2, checks result list | Returns list (possibly empty) |
| 6 | DDG timeout (verify) | Same as #3, checks result structure | Returns dict with neutral scores |

**Baseline:** 6/6 HEALTHY

### B6 — Fix What B1–B3 Found

Applied and verified two fixes discovered by the B1–B3 probes:

| Fix | Agent | Problem | Solution | Verified |
|-----|-------|---------|----------|----------|
| 1 | Agent 1 | Sequential HN fetches, non-story items reducing count | `ThreadPoolExecutor` + over-fetch (12 IDs for 8 stories) | ✅ 8 stories, HEALTHY |
| 2 | Agent 2 | Tier name not in return value (stdout capture was fragile) | `return_tier=True` param returning `(content, tier)` tuple | ✅ B2 replay clean |

---

## File Map

| File | Task | Purpose |
|------|------|---------|
| `ops_probe.py` | B1 | Agent 1 HN API latency + story count probe |
| `tool_access_replay.py` | B2 | Agent 2 tier distribution replay |
| `fallback_stress.py` | B3 | Agent 3 local fallback stress test |
| `quota_table.md` | B4 | Groq + YouTube quota arithmetic |
| `chaos_checks.py` | B5 | Failure-mode / chaos checks |

## Baseline Results (in `evals/results/`)

| File | Task |
|------|------|
| `b1_probe_baseline.md` | B1 baseline numbers |
| `b2_replay_baseline.md` | B2 tier distribution |
| `b3_fallback_baseline.md` | B3 fallback latency + parse rate |
| `b5_chaos_baseline.md` | B5 chaos check results |
| `b6_fixes_baseline.md` | B6 fix descriptions + verification |

---

## Design Notes

- **No LLM quality judgments.** These evals measure infrastructure — latency,
  tier routing, exception handling. Quality is Phase A's job.
- **Real network calls.** B1 and B2 hit live APIs (HN, trafilatura, Jina).
  Results vary by network conditions. Thresholds are set with margin.
- **Monkeypatch, not mocks.** B5 patches the actual agent code paths so the
  test exercises real fallback logic, not a simulation of it.
- **Thresholds are documented with rationale.** When a threshold was adjusted
  (B3 warm p95: 5s → 25s), the reason is recorded in the baseline doc.
