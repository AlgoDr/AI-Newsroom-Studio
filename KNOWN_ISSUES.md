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

**Status:** Resolved for dev (qwen2.5:3b → llama3.1:8b). Production swap to
gemini-2.0-flash was planned but never implemented — current dev model
(llama3.1:8b) has proven sufficient through Agent 2's full build.
**Affects:** Agent 2 synthesis

### Symptom
qwen2.5:3b (original synthesis model) garbled specifics and was overly cautious.
Replaced by llama3.1:8b + groq/compound-mini routing.

### Current state
- DEV: llama3.1:8b (good quality, no hallucination with anti-invention prompt,
  confirmed accurate across many real runs — Rocketlab, Supreme Court,
  CUDA kernel stories all produced specific, correct backgrounds)
- PRODUCTION: gemini-2.0-flash swap remains a documented option (one dict
  change in routing registry) but has not been needed — llama3.1:8b output
  quality has been sufficient throughout dev. Revisit only if dev quality
  degrades or production deployment requires larger context.

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

**Status:** Resolved — replaced by groq/compound-mini (see ISSUE-7)
**Affects:** Agent 2 synthesis (_synthesize_grokapi_cloud)

### Symptom
groq/compound returns HTTP 413 (Request Entity Too Large) regardless of
content cap (tried 2000, 1500, 1000, and ~100 char payloads — all 413
identically, confirming the issue is not payload-size-related).

### Root cause
`groq/compound` is a system internally powered by Llama 4 Scout + GPT-OSS
120B, supporting up to 10 tool calls per request. The heavier orchestration
appears to trigger the 413 regardless of input size on this account.

### Resolution
Replaced with `groq/compound-mini` (single tool call per request, ~3x lower
latency). compound-mini does not 413 and successfully performs web search
for 0-snippet stories. See ISSUE-7 for the full current chain and a newly
discovered quota-sharing caveat.

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

## ISSUE-7: Agent 2 big-boss model shares gpt-oss-120b quota with Agent 3

**Status:** Known limitation — working but not quota-isolated. Fix in progress
(local codebase already switched to gpt-oss-20b; UNTESTED for quality).
**Affects:** Agent 2 synthesis (_synthesize_grokapi_cloud), Agent 3 credibility

**Tag: `till-agent3-completed`**
**Commit: [`5d80690`](https://github.com/AlgoDr/AI-Newsroom-Studio/commit/5d80690)**
— last confirmed-working state with Agent 2 on gpt-oss-120b throughout.
Click the commit link above to view/restore that exact snapshot.

### Symptom
Both Agent 2's big-boss fallback and Agent 3's credibility check call
`openai/gpt-oss-120b`. If Agent 2 fires the big boss multiple times in one
run (several 0-snippet stories in a row), it can consume enough of the
shared 200K daily token pool that Agent 3 hits a 429 before scoring all
8 stories.

Observed: full pipeline run where Agent 2 fired big boss once (Wallace
telescope story), and Agent 3 subsequently 429'd on every single story —
all 8 fell back to 0.5 neutral instead of getting REAL/OPINION/SPAM scores.

### Root cause — confirmed via Groq documentation research
Two misunderstandings were corrected during investigation:

1. `groq/compound` (original choice, see ISSUE-5) is not a standalone
   model — it's a system internally powered by Llama 4 Scout + GPT-OSS
   120B, and reliably 413s on this account. Replaced by `compound-mini`.

2. `groq/compound-mini` was assumed to be a separate, smaller,
   quota-isolated model. This was WRONG. Per Groq's own docs: "Compound
   mini is powered by Llama 3.3 70B and GPT-OSS 120B... Rate limits for
   groq/compound-mini are determined by the rate limits of the individual
   models that comprise them." compound-mini draws from the SAME 200K
   gpt-oss-120b pool as the big-boss fallback and as Agent 3's
   credibility check. All three were never quota-isolated.

### Architecture at the tagged commit (5d80690 — WORKING, not quota-isolated)
```
Agent 2 synthesis (0-snippet stories):
  1. groq/compound-mini   — single search, uses Llama 3.3 70B + gpt-oss-120b
  2. openai/gpt-oss-120b  — explicit web_search_preview, Responses API
                            (fires only if compound-mini returns empty/fails)
  3. llama3.1:8b local    — final fallback, zero quota cost

Agent 3 credibility (all stories):
  openai/gpt-oss-120b     — REAL/OPINION/SPAM classification
```

### Why this was accepted at the time, not urgent
- Real runs showed 8/8 backgrounds AND working credibility scores most of
  the time — the conflict only manifests when MULTIPLE 0-snippet stories
  hit the big-boss path in the same run (uncommon: most HN stories have
  some DDG/Wikipedia coverage, so Agent 2 mostly routes to local 8B).
- When the conflict does occur, the failure mode is SAFE: Agent 3 falls
  to 0.5 neutral on every story (never discards incorrectly), pipeline
  completes without crashing.
- Daily quota resets at midnight UTC (5:30 AM IST) — a same-day re-run
  after reset recovers full functionality with no code changes needed.

### Fix in progress (local codebase, not yet pushed/verified)
Local agent2.py has been switched: Agent 2's big-boss model changed from
`openai/gpt-oss-120b` to `openai/gpt-oss-20b`, which Groq lists with its
own separate 200K daily token pool, independent from the 120B pool
Agent 3 uses.

**This fix is UNVERIFIED for output quality** — no side-by-side test has
been run comparing 20B vs 120B background-synthesis quality on Agent 2's
specific task. Before treating this as production-ready, run a same-story
comparison test:
  1. Feed an identical 0-snippet story to both `gpt-oss-20b` and
     `gpt-oss-120b` with `web_search_preview` enabled
  2. Compare specificity, factual accuracy, and length of output
  3. Only fully adopt 20B if quality holds up — do not assume it from
     parameter count alone

### What NOT to do
Do not assume compound-mini gives quota isolation "for free" — it does
not. Any fix must explicitly move Agent 2's synthesis path to a model
with a genuinely separate quota pool from `gpt-oss-120b`, verified via
Groq's rate-limit response headers (`x-ratelimit-remaining-tokens`), not
assumed from documentation alone.

### How to revert to the last known-good 120b-only state
```bash
# Restore just agent2.py to the tagged working version:
git checkout till-agent3-completed -- experiments/agents/agent2.py

# See what changed in agent2.py since that tag:
git diff till-agent3-completed..HEAD -- experiments/agents/agent2.py

# View the tagged commit directly on GitHub:
# https://github.com/AlgoDr/AI-Newsroom-Studio/commit/5d80690
```

---

## Summary for future sessions

```
Agent 4+ debugging: if stories are missing, check Agent 3 discard logic
  → only stories with content=0 should score <0.4 (ISSUE-6 for edge cases)

Agent 5 thin scripts: check if story has background or is content-only
  → content-only = ISSUE-1 (GitHub/arXiv), not a script-writer bug

Background quality issues: check synthesis routing print
  → "[synth] compound-mini failed" → big boss → 8B fallback = ISSUE-7 (normal)
  → "[synth] llama3.1:8b → N chars" = working correctly

Credibility all 0.50 across every story in a run: check for 429 errors
  → "Rate limit reached... tokens per day (TPD)" = ISSUE-7 quota conflict
  → wait for midnight UTC reset, or revert Agent 2 to `till-agent3-completed`

Credibility occasional 0.50 (1-2 stories, not all): check [cred DEBUG] raw=
  → raw='' for some = ISSUE-6 (safety filter, expected)
  → raw='REAL'/'OPINION' for others = working correctly
```