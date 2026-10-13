# B4 — Quota Table

**Date**: 2026-10-13
**Purpose**: Answer "what breaks first if traffic grows?" with arithmetic,
not guesses.

---

## Groq Cloud — Per-Model Daily Token Limits

| Model | Agent(s) | Daily Pool | Est. Tokens/Run | Runs/Day Before 429 |
|-------|----------|------------|-----------------|---------------------|
| `openai/gpt-oss-120b` | Agent 3 (credibility) | 200K TPD | ~8 stories × ~2K tokens ≈ **16K** | **~12** |
| `openai/gpt-oss-20b` | Agent 2 (big-boss fallback) | 200K TPD | ~2 stories × ~3K tokens ≈ **6K** (fires rarely) | **~33** (if every run triggers it) |
| `groq/compound-mini` | Agent 2 (0-snippet synthesis) + Agent 3 (contradiction) | 8K TPM | ~2K per call, ~3 calls/run ≈ **6K** | **TPM-limited**: max 1 run/min, ~1440/day in theory |
| `llama-3.3-70b-versatile` | Agent 5 (script) + Agent 6 (rewrite) | 100K TPD | ~3K (script) + ~3K (rewrite) ≈ **6K** | **~16** |

### First Limit Hit

**`openai/gpt-oss-120b` at ~12 runs/day** — Agent 3 classifies all 8 stories
every run, each classification sends the full article (up to 6000 chars) as
the prompt. This is the tightest bottleneck by far.

Second limit: `llama-3.3-70b-versatile` at ~16 runs/day (script generation +
QC rewrite).

### What This Means for "2 Videos/Day" Target

2 runs/day = ~32K tokens on gpt-oss-120b (16% of daily quota). **Comfortably
within limits.** The ceiling is ~6x the target before any 429s.

At 5 runs/day (pipeline experimentation + reruns): ~80K tokens = 40% of quota.
Still safe.

---

## YouTube Data API v3 — Upload Quota

| Resource | Cost (units) | Daily Quota | Videos/Day |
|----------|-------------|-------------|------------|
| `videos.insert` | 1,600 | 10,000 | **6** |
| Thumbnail upload | 50 | (shared) | — |
| **Total per video** | **1,650** | **10,000** | **~6** |

### YouTube Bottleneck

At 2 videos/day: 3,300 units = 33% of daily quota. **Well within limits.**

Maximum: ~6 videos/day before quota exhaustion. This is a hard YouTube-side
limit that cannot be raised on the free tier.

---

## Local Models (Ollama) — No Quota

| Model | Agent(s) | Limit |
|-------|----------|-------|
| `phi3.5` | Agent 2 (wiki keywords) | None — local |
| `llama3.1:8b` | Agent 2 (background synthesis) | None — local |
| `qwen2.5:7b` | Agent 4 (dedup) + Agent 3 fallback | None — local |
| `gemma2:9b` / `gemma3:12b` | Agent 6 rewrite fallback / Agent 5 fallback | None — local |
| `qwen3.5:9b` | Agent 3 credibility fallback | None — local |

Local models are the safety net: when Groq quota is exhausted, fallback
models keep the pipeline alive (slower but functional).

---

## Summary: What Breaks First at Scale

| Scale | First Bottleneck | What Happens |
|-------|-----------------|--------------|
| 2 runs/day (target) | Nothing | All quotas at <33% |
| 6 runs/day | YouTube uploads | Hard cap at ~6 videos/day |
| 12 runs/day | `gpt-oss-120b` (Agent 3) | 429 → falls back to qwen3.5:9b local (slower, still works) |
| 16 runs/day | `llama-3.3-70b` (Agent 5) | 429 → falls back to gemma3:12b local (slower, still works) |
| 33 runs/day | `gpt-oss-20b` (Agent 2) | 429 → falls back to llama3.1:8b local (already the primary path) |

**Bottom line**: The 2 videos/day target sits at ~16% of every quota ceiling.
The first hard wall is YouTube at 6 videos/day. The first Groq wall is
gpt-oss-120b at ~12 runs/day, but that degrades gracefully via local fallback.
