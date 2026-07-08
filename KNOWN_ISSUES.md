# Known Issues — AI Newsroom Studio

Documented limitations as of the Agent 1-5 milestone (12 issues total).
These are **expected behaviors / accepted limitations**, not bugs.
Recorded so future debugging (Agents 6-10) doesn't mistake them for new
failures.

**Issue index:** ISSUE-1,2 (Agent 2 background gathering) · ISSUE-3,4,5
(Agent 2 synthesis models) · ISSUE-6,7,8 (Agent 3 credibility) ·
ISSUE-9 (Agent 4 deduplication) · ISSUE-10,11 (Agent 5 script writer) ·
ISSUE-12 (voice-over — Kokoro/mlx-audio setup, pre-Agent 6.5)

---

## ISSUE-1: GitHub / arXiv / docs URLs yield no meaningful background

**Status:** Partially mitigated by compound-mini web search upgrade.
Frequency significantly reduced. Honest-empty still occurs for truly
new projects with zero web presence — correct behavior, not a bug.
**Affects:** Agent 2 (Context Researcher), downstream Agents 4 & 5

### Original symptom
Certain story URLs produced EMPTY backgrounds:
- **GitHub repos** → README is code/install steps, not narrative news
- **arXiv papers** → abstract + citation chrome, no news coverage
- **Docs pages** → API reference, not news

DDG returned 0 snippets for brand-new repos → synthesizer had nothing to work with.

### Current behavior after compound-mini upgrade
compound-mini has built-in web search and fires for 0-snippet stories.
It searches the web directly, bypassing the DDG gap entirely.

Real run evidence:
  GLM5.2 (github.com URL)     → 662-716 chars background ✅
  Jamesob SOTA LLMs (github)  → 645 chars background ✅
  SearXNG (github.com)        → 544 chars background ✅
  arXiv stories               → 630-770 chars background ✅

### When honest-empty still occurs
Brand-new repos/papers with zero web presence (published hours ago,
no coverage yet on any outlet). compound-mini finds nothing → correct
honest-empty. This is intended behavior, not a failure.

### Downstream impact (reduced)
- **Agent 4 (Editorial):** still rank verified backgrounds higher
- **Agent 5 (Script Writer):** very rare now to get content-only stories

### Remaining improvement path
- GitHub README via GitHub API (structured extraction for code repos)
- arXiv abstract via arXiv API (for papers with no news coverage yet)

---

## ISSUE-2: Wikipedia keyword extraction occasionally off-target

**Status:** Low impact, accepted. Impact further reduced by compound-mini upgrade.
**Affects:** Agent 2

### Symptom
`extract_wiki_keyword` (phi3.5) sometimes pulls a generic keyword, so Wikipedia
returns off-topic content that the synthesizer rejects. Worst case: one wasted
API call.

### Why not blocking (original reason, still valid)
The content anchor catches it — wrong Wikipedia content gets filtered out, not
included. DDG snippets + article content carry the story regardless.

### Why even less impactful now
The compound-mini upgrade made Wikipedia a bonus path, not a dependency.
Even if Wikipedia returns nothing useful, compound-mini independently
searches the web for 0-snippet stories and fills the gap. The pipeline
is no longer reliant on Wikipedia for background quality.

### Still technically present
phi3.5 is still used for keyword extraction. The occasional off-target
keyword still fires a wasted Wikipedia call. But the downstream quality
impact is negligible given the compound-mini safety net.

### Possible future fix
Use qwen2.5:3b or a better instruction-following model for keyword extraction.
Not urgent given current pipeline resilience.

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

**Status:** Quota isolation CONFIRMED in live runs. Three fully separate pools:
gpt-oss-20b (Agent 2 big-boss), gpt-oss-120b (Agent 3 credibility),
compound-mini (Agent 3 contradiction check). Each pool hit independent 429s.
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

### Current architecture (quota-isolated)
Three fully separate Groq quota pools:
  Agent 2 big-boss:      openai/gpt-oss-20b   (own 200K daily pool)
  Agent 3 credibility:   openai/gpt-oss-120b  (own 200K daily pool)
  Agent 3 contradiction: groq/compound-mini   (own TPM pool, 8K/min)

compound-mini TPM (per-minute) exhaustion fix: time.sleep(2) added
before _check_contradiction call. Prevents 429 on rapid consecutive calls.

