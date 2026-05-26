# 🎙️ AI Newsroom Studio

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1.0-FF6B6B?style=for-the-badge)
![Gemini](https://img.shields.io/badge/Gemini_2.5_Flash-API-4285F4?style=for-the-badge&logo=google&logoColor=white)
![YouTube](https://img.shields.io/badge/YouTube_API-v3-FF0000?style=for-the-badge&logo=youtube&logoColor=white)
![Status](https://img.shields.io/badge/Status-In_Development-yellow?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

**A fully autonomous, multi-agent AI pipeline that researches trending news, fact-checks it, writes engaging scripts, generates short-form videos, and publishes them to YouTube — all without human intervention.**

[Overview](#-overview) • [Architecture](#-agent-architecture) • [Tech Stack](#-tech-stack) • [Roadmap](#-development-roadmap) • [Setup](#-getting-started) • [Contributing](#-contributing)

</div>

---

## 📌 Overview

AI Newsroom Studio is a production-grade multi-agent system inspired by how a real newsroom operates — except every role is played by a specialized AI agent. From trend discovery to YouTube upload, the entire pipeline runs autonomously on a daily schedule.

The system identifies the most buzzworthy topics of the day, verifies them against credible sources, selects the top stories editorially, writes a compelling narrative script with a host persona, generates a short-form video, and publishes it — all in one unattended pipeline run.

### Why This Project?

- **Real-world multi-agent orchestration** — not a toy demo
- **End-to-end automation** — zero manual steps from trend to published video
- **Production-grade engineering** — LangGraph state machines, SQLite persistence, APScheduler, error recovery at every node
- **Short-form first** — targets YouTube Shorts (60–90 sec) where algorithmic reach is highest

---

## 🏗️ Agent Architecture

The pipeline is a directed graph of **8 specialized agents**, each owning exactly one responsibility. State flows through every agent, accumulating context until the final video is published.

```
┌─────────────────────────────────────────────────────────────────┐
│                        DAILY PIPELINE RUN                       │
│                     (Triggered at 9:00 AM)                      │
└─────────────────────────┬───────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
  ┌──────────────┐ ┌──────────────┐      │
  │ TREND SCOUT  │ │    DEEP      │      │
  │   AGENT      │ │  RESEARCHER  │      │
  │              │ │    AGENT     │      │
  │ Today's buzz │ │ Past 7 days  │      │
  │ Reddit PRAW  │ │ NewsAPI.ai   │      │
  │ Google Trends│ │ Web Search   │      │
  │ Serper Search│ │ Serper Search│      │
  └──────┬───────┘ └──────┬───────┘      │
         └────────┬────────┘              │
                  ▼                       │
         ┌────────────────┐               │
         │  FACT-CHECKER  │               │
         │     AGENT      │               │
         │                │               │
         │ Source verify  │               │
         │ Credibility    │               │
         │ score (0–1)    │               │
         │ Flag/Discard   │               │
         └───────┬────────┘               │
    credibility  │  credibility           │
    score < 0.4  │  score ≥ 0.4           │
    ─────────────▼                        │
    [STORY DISCARDED]                     │
                 │ ◄────────────────────  │
                 ▼
         ┌────────────────┐
         │   EDITORIAL    │
         │     AGENT      │
         │                │
         │ Scores stories │
         │ Picks top 3    │
         │ Ensures topic  │
         │ diversity      │
         └───────┬────────┘
                 │
                 ▼
         ┌────────────────┐
         │ SCRIPT WRITER  │
         │     AGENT      │
         │                │
         │ Hook → Context │
         │ → Twist → CTA  │
         │ Host dialogue  │
         │ 150–200 words  │
         └───────┬────────┘
                 │
                 ▼
         ┌────────────────┐
         │  VIDEO PROMPT  │
         │     AGENT      │      ← You were RIGHT to call this out
         │                │         as a separate agent
         │ Script →       │
         │ Scene-by-scene │
         │ cinematic      │
         │ prompts        │
         └───────┬────────┘
                 │
                 ▼
         ┌────────────────┐
         │    VIDEO       │
         │  GENERATOR     │
         │     AGENT      │
         │                │
         │ HeyGen API     │
         │ moviepy stitch │
         │ Whisper caption│
         │ 1080×1920 MP4  │
         └───────┬────────┘
                 │
                 ▼
         ┌────────────────┐
         │   PUBLISHER    │
         │     AGENT      │
         │                │
         │ YouTube API v3 │
         │ Auto title/    │
         │ description/   │
         │ tags from      │
         │ script         │
         └────────────────┘
```

### Agent Responsibilities

| # | Agent | Input | Output | Key Tools |
|---|-------|-------|--------|-----------|
| 1 | **Trend Scout** | Today's date | `List[TrendItem]` with buzz scores | Reddit PRAW, pytrends, Serper |
| 2 | **Deep Researcher** | `List[TrendItem]` | `List[ResearchPacket]` (topic + 3 articles each) | NewsAPI.ai, Serper, web scraping |
| 3 | **Fact Checker** | `List[ResearchPacket]` | Same list + `credibility_score`, `verified_by`, `flag` | Source credibility map, Gemini LLM |
| 4 | **Editorial Agent** | Verified packets | `Top3Stories` with selection reasoning | Gemini LLM scoring |
| 5 | **Script Writer** | `Top3Stories` | Structured script with `[SCENE]`, `[HOST_LINE]`, `[B_ROLL]` tags | Gemini LLM |
| 6 | **Video Prompt Agent** | Script scenes | `List[VideoPrompt]` with camera, mood, duration | Gemini LLM |
| 7 | **Video Generator** | `List[VideoPrompt]` | Final `.mp4` (1080×1920, 60fps) | HeyGen API, moviepy, Whisper |
| 8 | **Publisher** | `.mp4` + script metadata | YouTube video URL | YouTube Data API v3 |

---

## 🛠️ Tech Stack

### Core Framework
| Library | Purpose | Why |
|---------|---------|-----|
| **LangGraph 1.0** | Multi-agent orchestration | Explicit state graph, conditional routing, production-stable since Oct 2025 |
| **Python 3.11+** | Runtime | Type hints, async support |
| **APScheduler** | Daily cron trigger | Lightweight, no infra needed |

### LLM & AI
| Tool | Purpose | Tier Used |
|------|---------|-----------|
| **Gemini 2.5 Flash** | All LLM calls (research, fact-check, script, prompts) | Free tier (250K TPM/day) |
| **OpenAI Whisper** | Auto-captions from script | Local, free |
| **HeyGen API** | AI avatar video + talking-head generation | Free (3/month for testing), paid for production |

### Data & News Sources
| Source | What it provides | API Cost |
|--------|-----------------|----------|
| **NewsAPI.ai** | 200K articles, past 30 days | Free tier (2000 searches) |
| **Reddit PRAW** | Today's top posts from r/worldnews, r/technology etc. | Free (OAuth, 100 req/min) |
| **pytrends** | Google Trends data (unofficial) | Free, no API key |
| **Serper.dev** | Google Search results as JSON | Free (2500 searches on signup) |

### Video Pipeline
| Tool | Purpose | Cost |
|------|---------|------|
| **HeyGen** | AI news anchor avatar generation | 3 free/month → $29/month |
| **moviepy** | Stitch clips, add music, export | Free, open source |
| **Whisper (local)** | Generate caption SRT from script | Free, runs locally |

### Storage & Persistence
| Tool | Purpose |
|------|---------|
| **SQLite + SQLAlchemy** | Pipeline run logs, story history, publish records |
| **Loguru** | Structured logging across all agents |

### Publishing
| Tool | Purpose | Cost |
|------|---------|------|
| **YouTube Data API v3** | Automated video upload with metadata | Free (10K quota units/day) |

---

## 📁 Project Structure

```
ai-newsroom-studio/
│
├── core/
│   ├── agents/
│   │   ├── trend_scout.py          # Agent 1 — Today's buzz
│   │   ├── deep_researcher.py      # Agent 2 — Past 7 days context
│   │   ├── fact_checker.py         # Agent 3 — Credibility scoring
│   │   ├── editorial.py            # Agent 4 — Story selection
│   │   ├── script_writer.py        # Agent 5 — Narrative script
│   │   ├── video_prompt.py         # Agent 6 — Cinematic prompts
│   │   ├── video_generator.py      # Agent 7 — Video generation + stitch
│   │   └── publisher.py            # Agent 8 — YouTube upload
│   │
│   ├── graph/
│   │   ├── state.py                # NewsroomState TypedDict
│   │   ├── pipeline.py             # LangGraph StateGraph wiring
│   │   └── edges.py                # Conditional edge logic
│   │
│   ├── tools/
│   │   ├── news_fetcher.py         # NewsAPI.ai + Reddit wrapper
│   │   ├── trend_fetcher.py        # pytrends + Serper wrapper
│   │   ├── source_credibility.py   # Trusted sources map
│   │   ├── video_stitcher.py       # moviepy utilities
│   │   └── youtube_uploader.py     # YouTube API v3 wrapper
│   │
│   └── db/
│       ├── models.py               # SQLAlchemy models
│       └── session.py              # DB session management
│
├── data/
│   ├── newsroom.db                 # SQLite — pipeline run history
│   └── outputs/                   # Generated videos (local)
│
├── prompts/
│   ├── fact_checker_prompt.txt
│   ├── script_writer_prompt.txt
│   └── video_prompt_agent.txt
│
├── scheduler/
│   └── cron.py                    # APScheduler — 9 AM daily trigger
│
├── dashboard/
│   └── app.py                     # Streamlit pipeline status dashboard
│
├── tests/
│   ├── test_trend_scout.py
│   ├── test_fact_checker.py
│   └── test_pipeline_e2e.py
│
├── scripts/
│   ├── run_pipeline.py            # Manual one-shot pipeline trigger
│   └── run_scheduler.py          # Start the daily scheduler
│
├── .env.example
├── requirements.txt
├── README.md
└── LICENSE
```

---

## 🗄️ Database Schema

```sql
-- Pipeline run log
CREATE TABLE pipeline_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT NOT NULL,
    status          TEXT,             -- running / completed / failed
    stories_found   INTEGER,
    stories_passed  INTEGER,
    video_url       TEXT,
    youtube_url     TEXT,
    duration_sec    REAL,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Individual stories processed
CREATE TABLE stories (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER REFERENCES pipeline_runs(id),
    title               TEXT,
    source_url          TEXT,
    category            TEXT,         -- tech / finance / world / gossip
    credibility_score   REAL,
    buzz_score          REAL,
    selected            INTEGER,      -- 0 or 1
    discard_reason      TEXT,
    date_found          TEXT
);

-- Published videos
CREATE TABLE published_videos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES pipeline_runs(id),
    youtube_url     TEXT,
    title           TEXT,
    description     TEXT,
    duration_sec    INTEGER,
    published_at    TEXT
);
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- A Google account (for YouTube Data API + Gemini API)
- Serper.dev account (2500 free searches)
- NewsAPI.ai account (free tier)
- Reddit Developer app credentials (free)
- HeyGen account (3 free videos/month)

### Installation

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/ai-newsroom-studio.git
cd ai-newsroom-studio

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy env template and fill in your keys
cp .env.example .env
```

### Environment Variables

```env
# LLM
GEMINI_API_KEY=your_gemini_api_key_here

# News Sources
NEWSAPI_AI_KEY=your_newsapi_ai_key_here
SERPER_API_KEY=your_serper_api_key_here
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=ai-newsroom-studio/1.0

# Video Generation
HEYGEN_API_KEY=your_heygen_api_key_here

# YouTube Publishing
YOUTUBE_CLIENT_SECRETS_FILE=client_secrets.json

# Pipeline Config
CREDIBILITY_THRESHOLD=0.4          # Stories below this are discarded
TOP_STORIES_COUNT=3                 # How many stories to include per video
TARGET_VIDEO_DURATION_SEC=90       # Target short-form video length
PIPELINE_SCHEDULE_HOUR=9           # Daily run hour (24h format)
PIPELINE_SCHEDULE_TIMEZONE=Asia/Kolkata

# DB
DATABASE_URL=sqlite:///data/newsroom.db
```

### Run the Pipeline (Manual)

```bash
# Single one-shot run
python scripts/run_pipeline.py

# Start daily scheduler (9 AM IST every day)
python scripts/run_scheduler.py

# Launch Streamlit dashboard
streamlit run dashboard/app.py
```

---

## 🗺️ Development Roadmap

### Phase 0 — Multi-Agent Foundations
- [ ] Understand LangGraph `StateGraph`, `nodes`, `edges`
- [ ] Build 2-node graph (joke → critic)
- [ ] Add conditional edges (loop back on failure)
- [ ] Build shared `NewsroomState` TypedDict
- [ ] Mini project: 3-agent chain (Writer → Reviewer → Publisher)

### Phase 1 — Trend Scout Agent
- [ ] NewsAPI.ai integration
- [ ] Reddit PRAW — r/worldnews, r/technology, r/finance
- [ ] pytrends — Google Trends today
- [ ] Serper.dev — trending search queries
- [ ] Merge + deduplicate by topic (embeddings)
- [ ] Wrap as LangGraph node

### Phase 2 — Deep Researcher Agent
- [ ] Given topic → Serper web search → scrape top 3 articles
- [ ] LLM summarization to structured ResearchPacket
- [ ] Past-7-days filter via NewsAPI `from` param
- [ ] Wrap as LangGraph node

### Phase 3 — Fact Checker Agent
- [ ] Build trusted source credibility map
- [ ] Cross-reference: claim in 2+ credible sources?
- [ ] LLM red-flag detection (extraordinary claims, single-source)
- [ ] Output: `credibility_score`, `verified_by`, `flag`
- [ ] Conditional edge: score < 0.4 → discard

### Phase 4 — Editorial Agent
- [ ] Composite score: `buzz × credibility × recency`
- [ ] Category diversity enforcement
- [ ] LLM final editorial call with reasoning
- [ ] Output: Top 3 stories with selection justification

### Phase 5 — Script Writer Agent
- [ ] Prompt engineer news anchor storyteller persona
- [ ] Structure: Hook (3s) → Context → Twist → CTA
- [ ] Host dialogue lines
- [ ] Structured output: `[SCENE]`, `[HOST_LINE]`, `[B_ROLL]` tags
- [ ] Validate: 150–200 words for 60–90 sec video

### Phase 6 — Video Prompt Agent
- [ ] Research Runway / HeyGen prompt structures
- [ ] Per `[SCENE]` → `{visual, camera_movement, mood, duration_sec}`
- [ ] News broadcast aesthetic: cinematic, 4K, dramatic lighting
- [ ] Separate host (avatar) vs B-roll prompts

### Phase 7 — Video Generator Agent
- [ ] HeyGen API integration (avatar/talking-head)
- [ ] Scene-by-scene generation → download clips
- [ ] moviepy: stitch clips in order
- [ ] Whisper: generate + burn captions
- [ ] Royalty-free background music layer
- [ ] Export: 1080×1920, YouTube Shorts spec

### Phase 8 — Publisher Agent
- [ ] YouTube Data API v3 OAuth2 setup
- [ ] Auto-generate title, description, tags from script
- [ ] Scheduled publish (not immediate)
- [ ] Handle quota limits gracefully

### Phase 9 — Full Orchestration
- [ ] Wire all 8 agents into single LangGraph pipeline
- [ ] Error handling at every node (fail-safe, not fail-hard)
- [ ] APScheduler — 9 AM IST daily cron
- [ ] SQLite logging for every run
- [ ] Streamlit dashboard for pipeline status

---

## 🔑 API Cost Reality Check

| API | Free Tier | Paid (if needed) |
|-----|-----------|-----------------|
| Gemini 2.5 Flash | 1000 req/day, 250K TPM — sufficient for dev | Pay-as-you-go |
| NewsAPI.ai | 2000 searches/month | ~$49/month |
| Reddit PRAW | 100 req/min OAuth — sufficient | N/A |
| pytrends | Fully free (unofficial) | N/A |
| Serper.dev | 2500 free on signup | $50/month |
| HeyGen | 3 videos/month | $29/month (Creator) |
| YouTube API | 10K quota units/day (~6 uploads) | N/A |
| moviepy + Whisper | Free forever (local) | N/A |

**Bottom line:** Phases 1–6 can be built and validated at ₹0. Only video generation (Phase 7+) requires spending once you move to daily production.

---

## 🧠 Key Design Decisions

### Why LangGraph over CrewAI?
LangGraph 1.0 (stable since October 2025) gives explicit control over every state transition — you see exactly what flows where and why. CrewAI abstracts this away, which is great for quick demos but bad for a learning project where understanding every line of code is the goal. LangGraph also uses ~3× fewer tokens than CrewAI on equivalent tasks, which matters on free tier limits.

### Why Short-Form (60–90 sec)?
YouTube Shorts have stronger algorithmic distribution for new channels. Short-form also reduces video generation API costs significantly and makes the full pipeline feasible on free tiers during development.

### Why a Separate Video Prompt Agent?
Script writers optimize for narrative flow and engagement. Video generation models optimize for visual descriptions, camera movements, and lighting. These are different skills and different output formats — merging them into one agent produces worse output at both tasks.

### Why Gemini 2.5 Flash?
Free tier is genuinely usable for this pipeline (1000 req/day), the model is strong enough for all agents, and it's already used in the broader project ecosystem.

---

## 📊 Output Example

Each daily pipeline run produces:

```
📰 Stories Researched:   12–15
✅ Stories Passed Fact-Check: 8–10
🏆 Stories Selected:     3
📝 Script Word Count:    ~180 words
🎬 Video Duration:       75–90 seconds
📱 Format:               YouTube Shorts (1080×1920)
🔗 Published to:         youtube.com/@YourChannel
```

---

## 🤝 Contributing

This project is actively being developed as a learning exercise in production multi-agent systems. Contributions, suggestions, and issue reports are welcome.

```bash
# Fork the repo, then:
git checkout -b feature/your-feature-name
git commit -m "feat: your feature description"
git push origin feature/your-feature-name
# Open a Pull Request
```

---

## 📚 Learning Resources

These are the resources this project was designed around:

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangGraph 1.0 Stable Release Notes](https://blog.langchain.dev/langgraph-v1/)
- [Gemini API Docs](https://ai.google.dev/gemini-api/docs)
- [HeyGen API Docs](https://docs.heygen.com/)
- [YouTube Data API v3](https://developers.google.com/youtube/v3)
- [Reddit PRAW Docs](https://praw.readthedocs.io/)
- [moviepy Docs](https://zulko.github.io/moviepy/)

---

## 📄 License

MIT License — see [LICENSE](./LICENSE) for details.

---

<div align="center">

Built with 🧠 and too much coffee by [Deepak Rathore](https://github.com/YOUR_USERNAME)

*From DRDO embedded systems to autonomous AI newsrooms — one agent at a time.*

</div>
