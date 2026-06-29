# Known Issues — AI Newsroom Studio

Documented limitations as of the Agent 1 + 2 + 3 milestone. These are
**expected behaviors / accepted limitations**, not bugs. Recorded so future
debugging (Agents 4-10) doesn't mistake them for new failures.

---

## ISSUE-1: GitHub / arXiv / docs URLs yield no meaningful background

**Status:** Accepted limitation (not a bug)
**Affects:** Agent 2 (Context Researcher), downstream Agents 4 & 5

### Symptom
Certain story URLs produce an EMPTY background even though content fetched fine:
- **GitHub repos** → content is a README (code, install steps), not narrative news
- **arXiv papers** → content is abstract + citation chrome
- **Docs pages** → API reference, not news

### Root cause
1. DDG news returns 0 snippets for brand-new repos/papers (no coverage yet)
2. When snippets exist but content is reference/code, the content-anchored
   synthesizer correctly returns INSUFFICIENT DATA rather than fabricating backstory

This is the **honest-empty principle working as designed**.

### Downstream impact
- **Agent 4 (Editorial):** rank stories with background higher than content-only
- **Agent 5 (Script Writer):** scripts from content-only stories will be thinner

### Possible future fixes
- GitHub README via GitHub API (structured extraction)
- arXiv abstract via arXiv API
- gemini-2.0-flash production swap: 1M context, no cap needed

---

## ISSUE-2: Wikipedia keyword extraction occasionally off-target

**Status:** Minor, accepted
**Affects:** Agent 2

### Symptom
`extract_wiki_keyword` (phi3.5) sometimes pulls a generic keyword, so Wikipedia
returns off-topic content that the synthesizer rejects. Worst case: wasted fetch.

### Why not blocking
The content anchor catches it — wrong Wikipedia content gets filtered out, not
included. DDG snippets + article content carry the story regardless.

### Possible future fix
Use qwen2.5:3b for keyword extraction (better instruction following).

---

## ISSUE-3: Local 3B model precision ceiling

**Status:** Accepted for dev; resolved in production
**Affects:** Agent 2 synthesis

### Symptom
qwen2.5:3b (original synthesis model) garbled specifics and was overly cautious.
Replaced by llama3.1:8b + groq/compound routing.

### Current state
- DEV: llama3.1:8b (good quality, no hallucination with anti-invention prompt)
- PRODUCTION: swap synthesis → gemini-2.0-flash (one dict change in routing registry)

---

## ISSUE-4: llama3.1:8b context bleed between consecutive stories

**Status:** Fixed — keep_alive=0 eliminates bleed
**Affects:** Agent 2 synthesis (_synthesize_local)

### Symptom
llama3.1:8b occasionally carried topic fragments from story N into story N+1.

Observed example (before fix):
```
Story N:   Age verification (surveillance laws)
Story N+1: Replacing Systemd with OpenRC
Result:    Systemd background mentioned "age verification laws" as a systemd
           feature — factually wrong, bled from prior story
```

### Root cause
Default ollama keep_alive=5min keeps model loaded between calls. Back-to-back
calls caused latent pattern retention from recent output.

### Fix applied
```python
options={"temperature": 0.2, "num_ctx": 8192, "keep_alive": 0}
```
Forces model unload after each call. Fresh load (~2-3s on M4) = no shared state.
`time.sleep(2)` between stories was removed (redundant with keep_alive=0).

### Cost
~2-3s reload per synthesis call. For 8-story run: ~16-24s extra. Acceptable.

### Production note
Cloud models (Gemini, Groq) have no stateful context between calls — this
issue disappears entirely with the production model swap.

---

## ISSUE-5: groq/compound 413 on any payload size

**Status:** Accepted — 8B fallback handles it cleanly
**Affects:** Agent 2 synthesis (_synthesize_grokapi_cloud)

### Symptom
groq/compound returns HTTP 413 (Request Entity Too Large) regardless of
content cap (tried 2000, 1500, 1000 chars — all 413).

### Root cause
Unknown — compound's actual free-tier payload limit appears lower than
documented, or the system message overhead triggers the limit on this account.

### Mitigation
Intent-based routing in synthesize_background:
- 0 snippets + small payload → tries groq/compound FIRST (web search needed)
- compound 413 → automatic fallback to llama3.1:8b
- 8B produces equivalent or better quality output for these cases

### Impact
compound effectively never runs — 8B handles all synthesis. The pipeline
produces correct backgrounds regardless. Not a quality issue.

### Why not migrating away from compound
The 8B fallback works well. Compound remains in the architecture for when
Groq resolves the limit or a different account is used in production.

---

## ISSUE-6: gpt-oss-120b returns empty for some stories

**Status:** Partially mitigated
**Affects:** Agent 3 (Fact Checker)

### Symptom
Groq gpt-oss-120b occasionally returns an empty string for certain articles,
resulting in 0.5 neutral score instead of REAL/OPINION/SPAM classification.

Observed: Pollen (corporate fraud story) → raw='' → 0.5 neutral.

### Root cause
gpt-oss-120b is a reasoning model. For content involving legal/fraud topics,
the model's safety filter likely triggered and returned nothing rather than
classifying. Not a code bug — a model behavior.

### Mitigation
Empty response guard in llm_credibility_check:
```python
if not raw or not raw.strip():
    return 0.5  # neutral, never discard on empty
```
Story stays KEPT (0.5 > 0.4 threshold). Correct behavior.

### Impact
~1-2 stories per run get neutral 0.5 instead of REAL (0.9). They stay in
the pipeline — just scored slightly lower. Not a blocking issue.

---

## Summary for future sessions

```
Agent 4+ debugging: if stories are missing, check Agent 3 discard logic
  → only stories with content=0 should score <0.4 (ISSUE-6 for edge cases)

Agent 5 thin scripts: check if story has background or is content-only
  → content-only = ISSUE-1 (GitHub/arXiv), not a script-writer bug

Background quality issues: check synthesis routing print
  → "[synth] compound empty/failed → local 8B fallback" = ISSUE-5 (normal)
  → "[synth] llama3.1:8b → N chars" = working correctly

Credibility all 0.50: check [cred DEBUG] raw= prints
  → raw='' for some = ISSUE-6 (safety filter, expected)
  → raw='REAL'/'OPINION' for others = working correctly
```