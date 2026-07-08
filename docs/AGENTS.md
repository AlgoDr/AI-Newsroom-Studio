# Agent Architecture — Detailed Reference

Full technical breakdown of every agent's internal design: functions, formulas,
prompt engineering decisions, and real failure modes encountered during
development. The [main README](../README.md) has the high-level summary —
this document is the deep-dive for each agent.

**Contents:** [Agent 2](#agent-2--context-researcher-detailed) · [Agent 3](#agent-3--fact-checker-detailed) · [Agent 4](#agent-4--editorial-detailed) · [Agent 5](#agent-5--script-writer-detailed)

Agent 1 (Trend Hunter) has no dedicated section here — its entire logic is
one velocity formula, documented fully in the main README's pipeline diagram.

---

### Agent 2 — Context Researcher (detailed)

Agent 2 is the most complex agent built so far. It runs three internal stages for every story.

![Agent 2 Architecture](./agent2_architecture.svg)


```
STAGE 1 — Content Fetch (3-tier fallback)
  trafilatura → Jina AI reader → Tavily extract
  Each tier gated by looks_like_real_content():
    ✓ length check (≥200 chars)
    ✓ whitespace ratio check
    ✓ junk markers (Cloudflare, Akamai, captcha...)
    ✓ prose-line check (menus vs articles)

STAGE 2 — Background Gather
  DDG news search (up to 5 snippets, 2s rate-limit sleep)
  + Wikipedia summary (phi3.5 extracts keyword → 12 sentences)
  → combined snippets list

STAGE 3 — Synthesis (intent-based routing)
  0 snippets + small payload  → groq/compound (web search built-in)
  rich snippets OR large payload → llama3.1:8b local (no size limit)
  Either path → _clean_synthesis() → story["background"]
```

### Agent 3 — Fact Checker (detailed)

![Agent 3 Architecture](./agent3_architecture.svg)

Agent 3 v2 scores credibility on a **-1 to +1 scale**. Zero is the natural boundary — negative = discard, positive = keep.

**Three signals with dynamic reweighting:**

| Signal | Base Weight | Range | How |
|--------|-------------|-------|-----|
| `source_score` | 20% | 0.0 to +0.95 | 35-domain trust map (HN-tuned) |
| `llm_credibility_check` | 60% | -0.7 to +0.9 | gpt-oss-120b → REAL/OPINION/SPAM |
| `cross_verify` | 20% | -0.6 to +0.8 | Exa semantic search → DDG fallback |

**Label scores:** REAL → +0.9 · OPINION → +0.1 · SPAM → -0.7

**Dynamic reweighting** — shifts when cross_verify fires:
- Contradiction detected: llm 60%→30%, verify 20%→50% (contradiction amplified)
- Confirmation detected:  llm 60%→50%, verify 20%→30% (verify boosted)
- Neutral (not found):    standard weights unchanged

**Guards:**
- content < 100 chars → 0.0 neutral (can't verify)
- content < 500 chars → 0.0 neutral (too thin to judge)
- Groq failure / empty response → 0.0 neutral (never discard on crash)

**Cross-verification:**
- Exa semantic search (primary) — finds story variants, HN-aware indexing
- DDG news fallback — already in pipeline, free, real-time
- Only sources with trust ≥ 0.70 can trigger verification signals
- Contradiction check uses compound-mini (separate quota from 120b)

**Quota isolation (three separate Groq pools):**
- gpt-oss-120b: credibility classification (200K tokens/day)
- gpt-oss-20b:  Agent 2 big-boss synthesis (200K tokens/day)
- compound-mini: contradiction check (own TPM pool)

```python
combined = round(src×w_src + llm×w_llm + verify×w_verify, 2)
score < 0.0 → story["discarded"] = True  (marked, NOT deleted — audit trail)
```

### Agent 4 — Editorial (detailed)

![Agent 4 Architecture](./agent4_architecture.svg)

Agent 4 answers "which stories should we actually cover today?" — filtering, scoring, deduplicating, and selecting the top 3 from Agent 3's credibility-scored pool.

**Four-step pipeline (pure Python except deduplication):**

| Step | Function | What |
|------|----------|------|
| 1 | `filter_stories()` | Remove `discarded=True` stories (no model, no API) |
| 2 | `score_editorially()` | Composite score, addition not multiplication |
| 3 | `deduplicate_topics()` | qwen2.5:7b clusters titles by topic (one call) |
| 4 | `select_top_stories()` | Sort by editorial_score, take top 3 |

**Editorial score formula (weighted addition, not multiplication):**

```python
vel_norm = min(velocity / max_velocity_in_batch, 1.0)   # relative to today's batch
bg_norm  = min(len(background) / 800, 1.0)               # 0-1, capped at 800 chars

editorial_score = credibility_score×0.50 + vel_norm×0.30 + bg_norm×0.20
```

Why addition, not multiplication: a viral, credible story with a thin
background would score **zero** under multiplication (one weak signal
kills everything). Addition means each signal contributes independently —
missing background is a *penalty*, not a *veto*.

**Deduplication — model evolution during testing:**
- phi3.5 (3.8B): correct JSON *format* issues fixed with 2-layer cleaning
  (trailing commas, spaces in brackets, text mixed with numbers) —
  but still clustered *unrelated* stories together (e.g. grouped a NAS
  tutorial with a TTS tool as "both local software")
- **qwen2.5:7b** (current): better semantic topic separation, same
  2-layer JSON safety net retained. See KNOWN_ISSUES ISSUE-9.

**Topic clusters → keep highest editorial_score per cluster:**
```python
# phi3.5/qwen2.5:7b returns: [[1,3],[2],[4],[5],[6],[7],[8]]
# story 1 and 3 are "same topic" → keep whichever scores higher
# story marked _is_duplicate=True is excluded from selection, NOT deleted
```

**LangGraph conditional edge (first branching point in the pipeline):**
```python
def route_after_editorial(state) -> str:
    selected = [s for s in state["stories"].values() if s.get("selected")]
    if len(selected) >= 1:
        return "script_writer"   # even ONE great story is worth covering
    return "end"                  # 0 stories → macOS notification, pipeline stops
```
Real newsroom logic: a fixed quota of 3 is wrong. Quality over quantity —
one credible, high-velocity story beats padding to reach a number.

**Fields added per story:**
```
editorial_score · selected · selection_rank · selection_reason
_vel_norm · _bg_norm · _topic_cluster · _is_duplicate
```

### Agent 5 — Script Writer (detailed)

![Agent 5 Architecture](./agent5_architecture.svg)

Agent 5 turns the top 3 selected stories into ONE continuous 60-90 second
YouTube Shorts script, using `llama-3.3-70b-versatile` — a separate Groq
quota pool from Agent 3's `gpt-oss-120b`.

**Six-function pipeline:**

| Function | Job |
|----------|-----|
| `_get_selected_stories()` | Filter `selected=True`, sort by `selection_rank` |
| `_tone_instruction()` | Map `credibility_score` → confident / attributed / cautious |
| `_build_prompt()` | Assemble one prompt covering all 3 stories |
| (LLM call) | `llama-3.3-70b-versatile`, temperature=0.4, one call |
| `_enforce_word_count()` | Trim/expand if outside 150-225 words, max 2 attempts |
| `_parse_script()` | Regex-extract 10 labelled sections |

**Tone calibration — driven entirely by Agent 3's credibility_score:**
```
cred > 0.5   → "Write confidently. State facts directly. Use specific numbers."
cred > 0.15  → "Attribute clearly: 'According to the report', 'The company says'"
cred < 0.15  → "Cautious framing: 'Reports suggest', 'If accurate, this means'"
```

**Section labels (word budget: rank1=90w, rank2=70w, rank3=55w ≈ 215w total):**
```
HOOK → S1_CONTEXT → S1_CORE → S1_TWIST →
S2_HOOK → S2_CORE → S2_TWIST →
S3_HOOK → S3_CORE → CTA
```

**Prompt engineering lessons learned (iterative, real-run driven):**

| Problem observed | Fix applied |
|---|---|
| HOOK was generic ("New tech updates daily") | BAD/GOOD examples in prompt, rule: "must name ONE specific fact" |
| TWIST just restated CORE | Explicit rule: "must reveal a consequence NOT already stated" |
| Model reordered stories for drama | `temperature 0.7→0.4` + explicit "write in exact order given" |
| CTA became a custom 30-word paragraph | "WORD-FOR-WORD, copy one of three options exactly" |
| Transitions were flat ("Meanwhile...") | Two-part rule: signal completion, then open next story with tension |
| AI press-release voice ("can generate high-quality speech") | Banned-phrases list + "write like a friend explaining over coffee" |
| First draft undershot word count (105w) | Word-count enforcement with trim/expand, max 2 attempts |
| Expand attempt overshot badly (105w→387w) | Explicit ceiling: "target X words exactly, not just 'at least'" |

**Word count enforcement — never blocks the pipeline:**
```python
150-225 words        → pass through immediately
> 225 words          → one trim call → re-check
< 150 words          → one expand call → re-check
still wrong after 2   → accept as-is with warning (Agent 6 QC catches it)
```

**Output — first top-level key in NewsroomState (not per-story):**
```python
state["script"] = {
    "full_text":    str,   # complete script
    "word_count":   int,   # verified count
    "est_duration": str,   # e.g. "78s"
    "sections":     dict,  # 10 labelled sections
    "stories_used": list,  # [1, 2, 3] selection ranks
    "attempt":      int,   # 1 or 2 (audit trail)
}
```

**Design boundary — Agent 5 vs Agent 6:**
Agent 5 owns *what* to say (facts, structure, word count). Human-voice
polish, date humanization ("August 23, 2024" → "last year"), and pacing
annotations (`[PAUSE]` `[BEAT]` `[EMPHASIS]`) are explicitly deferred to
Agent 6 — Agent 5 doesn't know today's date, Agent 6 will.