20b quality for Agent 2 big-boss: still unverified vs 120b.
See ISSUE-7 TODO checklist — milestone_tracker.py auto-logs every
gpt-oss-20b firing; alert fires at 5 and 10 real calls.

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

---

## ISSUE-8: False positive risk when LLM says REAL but cross-verify contradicts

**Status:** Partially mitigated by dynamic reweighting. Known design gap.
**Affects:** Agent 3 check_credibility()

### Symptom
When gpt-oss-120b classifies content as REAL (+0.9) but a credible source
contradicts a specific fact, the LLM signal (60% weight) can dominate and
keep a story that should be discarded.

Example:
  Story: "Company X raises $500M" (unknown blog, number fabricated)
  cross_verify: Bloomberg says "$50M not $500M"
  Standard weights: 0.0x0.20 + 0.9x0.60 + -0.6x0.20 = +0.42 -> KEEP (wrong)

### Mitigation
Dynamic reweighting shifts weights when contradiction detected:
  llm: 0.60 -> 0.30 (reduced)
  verify: 0.20 -> 0.50 (amplified)
  Corrected: 0.0x0.20 + 0.9x0.30 + -0.6x0.50 = -0.03 -> DISCARD (correct)

### Remaining risk
Reweighting only fires if _check_contradiction() returns CONTRADICTS.
If compound-mini returns CONSISTENT or UNRELATED (false negative on the
contradiction), reweighting does not trigger and the false positive survives.

### Frequency on HN
Low — HN community pre-screens fabricated stories via downvotes.
Primary risk: plausible-sounding misinformation with slightly inflated
financial figures or misattributed technical claims.

### Future improvement
Run _check_contradiction twice (majority vote) for high-stakes stories.
Use result_trust as a confidence multiplier on the contradiction signal.

---


---

## ISSUE-9: phi3.5 deduplication returns malformed JSON (Agent 4)

**Status:** Partially fixed — two-layer JSON cleaning in place.
Whitespace compaction fix applied. Some edge cases may still occur.
**Affects:** Agent 4 deduplicate_topics()

### Symptom
phi3.5 returns valid topic clusters but in malformed JSON format.
Three observed variants across real runs:

  Variant A — titles alongside numbers (Run 1):
    [["1", "Fable turned reMarkable..."], ["2",]]
    int("Fable turned...") → ValueError

  Variant B — trailing commas (Run 2):
    [["1", "7"], ["2",], ["3",]]
    json.loads() → JSONDecodeError (trailing comma)

  Variant C — spaces in outer brackets (Run 3):
    [ [1,3], [2,5], [4], [6], [7], [8] ]
    find("[[") fails on "[ [" → ValueError: no JSON array found

### Root cause
phi3.5 (3.8B) was trained on human-written text, not JSON schema compliance.
When instructed "return ONLY integers", it tries to be helpful by:
  - adding title text alongside numbers (so the reader knows which story)
  - adding trailing commas (natural when listing items in human writing)
  - adding spaces inside brackets (looks more readable to humans)

This is not the model ignoring instructions — it is misunderstanding the task.
phi3.5 hears "group these titles" as "show me the groups WITH titles".
It does not understand that machine-readable integers only are required.

This is a fundamental alignment gap between what the prompt says and what
phi3.5 was trained to produce. The two-layer cleaning fix handles the
symptoms; the root cause is a model capability ceiling for strict JSON output.
llama3.1:8b follows JSON format instructions more reliably because it was
trained on significantly more code and structured-data examples.

### Fix applied (two-layer defense)
Layer 1 — before json.loads (cleans malformed syntax):
  raw_compact = re.sub(r',\s*]', ']', raw)   # trailing commas
  raw_compact = raw_compact.replace(" ","").replace("\n","").replace("\t","")
  # compaction: "[ [1,3] ]" → "[[1,3]]" fixes Variant C

Layer 2 — after json.loads (handles text mixed with numbers):
  for item in group:
      if isinstance(item, int): nums.append(item)
      else: m = re.match(r'\d+', str(item)); if m: nums.append(int(m.group()))
  # extracts integers from ["1","title text"] → [1]

### Safe fallback
If both layers fail → every story treated as its own cluster → no
deduplication → all stories eligible for selection. Pipeline never crashes.
Selection still correct (just no topic diversity enforcement that run).

### Remaining risk
Variant B (trailing commas) + Variant C (spaces) may still co-occur in
a single response that both layers can't fully clean. Low probability.

