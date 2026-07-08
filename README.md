# 🎙️ AI Newsroom Studio

<div align="center">

![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-In_Progress-FF6B6B?style=for-the-badge)
![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-black?style=for-the-badge)
![Groq](https://img.shields.io/badge/Groq-Cloud_Inference-F55036?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Agents_1--5_Complete-brightgreen?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

**A fully autonomous, multi-agent AI pipeline that researches trending tech news, fact-checks it, writes engaging scripts, generates short-form videos, and publishes them to YouTube — all without human intervention.**

[Overview](#-overview) • [What's Built](#-whats-built-so-far) • [Architecture](#-agent-architecture) • [Tech Stack](#-tech-stack) • [Setup](#-getting-started) • [Roadmap](#-development-roadmap)

</div>

---

## 📌 Overview

AI Newsroom Studio is a production-grade multi-agent system that mirrors how a real newsroom operates — except every role is played by a specialized AI agent. From trend discovery to YouTube upload, the entire pipeline runs autonomously on a daily schedule.

The system identifies the most buzzworthy topics from HackerNews, enriches them with article content and background context, fact-checks credibility, selects the top stories editorially, writes a compelling script, generates a short-form video, and publishes it — all in one unattended pipeline run.

### Why This Project?

- **Real-world multi-agent orchestration** — not a toy demo, built line by line
- **Edge AI + Cloud hybrid** — local Ollama models for dev, cloud APIs for production precision
- **Honest engineering** — every design decision is documented, including what failed and why
- **Short-form first** — targets YouTube Shorts (60–90 sec) for algorithmic reach

---

## ✅ What's Built So Far

| Agent | Status | Description |
|-------|--------|-------------|
| **Agent 1 — Trend Hunter** | ✅ Complete | HackerNews top stories with velocity scoring |
| **Agent 2 — Context Researcher** | ✅ Complete | 3-tier content fetch + background synthesis |
| **Agent 3 — Fact Checker** | ✅ Complete | 3-signal scoring (-1 to +1): source + LLM + cross-verify |
| **Agent 4 — Editorial** | ✅ Complete | Filter → score → deduplicate (qwen2.5:7b) → select top 3 |
| **Agent 5 — Script Writer** | ✅ Complete | HOOK → CONTEXT → CORE → TWIST → CTA (llama-3.3-70b) |
| Agent 6 — Script QC | 🔨 Next | APPROVE/REVISE loop, pacing annotations |
| Agent 7 — Video Prompt | ⏳ Planned | Scene-by-scene cinematic prompts |
| Agent 8 — Video Generator | ⏳ Planned | MOCK ffmpeg first, Fal.ai Wan later |
| Agent 9 — SEO Optimizer | ⏳ Planned | Title, description, tags |
| Agent 10 — Publisher | ⏳ Planned | YouTube Data API v3 |

---

## 🏗️ Agent Architecture

### Pipeline Overview

```
HackerNews API
     │
     ▼
┌─────────────────┐
│  Agent 1        │  velocity = (upvotes + comments×2) / age_hrs
│  Trend Hunter   │  → top 8 stories sorted by velocity
└────────┬────────┘
         │  title + url + velocity
         ▼
┌─────────────────┐
│  Agent 2        │  3-tier content fetch → background synthesis
│  Context        │  → story["content"] + story["background"]
│  Researcher     │
└────────┬────────┘
         │  content + background
         ▼
┌─────────────────┐
│  Agent 3        │  source(20%) + LLM(60%) + cross-verify(20%), dynamic
│  Fact Checker   │  → story["credibility_score"] (-1 to +1) + discarded
└────────┬────────┘
         │
    ┌────┴─────┐
    ▼           ▼
[DISCARD]   [KEEP]
score<0.0   score≥0.0
         │
         ▼
┌─────────────────┐
│  Agent 4        │  filter → score → deduplicate → select top 3
│  Editorial      │  → story["editorial_score"] + story["selected"]
└────────┬────────┘
         │  top 3 selected stories (by selection_rank)
    ┌────┴─────┐
    ▼           ▼
 [0 stories]  [≥1 story]
  end + notify    │
         ▼
┌─────────────────┐
│  Agent 5        │  HOOK → CONTEXT → CORE → TWIST → CTA (one LLM call)
│  Script Writer  │  → state["script"] (first top-level state key)
└────────┬────────┘
         │  full_text + word_count + sections
         ▼
    Agent 6 → ... → Agent 10
    (in progress)
```

### Detailed Agent Architecture

Each agent's internal functions, formulas, and prompt-engineering decisions
are documented in full in **[docs/AGENTS.md](./docs/AGENTS.md)** — including
the real failure modes hit during development and the exact fixes applied.

| Agent | One-line summary |
|---|---|
| **[Agent 2 — Context Researcher](./docs/AGENTS.md#agent-2--context-researcher-detailed)** | 3-tier content fetch (trafilatura→Jina→Tavily) → background synthesis (compound-mini/8B routing) |
| **[Agent 3 — Fact Checker](./docs/AGENTS.md#agent-3--fact-checker-detailed)** | 3-signal credibility (-1 to +1): domain trust + LLM classification + Exa/DDG cross-verify, dynamically reweighted |
| **[Agent 4 — Editorial](./docs/AGENTS.md#agent-4--editorial-detailed)** | Filter → weighted-addition score → qwen2.5:7b topic dedup → select top 3, LangGraph conditional edge |
| **[Agent 5 — Script Writer](./docs/AGENTS.md#agent-5--script-writer-detailed)** | One llama-3.3-70b call → HOOK/CONTEXT/CORE/TWIST/CTA × 3 stories, credibility-driven tone |

---

## 🛠️ Tech Stack

### LLM Routing (Dev vs Production)

| Stage | Dev (local) | Production (one dict change) |
|-------|-------------|------------------------------|
| Wiki keyword extraction | phi3.5 (3.8B, Ollama) | same |
| Background synthesis | llama3.1:8b (Ollama) | gemini-2.0-flash |
| Synthesis for 0-snippet stories | groq/compound-mini | groq/compound-mini |
| Big-boss synthesis fallback | Groq gpt-oss-20b | Groq gpt-oss-20b |
| Credibility classification | Groq gpt-oss-120b | Groq gpt-oss-120b |
| Contradiction check | groq/compound-mini | groq/compound-mini |
| Topic deduplication | qwen2.5:7b (Ollama) | qwen2.5:7b (Ollama) |
| Script generation | Groq llama-3.3-70b-versatile | Groq llama-3.3-70b-versatile |

### Data Sources

| Source | What | Cost |
|--------|------|------|
| HackerNews Firebase API | Top stories + engagement | Free, no key |
| DuckDuckGo News (DDGS) | Background snippets + Agent 3 cross-verify fallback | Free, no key |
| Wikipedia (python lib) | Background summaries | Free, no key |
| Jina AI reader | JS-heavy page content | Free tier |
| Tavily Extract | Paywalled/blocked content | Free tier |
| Exa Search | Agent 3 semantic cross-verification (primary) | Free tier |
| Groq Cloud | Credibility, synthesis fallback, script generation | Free tier (per-model daily limits) |

### Models in Use

| Model | Size | Where | Job | Quota Pool |
|-------|------|--------|-----|------------|
| phi3.5 | 3.8B | Ollama local | Wikipedia keyword extraction | — (local) |
| llama3.1:8b | 8B | Ollama local | Background synthesis (primary) | — (local) |
| qwen2.5:7b | 7B | Ollama local | Agent 4 topic deduplication | — (local) |
| groq/compound-mini | cloud | Groq | 0-snippet synthesis + contradiction check | 8K TPM (shared, own pool) |
| openai/gpt-oss-20b | 20B | Groq | Agent 2 big-boss synthesis fallback | 200K TPD (own pool) |
| openai/gpt-oss-120b | 120B | Groq | Credibility classification | 200K TPD (own pool) |
| llama-3.3-70b-versatile | 70B | Groq | Script generation (Agent 5) | 100K TPD (own pool) |

**Quota isolation matters:** three Groq models above have fully separate
daily pools, confirmed via independent 429 responses in live runs.
See KNOWN_ISSUES ISSUE-7.

---

## 📁 Project Structure

```
NewsStudio/
├── experiments/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── agent1.py          # Trend Hunter — HackerNews + velocity
│   │   ├── agent2.py          # Context Researcher — fetch + background
│   │   ├── agent3.py          # Fact Checker — 3-signal credibility scoring
│   │   ├── agent4.py          # Editorial — filter/score/dedup/select
│   │   └── agent5.py          # Script Writer — HOOK→CORE→TWIST→CTA
│   │
│   ├── agent_tools/
│   │   ├── __init__.py
│   │   ├── story_cache.py      # Persist Agent 1-3 output (data/stories_cache.json)
│   │   ├── pipeline_cache.py   # Persist Agent 4-5+ full state (data/checkpoints/)
│   │   └── milestone_tracker.py # macOS alerts at N function-hit milestones
│   │
│   ├── workflow.ipynb          # Main pipeline notebook (A1→A2→A3→A4→A5)
│   └── __init__.py
│
├── data/                        # gitignored — local cache + checkpoints
│   ├── stories_cache.json
│   └── checkpoints/
│       └── till-agent5.json
│
├── docs/
│   ├── agent2_architecture.svg
│   ├── agent3_architecture.svg
│   ├── agent4_architecture.svg
│   └── agent5_architecture.svg
│
├── KNOWN_ISSUES.md             # 11 documented limitations (not bugs)
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.13+
- [Ollama](https://ollama.ai) installed and running
- Groq API key (free at console.groq.com)
- Tavily API key (free tier)
- Exa API key (free tier, for Agent 3 cross-verification)

### Installation

```bash
# 1. Clone the repo
git clone https://github.com/AlgoDr/AI-Newsroom-Studio.git
cd AI-Newsroom-Studio

# 2. Create virtual environment
python -m venv multi-agent-env
source multi-agent-env/bin/activate

# 3. Install dependencies
pip install trafilatura requests ddgs wikipedia \
            ollama groq tavily-python exa-py langchain-core \
            typing_extensions

# 4. Pull local models
ollama pull phi3.5
ollama pull llama3.1:8b
ollama pull qwen2.5:7b

# 5. Set up environment variables
cp .env.example .env   # then fill in your keys
```

### Environment Variables

```env
GROQ_KEY=your_groq_api_key
TAVILY_API_KEY=your_tavily_api_key
EXA_API_KEY=your_exa_api_key
```

> **Note:** `.env` may also carry `NEWS_API`, `SERPER_KEY`, or
> `CURRENT_API_KEY` from earlier experimentation — these are not
> required by any agent currently in the pipeline (1-5) and can be
> left blank or removed.

### Run the Pipeline

Open `experiments/workflow.ipynb` in Jupyter and run cells top to bottom.
Each agent has a cumulative inspect cell showing every field added by
every prior agent — useful for understanding data flow, not just output.

```
Agent 1 — Run + inspect (velocity, engagement, category, source domain)
Agent 2 — Run + inspect (+ content chars, background chars, bg status)
Agent 3 — Run + inspect (+ credibility_score, regime, weights, verified_by)
Agent 4 — Run + inspect (+ editorial_score, selected, selection_rank)
Agent 5 — Run + inspect (full script, word count, sections)
```

**Skip re-running Agents 1-3** if you already have a good cached run —
see [Cache & Checkpoint Reference](#-cache--checkpoint-reference) below.

### Expected Output (Agents 1-5, full run)

```
Stories fetched: 8
  80.1 vel | how-to-build-a-minimal-zfs-nas-without-synology...
  69.4 vel | is-the-economist-always-wrong
  ...

── CREDIBILITY RESULTS ──────────────────────────────
+0.54 ✅ KEEP [neutral]      | How to Build a Minimal ZFS NAS...
+0.69 ✅ KEEP [confirmation] | Local, CPU-Friendly TTS with Kokoro
──────────────────────────────────────────────────────

======================================================================
AGENT 4: Editorial
======================================================================
  [select] #1 ✅ score=0.676 | How to Build a Minimal ZFS NAS...
  [select] #2 ✅ score=0.672 | Local, CPU-Friendly TTS with Kokoro
  [select] #3 ✅ score=0.621 | Tenda firmware hidden backdoor
  [route] → script_writer (Agent 5)

======================================================================
AGENT 5: Script Writer
======================================================================
HOOK: You can build a crash-proof home server for under $500 — no Synology needed
S1_CONTEXT: Using Debian 12 and OpenZFS...
...
CTA: Follow for daily tech news
── STATS ──────────────────────────────────────────────
Words: 196   Duration: ~78s   Sections: 10   Attempts: 1
```

### 🗂️ Cache & Checkpoint Reference

Two separate utilities manage state persistence — don't confuse them:

| Utility | Saves | Use to reload for... |
|---|---|---|
| `story_cache.py` | `stories` dict only (A1+A2+A3 fields) | Testing Agent 4 or 5 |
| `pipeline_cache.py` | Full state — `stories` + `script` | Testing Agent 6 onwards |

```python
# Skip A1-A3 — jump straight to Agent 4/5
from agent_tools.story_cache import load_stories
stories = load_stories()
call4 = editorial_node({"stories": stories})

# Skip A1-A5 — jump straight to Agent 6
from agent_tools.pipeline_cache import load_checkpoint
state = load_checkpoint("till-agent5")
call6 = script_qc_node(state)
```

---

## 🗺️ Development Roadmap

### Phase 1 — Foundations ✅
- [x] LangGraph StateGraph, nodes, conditional edges
- [x] Shared NewsroomState TypedDict
- [x] HackerNews trend fetching with velocity scoring

### Phase 2 — Context Researcher (Agent 2) ✅
- [x] 3-tier content fetching (trafilatura → Jina → Tavily)
- [x] Junk content detection (looks_like_real_content)
- [x] DDG news background search
- [x] Wikipedia keyword extraction (phi3.5)
- [x] Content-anchored background synthesis
- [x] Intent-based synthesis routing (compound vs 8B)
- [x] Context bleed prevention (keep_alive=0)

### Phase 3 — Fact Checker (Agent 3) ✅
- [x] 35-domain SOURCE_TIERS map (HN-tuned, 0.0 to +0.95)
- [x] REAL/OPINION/SPAM classification (Groq gpt-oss-120b)
- [x] -1 to +1 credibility range (zero = natural discard boundary)
- [x] Cross-verification: Exa semantic search → DDG fallback
- [x] Dynamic reweighting on contradiction/confirmation
- [x] Quota isolation: 120b / 20b / compound-mini separate pools
- [x] Soft discard marking (audit trail, not deletion)
- [x] Defensive guards (empty, thin, crash → 0.0 neutral)

### Phase 4 — Editorial Agent ✅
- [x] Composite score: credibility×0.50 + velocity_norm×0.30 + bg_norm×0.20 (addition, not multiplication)
- [x] Pick top 3 with topic diversity (qwen2.5:7b deduplication)
- [x] Soft-exclude thin-background stories via bg_norm penalty (KNOWN_ISSUES ISSUE-1)
- [x] Conditional edge (LangGraph): ≥1 story → Agent 5, 0 stories → end + macOS notification
- [x] Two-layer JSON cleaning for local-model dedup output (KNOWN_ISSUES ISSUE-9)

### Phase 5 — Script Writer ✅
- [x] HOOK → CONTEXT → CORE → TWIST → CTA structure (10 labelled sections, 3 stories)
- [x] 150-225 words for 60-90 sec video, word-count enforcement (trim/expand, max 2 attempts)
- [x] Groq llama-3.3-70b-versatile (separate quota from Agent 3's gpt-oss-120b)
- [x] Tone calibration driven by Agent 3's credibility_score
- [x] Iteratively hardened prompt: HOOK specificity, TWIST-not-restating-CORE,
      story-order enforcement, banned AI-tell phrases (KNOWN_ISSUES ISSUE-10, ISSUE-11)

### Phase 6 — Script QC 🔨 Next
- [ ] APPROVE/REVISE loop, max 2 iterations
- [ ] Validate word count surgically per-section (not whole-script regeneration)
- [ ] Validate CTA is exactly one of the 3 allowed options
- [ ] Human-voice polish: rewrite remaining AI-tell phrases
- [ ] Date humanization ("August 23, 2024" → "last year") using real current date
- [ ] Pacing annotations: `[PAUSE]` `[BEAT]` `[EMPHASIS]`
- [ ] Expansion decision: approve up to ~300 words if content substance justifies it

### Phase 7-10 — Video Pipeline
- [ ] Video Prompt Agent (cinematic scene descriptions)
- [ ] Video Generator (MOCK ffmpeg → Fal.ai Wan 2.2)
- [ ] SEO Optimizer
- [ ] YouTube Publisher

---

## 🧠 Key Design Decisions

### Why HackerNews over Reddit/NewsAPI?

HackerNews has a public Firebase API with zero authentication, real-time engagement data, and a high-quality tech audience. The velocity score `(upvotes + comments×2) / age_hrs` naturally surfaces breaking stories without requiring API keys or rate-limit management.

### Why local models + cloud hybrid?

Local Ollama models (phi3.5, llama3.1:8b) handle the high-frequency, low-precision tasks (keyword extraction, synthesis from given material). Cloud models (Groq gpt-oss-120b) handle the low-frequency, high-precision tasks (credibility judgment requiring world knowledge). This minimizes API costs while maximizing quality where it matters.

### Why REAL/OPINION/SPAM instead of a decimal?

Small models (3B) cannot reliably produce consistent decimal credibility scores — they return 0.2 for factual articles and 0.8 for hype without discrimination. Classification into 3 categories is what 3B+ models actually do well. The decimal score is computed in code from the label, not by the model.

### Why soft discard (mark, not delete)?

A story marked `discarded=True` stays in the pipeline state as an audit trail. Agent 4 (Editorial) can see WHY it was discarded, future debugging can inspect it, and the threshold can be tuned without rerunning the pipeline.

### Why not CrewAI?

LangGraph gives explicit control over every state transition. For a learning project, understanding every line is the goal — abstractions hide the interesting parts.

### Why addition instead of multiplication for editorial_score?

Multiplication means one weak signal (e.g. a thin background) zeroes out
an otherwise excellent story. Addition treats each signal as an
independent contribution — missing background is a penalty (loses 20%
of the score), not an automatic disqualification. A viral, credible
story with no synthesized background can still make top 3, because
Agent 5 can script directly from `content` alone.

### Why separate story_cache.py and pipeline_cache.py instead of one file?

`story_cache.py` saves a flat `{story_id: {...}}` dict — that's all
Agent 1-3 produce. Agent 5 introduces `state["script"]`, a *top-level*
key sitting alongside `stories`, not inside it. Merging both into one
cache format would require restructuring the JSON on disk and updating
every existing load call — for a research/learning project, two small,
single-purpose files are safer than one file with two shapes.

---

## 📊 Known Limitations

See [KNOWN_ISSUES.md](./KNOWN_ISSUES.md) for all 11 documented limitations. Highlights:

- **ISSUE-1:** GitHub/arXiv/docs URLs — background frequency issue, largely mitigated by compound-mini web search
- **ISSUE-4:** llama3.1:8b context bleed between stories (fixed — `keep_alive=0`)
- **ISSUE-6:** gpt-oss-120b two failure modes — safety-filter empty response, and quota/network 403 mid-run (both fall back to 0.0 neutral, never crash)
- **ISSUE-7:** Quota isolation across 3 Groq model pools — confirmed via independent 429s
- **ISSUE-8:** False-positive risk when LLM says REAL but cross-verify contradicts (mitigated by dynamic reweighting, not eliminated)
- **ISSUE-9:** Local-model topic deduplication — JSON format issues (fixed, 2-layer cleaning) vs semantic clustering quality (phi3.5→qwen2.5:7b improved, not perfect)
- **ISSUE-10:** Script word-count overshoot on expand-correction (mitigated in Agent 5, definitive fix deferred to Agent 6)
- **ISSUE-11:** Script CTA drifting from the 3 allowed options (prompt-hardened in Agent 5, Agent 6 will validate + force regeneration)

---

## 🤝 Contributing

This project is actively being built as a learning exercise in production multi-agent systems. Contributions, suggestions, and issue reports are welcome.

---

## 📄 License

MIT License — see [LICENSE](./LICENSE) for details.

---

<div align="center">

Built with 🧠 by [Deepak Rathore](https://github.com/AlgoDr)

*From edge AI to autonomous AI newsrooms — one agent at a time.*

</div>