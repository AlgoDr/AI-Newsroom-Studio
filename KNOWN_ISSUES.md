# Known Issues — AI Newsroom Studio

Documented limitations as of the Agent 1 + 2 milestone. These are **expected
behaviors / accepted limitations**, not bugs. Recorded so future debugging
(Agents 3-10) doesn't mistake them for new failures.

---

## ISSUE-1: Some URL types yield no meaningful background

**Status:** Accepted limitation (not a bug)
**Affects:** Agent 2 (Context Researcher), downstream Agents 4 & 5

### Symptom
Certain story URLs produce an EMPTY background even though content fetched fine:
- **GitHub repos** (e.g. baidu/Unlimited-OCR) -> content is a README (code,
  install steps), not narrative news
- **arXiv papers** (e.g. VibeThinker) -> content is abstract + citation chrome
- **Docs pages** (e.g. unsloth GLM-5.2, Plotnine) -> API reference, not news
- **Show HN / project pages** -> often thin or code-heavy

### Root cause
Two independent reasons, both expected:
1. **DDG news returns 0 snippets** for brand-new repos/papers — there is no
   news coverage of a tool released hours ago. No snippets -> honest EMPTY.
2. When snippets DO exist but the content is reference/code, the
   content-anchored synthesizer correctly finds them off-topic and returns
   INSUFFICIENT DATA rather than fabricating a backstory.

This is the **honest-empty principle working as designed**: no background is
better than a wrong/hallucinated one.

### Observed examples (real runs)
```
Unlimited-OCR (GitHub)   -> DDG 0 snippets -> EMPTY   (correct)
VibeThinker (arXiv)      -> DDG 0 snippets -> EMPTY   (correct)
futo-swipe               -> DDG 0 snippets -> EMPTY   (correct)
vulnerability-reports    -> wiki present but off-topic -> EMPTY (correct)
raspberry-pi-pico-w      -> 37792-char content + 5 snippets -> EMPTY
                           (suspect: [:3500] cap landed on boilerplate,
                            OR snippets genuinely off-topic — UNCONFIRMED)
```

### Why this is NOT blocking
- For tool/repo/paper stories, the **article content itself carries the story**
  (what the tool does). A "backstory" often doesn't exist — the thing just
  launched.
- Background matters most for **news/events** (pricing announcements, company
  moves) where there's a real "how we got here." Those work well.

### Downstream impact & mitigation
- **Agent 4 (Editorial):** should rank stories WITH background higher than
  content-only stories when picking the top 3. Content-only stories are still
  usable, just lower priority.
- **Agent 5 (Script Writer):** scripts from content-only stories will be
  thinner. This is expected — do NOT debug Agent 5 for this; the cause is
  this documented upstream limitation.

### Possible future fixes (only if it becomes a real problem)
- GitHub README via GitHub API (structured, cleaner than scraped page)
- arXiv abstract via arXiv API (clean abstract, no citation chrome)
- Accept content-only for tool/repo stories (skip background entirely for them)
- Swap synthesis to gemini-2.0-flash (production): 1M context = feed full
  content, no [:3500] cap, better at extracting context from reference docs

---

## ISSUE-2: Wikipedia keyword extraction occasionally off-target

**Status:** Minor, accepted
**Affects:** Agent 2

### Symptom
extract_wiki_keyword (phi3.5) sometimes pulls a generic/wrong keyword, so
Wikipedia returns content that the synthesizer then rejects as off-topic
(e.g. vulnerability-reports run: wiki 1334 chars fetched but background EMPTY).

### Why not blocking
The content anchor catches it — wrong Wikipedia content gets filtered out
rather than poisoning the background. Worst case is a wasted fetch, not a
wrong output. DDG snippets + content still carry relevant stories.

### Possible future fix
Better keyword extraction model (qwen2.5:3b) or skip Wikipedia entirely if it
proves low-value across more runs.

---

## ISSUE-3: Local model (qwen2.5:3b) precision ceiling

**Status:** Accepted for dev; resolved in production
**Affects:** Agent 2 synthesis (and future LLM agents)

### Symptom
3B local model occasionally garbles specifics or is overly cautious
(returns EMPTY when a background was possible).

### Mitigation
- DEV: anti-invention prompt rule + content[:3500] cap keep it stable
- PRODUCTION: routing registry swaps synthesis to gemini-2.0-flash
  (one dict change) -> high precision + 1M context. The local model is a
  development/iteration tool, not the final synthesis engine.

---

## Summary for future sessions
If a downstream agent produces thin/empty results for a GitHub / arXiv / docs
story, **check this file first** — it's almost certainly ISSUE-1 (no
meaningful background available for that URL type), not a new bug in the
agent you're working on.