### Future improvement
Switch to llama3.1:8b for clustering (better JSON compliance) or use
compound-mini with explicit JSON schema enforcement.

---

## ISSUE-10: Agent 5 word count enforcement overshoots on expand (Script Writer)

**Status:** First-pass enforcement in Agent 5 (trim/expand, max 2 attempts).
Definitive word count validation delegated to Agent 6 (QC) — not yet built.
Agent 6 will enforce 150-225 surgically per section with targeted re-generation.
**Affects:** Agent 5 _enforce_word_count(), Agent 6 (planned)

### Symptom
First draft too short (105 words, target 150-225).
Expand correction prompt triggered.
Second draft severely overshot (387 words, ~155 seconds).

The expand prompt said "at least 150 words" with no upper limit.
llama-3.3-70b expanded aggressively, ignoring the implicit ceiling.

### Root cause
Expand correction prompt lacked an explicit upper bound:
  OLD: "Expand this script to at least 150 words"
  → model interpreted as "expand as much as possible"

### Fix applied
  NEW: "Expand to between 150 and 225 words. Target 170 words exactly.
        Add ONE specific detail to S1_CORE only. Do NOT add new sections."
Explicit ceiling + exact target + constrained section = tighter control.

### Why Agent 6 is the right fix, not Agent 5

Agent 5 self-correction is blind — it re-generates the whole script without
knowing which section caused the overrun. The result is unpredictable.

Agent 6 correction is surgical:
  - reads the script section by section
  - identifies exactly which section is too long (S1_CORE, S2_CORE etc.)
  - sends a targeted trim instruction for ONLY that section
  - re-checks word count after targeted re-generation
  - APPROVEs when 150-225 words confirmed

This is cleaner separation of concerns:
  Agent 5: GENERATE (focus on content quality and creativity)
  Agent 6: VALIDATE + CORRECT (focus on format, length, rules)

_enforce_word_count in Agent 5 is kept as a first-pass filter to catch
obvious overcorrection early and save quota. Agent 6 is the authoritative
validator.

### Word count formula
Target: 150-225 words = 60-90 seconds
Speaking pace: 2.5 words/second
est_duration = round(word_count / 2.5) seconds

---

## ISSUE-11: Agent 5 CTA not following allowed options (Script Writer)

**Status:** Prompt hardened in Agent 5 (WORD-FOR-WORD copy instruction).
CTA format validation is a primary Agent 6 responsibility — not yet built.
Agent 6 will reject any non-standard CTA and force exact regeneration.
**Affects:** Agent 5 _build_prompt(), Agent 6 (planned)

### Symptom
CTA generated as a custom 30+ word promotional paragraph:
  "Follow us for daily tech news and stay up-to-date on the latest
   developments in the world of technology. We'll keep you informed..."

Required: exactly one of three options:
  A: "Follow for daily tech news"
  B: "Comment below with your thoughts"
  C: "Link in bio for more"

### Root cause
Original prompt rule was too lenient:
  "CTA must be exactly one of: 'Follow for daily tech news' or..."
  → model treated this as a guideline and wrote a custom CTA instead

### Fix applied
Prompt now uses explicit copy instruction:
  "CTA must be WORD-FOR-WORD one of these three — do NOT modify:
   A: Follow for daily tech news
   B: Comment below with your thoughts
   C: Link in bio for more
   Copy one exactly. No custom CTAs."

### Why Agent 6 is the right fix

CTA validation is a FORMAT check, not a creativity check.
Agent 5 (generation) should focus on content quality.
Agent 6 (QC) is purpose-built for exactly this kind of rule enforcement:

Agent 6 CTA check:
  □ Is CTA exactly one of the three allowed options?
  □ NO → reject → send targeted instruction:
         "Replace CTA with exactly: Follow for daily tech news"
  □ Agent 5 regenerates ONLY the CTA line (not the full script)
  □ Agent 6 re-checks → APPROVE if correct

The prompt hardening in _build_prompt improves the first-draft hit rate.
Agent 6 guarantees correct CTA on every final output regardless of
what the first draft produced.

---

---

## ISSUE-12: Kokoro TTS via mlx-audio — dependency chain hidden behind one generic error

**Status:** Resolved. Documented here because a fresh machine or a reset venv
will hit the same wall, and `mlx-audio`'s error message doesn't reveal the
real cause.
**Affects:** Voice-over generation (planned Agent 6.5/7, not yet built)

### A nice bit of full-circle project history

This entry exists because of a story **Agent 1 (Trend Hunter) itself
surfaced** in a real pipeline run: *"Local, CPU-Friendly, High-Quality TTS
with Kokoro"* — velocity 44.9, later confirmed by Agent 3 via cross-verify
(github.com, trust=0.95) and selected by Agent 4 for scripting (editorial_score
0.672, rank #2). Agent 5 wrote a script about Kokoro without knowing the
project would end up using the exact model it was reporting on.

That's the newsroom finding its own tools — a genuinely fun validation
that the pipeline surfaces real, usable signal, not just noise.

### Symptom

```
python3 -m mlx_audio.tts.generate --model mlx-community/Kokoro-82M-bf16 \
  --text "..." --voice af_heart

Import error: Kokoro requires the optional 'misaki' package for text
processing. Install it with: pip install misaki
```

Running `pip install misaki` shows `Requirement already satisfied` —
yet the exact same error repeats. The message is misleading: `misaki`
IS installed, but one of *its* imports is failing, and `mlx_audio`
wraps every exception inside `misaki` with this one generic string.

### Root cause — a 4-layer dependency chain, each failure masked identically

```
mlx-audio
  └─ misaki (text → phoneme processing)
       ├─ num2words        (missing → ModuleNotFoundError, masked)
       └─ phonemizer       (missing → ModuleNotFoundError, masked)
            └─ espeak-ng   (system binary, NOT pip-installable, masked)
```

Every one of these three missing dependencies produced the *exact same*
top-level error message. Standard `pip install misaki` cannot reveal
which sub-dependency is actually missing — the traceback must be
unwrapped manually.

### How it was actually diagnosed

`mlx_audio`'s wrapped error hides the real `ModuleNotFoundError`. Bypass
the wrapper by importing the failing path directly and catching the
raw traceback:

```python
python3 -c "
try:
    from misaki import espeak
    print('espeak ok')
except Exception:
    import traceback; traceback.print_exc()
"
```

This is what surfaced `ModuleNotFoundError: No module named 'phonemizer'`
— the real error, three layers down from what `mlx_audio` printed.

### Fix — full install sequence (in dependency order)

```bash
pip install mlx-audio        # pulls mlx, mlx-metal (Apple GPU backend)
pip install misaki            # text/phoneme processing
pip install num2words         # number → word spelling ("123" → "one hundred...")
pip install phonemizer        # Python wrapper for espeak-ng
brew install espeak-ng        # system-level binary — NOT a pip package
```

`spacy` + `en_core_web_sm` are pulled and installed automatically on
first run — no manual step needed for those.

### Verification, one layer at a time

```bash
python3 -c "from misaki import en; print('en ok')"
python3 -c "from misaki import espeak; print('espeak ok')"
python3 -m mlx_audio.tts.generate --model mlx-community/Kokoro-82M-bf16 \
  --text "test" --voice af_heart
```

### Why MLX (not Docker) for Kokoro on Apple Silicon

Docker Desktop on macOS has **no GPU passthrough for Metal** — this is a
confirmed, unresolved Docker Desktop limitation as of mid-2026, true across
M1 through M5. The commonly-suggested `kokoro-fastapi-gpu` Docker image is
built for NVIDIA CUDA and cannot use Apple Silicon's GPU even if pulled.

`mlx-audio` bypasses Docker entirely and runs natively against Apple's
Metal API via the MLX framework — this is the only path to real GPU
acceleration for Kokoro on a Mac. Confirmed working on M4 Pro (10-core GPU):
clean generation, natural voice quality ("modern AI voice, like Siri"),
fast inference.

### Result

```
Model:   mlx-community/Kokoro-82M-bf16 (82M params, MLX-native port)
Voice:   af_heart (one of ~50 available voices)
Backend: Apple Metal via MLX — confirmed GPU-accelerated, not CPU fallback
Cost:    $0 — fully local, no API key, no quota, no network dependency
Output:  audio_000.wav — natural quality, fast generation
```

Free, local, GPU-accelerated, and already validated end-to-end. Candidate
default for the not-yet-built voice-over agent (Agent 6.5/7) once Agent 6
(Script QC) is complete.

## Summary for future sessions

```
Agent 4+ debugging: if stories are missing, check Agent 3 discard logic
  → only stories with content=0 should score <0.0 in new design (ISSUE-6 for edge cases)

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