# Known Issues — AI Newsroom Studio

Documented limitations as of the Agent 1-8 milestone (24 issues total).
These are **expected behaviors / accepted limitations**, not bugs.
Recorded so future debugging (Agents 9-10) doesn't mistake them for new
failures.

**Issue index:** ISSUE-1,2 (Agent 2 background gathering) · ISSUE-3,4,5
(Agent 2 synthesis models) · ISSUE-6,7,8 (Agent 3 credibility) ·
ISSUE-9 (Agent 4 deduplication) · ISSUE-10,11 (Agent 5 script writer) ·
ISSUE-12 (voice-over — Kokoro/mlx-audio setup, pre-Agent 6.5) ·
ISSUE-13 (voice-over — Kokoro pacing/emphasis markup, pre-Agent 6.5) ·
ISSUE-14 (Agent 2 — citation artifacts in background text) ·
ISSUE-15 (Agents 3/4/5/6 — keep_alive silently rejected by Ollama 0.24.0+) ·
ISSUE-16 (Agent 6 — empty pipe-separated JUDGE reasons parsed as valid) ·
ISSUE-17 (Agent 6 — no finish_reason visibility on live JUDGE path) ·
ISSUE-18 (Agent 6 — final word count not re-validated after rewrites) ·
ISSUE-19 (Agent 6.1 — short final chunk silently dropped by mlx_audio,
CTA lost) · ISSUE-20 (Video pipeline — local Wan2.1 text-to-video not
viable on 16GB Apple Silicon; PIL-based approach adopted instead) ·
ISSUE-21 (Agent 8 — `_load_font()` silently used a size-ignoring
fallback font on macOS; fixed with real cross-platform font paths +
loud failure instead of silent degradation) · ISSUE-22 (Agent 7 —
`KeyError: 'selection_rank'` on any run with an Agent-3-discarded
story; fixed) · ISSUE-23 (Agent 6.1 — ISSUE-19 recurred, 2 chunks
dropped instead of 1, same short/late-chunk pattern; still open) ·
ISSUE-24 (Agent 8 — long lower-third titles silently lost text, fixed
via font auto-shrink; text/audio timing sync still open, needs real
beat_timestamps)

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

Note (see ISSUE-15): Agent 4 subsequently switched its clustering model
from phi3.5 to qwen2.5:7b after real testing (test_dedup_reliability.py,
N=5 runs, 100% consistent, correctly beat gpt-oss-120b on real data too).
The two-layer JSON cleaning above remains in place as defense-in-depth
regardless of which local model is primary.

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

Note (see ISSUE-18): even after Agent 6 was built, its OWN final rewrite
pass was found to be able to push word count back outside 150-225 without
detection — see ISSUE-18 for that follow-on gap and its fix.

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

Note: after real testing, the "3 fixed strings" constraint was loosened
to 3 CATEGORIES (A=follow/subscribe, B=comment/engage, C=discover/link)
with story-tailored wording allowed within each category — see agent6.py
CTA prompt section for the current exact rule. The letter-label prefix
("A: Follow...") was also removed from the prompt after gemma3:12b was
observed copying the literal "A:" prefix into its output during Agent 5
fallback testing.

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

---

## ISSUE-13: Kokoro/mlx-audio has no markup support for pauses or emphasis

**Status:** Confirmed via research + design decision made. Not a bug —
a documented model/library limitation that shapes how Agent 6 (Script QC)
must prepare text before sending it to Kokoro. Re-check this entry if a
future Kokoro/mlx-audio release adds native markup support — the
workaround below may become unnecessary.
**Affects:** Agent 6 (Script QC, planned) → voice-over agent (planned
Agent 6.5/7)

### The design question that surfaced this

Agent 6's pacing-annotation design initially assumed script text could
carry inline markers like:
```
"No patch exists. [PAUSE] Disable remote management. [EMPHASIS: right now]"
```
with the expectation that these markers would guide delivery when the
text is eventually converted to speech via Kokoro. This needed to be
verified before building Agent 6, since a false assumption here would
silently produce broken audio (Kokoro reading the bracket text aloud).

### Confirmed: Kokoro does NOT understand bracket/SSML-style tags

The base Kokoro model (what `mlx-audio` runs) has **no native SSML or
custom-tag support**. Any article claiming "Kokoro supports SSML" is
describing a third-party wrapper app (e.g. Kokoro Web, TTS.ai) that
pre-processes those tags into plain punctuation/pauses **before** calling
the underlying model — the model itself never sees the tags. `mlx-audio`
is a bare interface to the model with no such wrapper layer.

If `[PAUSE]` / `[BEAT]` / `[EMPHASIS: word]` were sent directly to Kokoro,
it would attempt to pronounce the bracket characters and label words
literally — broken, garbled audio.

### Confirmed: what DOES reliably control pacing

Punctuation is the only native pacing control:
```
comma (,)      → short pause
period (.)     → natural full stop, longer pause
ellipsis (...) → longest pause, dramatic beat
new sentence   → natural reset point (functions as a "beat" boundary)
```

### Confirmed: there is no reliable emphasis mechanism

No bold, no capitalization, no markup gives word-level stress in base
Kokoro. A dedicated community project, `Kokoro-TTS-Pause`, exists
specifically because *"most TTS ignores pauses or makes them
unpredictable"* — confirming that even fine pause control beyond basic
punctuation isn't native to the model; that project works by stitching
separately-generated audio clips together with inserted silence, as a
post-processing hack, not by the model interpreting markup.

The only way to make a word land with vocal stress in Kokoro is to
**restructure the sentence** so that word naturally falls at a stress
position (end of a short clause) — not to tag it.

### Design decision — two-output split, translation not tagging

```
state["script"]["annotated_text"]
  Human/audit-readable version, KEEPS [PAUSE]/[BEAT]/[EMPHASIS] markers.
  Never sent to Kokoro. Useful for: audit trail, future subtitle
  bolding, a human narrator reading from a script, debugging.

state["script"]["tts_ready_text"]
  What actually gets sent to Kokoro. Tags are TRANSLATED, not passed through:
    [PAUSE]           → "."
    [BEAT]             → "..." or a fresh short sentence
    [EMPHASIS: word]   → REMOVED. Instead, Agent 6's rewrite stage
                         (Stage 2, llama-3.3-70b-versatile) must have
                         already restructured the sentence so the key
                         word/phrase sits at a natural stress point.
```

### Example — emphasis via restructuring, not tagging

```
BEFORE (tagged, wrong — would break if sent to Kokoro):
  "Disable remote management on your Tenda router right now."
  with [EMPHASIS: right now]

REWRITE for natural stress (what Stage 2 actually produces):
  "Disable remote management on your Tenda router. Right now."

"Right now" as its own short sentence gets natural vocal weight from
Kokoro purely through sentence-boundary placement — no tag needed.
```

### Why this belongs in Agent 6, not the voice-over agent

Agent 6 already does semantic rewriting (human-voice polish, transition
quality, twist quality) via the two-stage judge/rewrite model. Baking
stress-aware restructuring into that same rewrite pass is free — the
model is already touching the sentence for other reasons. Splitting this
into a separate later step would mean re-processing already-approved
text, risking new errors in text that already passed QC.

### Future re-check trigger

If a future Kokoro release, or a future `mlx-audio` version, adds native
pause/emphasis markup support (SSML or otherwise), this workaround
becomes unnecessary — Agent 6 could then emit tagged text directly.
Check `mlx-audio` changelog / Kokoro model card before assuming this
is still required.

---

## ISSUE-14: Citation artifacts leak into Agent 2 background text

**Status:** Fixed.
**Affects:** Agent 2 (`fetch_trend_background`, big-boss `gpt-oss-20b` path)

### Symptom
Background text for stories that escalated all the way to the
`gpt-oss-20b + web_search` fallback tier contained raw citation
markers, e.g.:
```
"Ant is a lightweight JavaScript runtime built from scratch that ships
as a 9 MB binary...【2†L10-L12】. Its hand-written engine...【2†L13-L15】."
```
`【2†L10-L12】` is a document/line-range citation marker gpt-oss-20b's
`web_search_preview` tool emits internally — never meant to reach
end-user content.

### Root cause
Only observed on the big-boss (`gpt-oss-20b`) synthesis path, not on
`groq/compound-mini` or `llama3.1:8b` — those two don't emit this
citation format. `_clean_synthesis()` already strips `INSUFFICIENT
DATA` markers but had no logic for these citation brackets.

### Fix applied
```python
import re

def _strip_citation_artifacts(text: str) -> str:
    """Remove gpt-oss-20b web_search citation markers like 【2†L10-L12】
    before storing as background text."""
    return re.sub(r'【[^】]*】', '', text).strip()
```
Applied in `fetch_trend_background()`, after `synthesize_background()`
returns — this is the single wrapper all three synthesis paths funnel
through, so the fix catches artifacts regardless of which tier produced
the result, without needing to be duplicated per-path.

### Impact if unfixed
Background text feeds directly into Agent 5's script-generation prompt.
Citation brackets would appear as unexplained noise in the LLM's
context — at minimum confusing, at worst the model could echo the
literal bracket text into a script section.

### Verification
Cannot be tested from `till-agent4`/`till-agent5`/`till-agent6`
checkpoints — background text is already baked in by the time those
checkpoints exist. Requires a fresh Agent 1→2 run, watching for the
`"[synth] gpt-oss-20b + web_search"` log line and confirming no
`【...】` markers appear in that story's background.

---

## ISSUE-15: `keep_alive` silently rejected when passed inside `options{}` (Ollama 0.24.0+)

**Status:** Fixed across all four affected files.
**Affects:** Every local `ollama.generate()` call — `agent3.py`,
`agent4.py`, `agent5.py`, `agent6.py`

### Symptom
```
level=WARN source=types.go:992 msg="invalid option provided" option=keep_alive
```
Every local-fallback/local-primary `ollama.generate()` call across the
pipeline logged this warning. The call still completed successfully —
this is not a crash — but `keep_alive` was silently ignored, meaning
local models stayed loaded for Ollama's default 5-minute window instead
of unloading immediately after each call.

### Root cause
Ollama's server API changed between versions: `keep_alive` used to be
accepted as a key inside the `options={}` dict. As of the installed
version (0.24.0), the server rejects it there specifically — it must
be passed as its own top-level keyword argument to `ollama.generate()`.

### Why this mattered beyond just the warning noise
`keep_alive=0` was originally added (see ISSUE-4) specifically to
prevent context bleed between consecutive local-model calls on the
same story batch. With it silently ignored, that protection may not
have actually been applying during recent runs, even though the code
looked correct at a glance.

### Fix applied (all four files)
```python
# WRONG (previous pattern, everywhere):
resp = ollama.generate(
    model=model, prompt=prompt, stream=False,
    options={"temperature": 0.1, "num_ctx": 4096, "keep_alive": 0},
)

# CORRECT:
resp = ollama.generate(
    model=model, prompt=prompt, stream=False,
    keep_alive=0,
    options={"temperature": 0.1, "num_ctx": 4096},
)
```
Applied to: `agent3.py::_llm_credibility_check_local`,
`agent4.py`'s dedup call, `agent5.py::_generate_script_local`,
`agent6.py::_judge_script_local` and `_rewrite_flagged_local`.

### Verification
Confirmed fixed — subsequent real runs no longer show the
`"invalid option provided"` warning for any of the four call sites.

---

## ISSUE-16: Agent 6 JUDGE — empty pipe-separated reasons parsed as valid blank reasons

**Status:** Fixed.
**Affects:** Agent 6 `_parse_judgment()`

### Symptom
When the JUDGE model (cloud or local fallback) returned
`FLAGGED_REASONS: |` (a bare pipe, no actual reason text), the parser
treated the resulting empty strings as legitimate reasons rather than
falling back to a sensible default.

```python
reasons = [r.strip() for r in reasons_raw.split("|")] if reasons_raw else []
# "|".split("|") -> ['', '']  -- two EMPTY STRINGS, not zero items
```
Since `0 < len(['',''])` and `1 < len(['',''])`, both empty strings
passed the `i < len(reasons)` check and were used AS the reason for
the first two flagged sections, instead of defaulting to
`"flagged by QC judge"`.

### Real, demonstrated impact
This caused the REWRITE stage to receive a blank instruction for two
of three flagged sections. With no real guidance, the rewrite model
added filler phrasing instead of fixing the actual problem — e.g.
`"This runtime is super lightweight, which is really nice"` was
introduced where the original had no such filler, and
`"That's interesting, but have you considered..."` replaced a clean
transition with hedging language. Both are exactly the AI-voice/
hedging patterns Agent 6 exists to remove, not add — the bug made
output measurably worse in a real run, not just cosmetically odd.

### Fix applied
```python
# FIND:
reasons = [r.strip() for r in reasons_raw.split("|")] if reasons_raw else []

# REPLACE:
reasons = [r.strip() for r in reasons_raw.split("|") if r.strip()] if reasons_raw else []
```
Filters empty strings out before indexing, so `"|"` correctly produces
`[]` instead of `['','']`, and every flagged section properly falls
back to the default reason when the model gave none.

### Related, not yet separately fixed
A second failure mode was observed in the same run: the local fallback
model sometimes writes reasons in a `"LABEL| reason"` per-line format
instead of the single pipe-joined `FLAGGED_REASONS:` line the prompt
requests. Since `_parse_judgment` only reads lines containing `:`,
these alternate-format lines are silently skipped, losing real reasons
the model did provide (e.g. `"too technical and vague"`,
`"vague quality adjectives"`). Not yet fixed — documented here as a
known remaining gap. A future fix could additionally scan for
`"LABEL| reason"` patterns as a secondary parse path.

---

## ISSUE-17: Agent 6 JUDGE — no `finish_reason` visibility on the live path

**Status:** Fixed.
**Affects:** Agent 6 `_judge_script()`

### Symptom
`finish_reason` logging (which revealed, during earlier testing, that
gpt-oss-120b can burn its entire `max_tokens` budget on internal
reasoning before ever emitting content — see ISSUE-6's root-cause
discussion) had only ever been added to throwaway test scripts, never
to the actual production `_judge_script()` function. When JUDGE went
empty on a real run, there was no way to tell whether it was
token-budget truncation, a genuine empty response, or something else.

### Fix applied
```python
# FIND:
raw = (resp.choices[0].message.content or "").strip()
except Exception as e:
    print(f"  [qc] JUDGE (gpt-oss-120b) call failed: {e}")

# REPLACE:
raw = (resp.choices[0].message.content or "").strip()
finish_reason = resp.choices[0].finish_reason
if not raw:
    print(f"  [qc] JUDGE empty content, finish_reason={finish_reason}")
except Exception as e:
    print(f"  [qc] JUDGE (gpt-oss-120b) call failed: {e}")
```
Any future empty-JUDGE event will now show `finish_reason` directly in
the live pipeline log, without needing a separate diagnostic script.

---

## ISSUE-18: Agent 6 — final word count not re-validated after last rewrite iteration

**Status:** Fixed.
**Affects:** Agent 6 `script_qc_node()`

### Symptom
A real script started at 202 words (within the 150-225 target).
Across 2 rewrite iterations — triggered by ISSUE-16's blank-reason bug,
which caused unnecessary/unfocused rewrites — the script drifted to
226 words, one word over `TARGET_MAX`. Nothing in `script_qc_node()`
re-checked word count after the final iteration completed, so the
script shipped as `approved: True` with no note that it had drifted
out of range.

### Fix applied
```python
# added immediately after: final_word_count = len(final_full_text.split())
if not (TARGET_MIN <= final_word_count <= TARGET_MAX):
    qc_notes.append(f"WARNING: final word count {final_word_count} outside "
                     f"target range {TARGET_MIN}-{TARGET_MAX} after rewrites")
    print(f"  [qc] WARNING: final word count {final_word_count} drifted outside target range")
```
Does not block the pipeline (matches the project's never-block
philosophy throughout) — just ensures any post-rewrite drift is
visible in `qc_notes` and the console log rather than silent.

---

## ISSUE-19: Agent 6.1 — short final chunk silently dropped by mlx_audio (CTA lost)

**Status:** Open, deferred — logged for future fix, not blocking pipeline.
**Affects:** Agent 6.1 `_generate_one_call()` / `_generate_audio()`

### Symptom
Real run on 2026-07-13 (`voiceover_20260713_084836.wav`, 201-word
script, 7 TTS-safe chunks): chunk 7/7 — the final chunk, only 8 words
(`"Check them out. Follow for daily tech news"`) — failed silently.
`mlx_audio` exited cleanly (returncode 0) but produced no
`audio_*.wav` file. The existing retry-with-extra-sanitization step
(Bug 3 fix, see module docstring) also produced no file. Per the
documented skip-not-abort design, the pipeline correctly continued and
stitched the remaining 6 chunks — but the shipped audio
(83.0s, `duration_verified: True`) is missing its final sentence and,
critically, **the entire CTA**. Every video this happens to ships
without a call-to-action, silently, since `duration_verified` only
sanity-checks total duration against word count and has no way to
know a specific sentence — especially the CTA — was the one dropped.

### Suspected cause (not yet confirmed)
The chunk that failed was short (8 words) relative to the ~30-40 word
chunks that succeeded in the same run. Bug 3's original fix targeted
Unicode/typographic characters (em-dashes, smart quotes, markdown
artifacts) tripping `espeak-ng`'s phonemizer — this chunk's text has
none of those, so the root cause is likely different: possibly
`mlx_audio`/Kokoro producing near-zero-length or empty output for
very short inputs, rather than a text-sanitization problem. Not yet
reproduced in isolation — needs a standalone test generating just an
8-word chunk repeatedly to confirm whether short length is the actual
trigger, or if this run was a one-off.

### Recurrence
This issue recurred on a second real run (2026-07-14) with a stronger
pattern: 2 chunks dropped instead of 1, both again short and at/near
the end of the script. See
[ISSUE-23](#issue-23-agent-61-chunk-drop-issue-19-recurred-dropping-2-chunks-instead-of-1)
for the full second occurrence and what it adds to the evidence here.

### Why deferred rather than fixed now
Agent 7/8 (video assembly) were prioritized and are now complete --
see their sections in [AGENTS.md](docs/AGENTS.md). This audio-stage
issue remains open and deferred, not because of competing priorities
anymore, but because it hasn't yet been revisited with dedicated
attention. This is a real, user-facing bug (silent CTA loss on every
affected run, now confirmed on 2 of 2 runs where a short chunk landed
near the script's end) and should be fixed before the pipeline is
trusted for daily unattended publishing.

### Candidate fixes to evaluate later
1. Detect a failed chunk that's disproportionately short (e.g. <15
   words) and merge its text into the previous chunk before retrying,
   rather than retrying it alone — avoids ever asking Kokoro to
   generate from a very short isolated string.
2. Add a specific alert/log line when the **last** chunk in a script
   is skipped, since losing the CTA is a materially worse outcome than
   losing an arbitrary mid-script chunk — current logging treats all
   skipped chunks identically.
3. Verify final `tts_ready_text` coverage post-stitch: compare the
   word count of chunks that actually produced audio against the
   original `tts_ready_text` word count, and surface a clear
   "X words missing from final audio, including CTA: <text>" warning
   distinct from the current generic `chunks_skipped` count.

---

## ISSUE-20: Agent 7/8 -- AI video/avatar generation evaluated and deferred (research log, not a bug)

**Status:** Resolved -- decision made, documented so it isn't re-investigated from scratch later. Agent 7 and Agent 8 (`reactive` mode) are now fully implemented and tested using the decision documented here.
**Affects:** Agent 7/8 design (video assembly stage)

### Context
While scoping Agent 7/8, considered building an AI-generated "host" or
presenter (talking avatar, lip-synced to the existing `af_heart` Kokoro
audio) rather than the originally-planned stock-footage b-roll
approach. Spent real time (2026-07-13) researching whether this was
newly viable given how fast video-gen models have moved, given the
project's own hardware: **M4 Pro, 16GB unified memory, 10-core GPU.**
Findings below, so a future session doesn't repeat this research.

### Finding 1: no cloud provider offers genuinely free, automatable daily video generation
Checked Synthesia, HeyGen, Canva, and Google Veo 3/3.1 specifically,
since these keep appearing in "free AI video tools" roundups. All four
turned out to have a meaningful gap between what SEO-style blog posts
claim and what the providers' own docs/pricing pages say:
- **Synthesia:** free tier is 10 min of video **per month**, watermarked,
  no downloads without watermark, and **no API access on the free
  tier at all** (API requires a paid Creator plan, ~$64-89/mo). 10
  min/month is far short of a 1-2 videos/day cadence (~60+ min/month
  minimum).
- **HeyGen:** free web tier is 3 videos/month, 720p, watermarked.
  HeyGen removed free API credits entirely as of Feb 2026 -- API is
  pay-as-you-go from ~$1-5/minute. One real-world account of running
  daily automated generation on HeyGen's API reported reaching ~$800/month.
- **Canva:** avatar feature is a thin wrapper licensing D-ID/HeyGen
  under the hood -- same underlying cost economics apply at volume.
- **Google Veo 3/3.1:** Google's own pricing page lists the free tier
  for Veo video generation as **"Not available"** as of March 2026;
  paid API is $0.15-0.40/second. Sources claiming "50 free videos/day"
  were conflating Gemini's genuinely-free *text* model tier with Veo
  (video), or describing the Google AI Pro *consumer app* subscription
  (3 videos/day, $19.99/mo), not a free API.

**Conclusion:** every cloud path breaks the project's "$0 by design"
principle from the very first video. Ruled out for a daily-automated
pipeline, not just "too expensive to prefer."

### Finding 2: local generation on 16GB unified memory is a genuine capability gap, not just slow
Investigated `mlx-video` (native MLX ports of LTX-2 and Wan2.1/2.2) as
the one path that could stay free, since Kokoro TTS already runs
locally via `mlx-audio` on this same machine.
- **LTX-2.3 / Wan2.2 14B:** multiple independent sources put the
  realistic floor at 32GB+ unified memory, and even at 32GB one
  real-Mac tester called them "difficult to run comfortably." Not
  viable on this project's 16GB hardware -- not attempted.
- **Wan2.1-T2V-1.3B:** the one model small enough to plausibly fit.
  1.3B params, 4-bit quantized weights ≈ 800MB. Officially trained at
  480p (832×480) -- 720p output is explicitly documented by Wan as
  "less stable." Native output is 81 frames at 16fps (~5s per
  generation call), not a continuous 90s video -- a full video would
  need ~18 separate stitched generations, with no built-in mechanism
  for keeping a consistent character/face across separate calls (that
  needs LoRA fine-tuning, a separate project on top of this).
  **Official VRAM requirement: 8.19GB** -- this is the number that
  matters, not the 800MB weight size. The gap is activation memory:
  a diffusion video model holds its *entire* spatio-temporal latent
  tensor (all frames × height × width × channels) in memory
  simultaneously across every denoising step, unlike an LLM which only
  holds one token's hidden state at a time regardless of output length.
  This is why a 12B *language* model (e.g. gemma3:12b, runs fine on
  this machine at ~6-7GB via Ollama's Q4 quantization) is not a fair
  comparison to a 1.3B *video* model -- parameter count alone doesn't
  predict memory footprint across these two model types.
  All published VRAM figures are from CUDA/NVIDIA benchmarks; MLX/Apple
  Silicon overhead is not accounted for and could be materially higher.
- On Apple Silicon specifically, exceeding unified memory capacity
  tends to cause **swapping (severe slowdown), not a clean OOM crash**
  the way CUDA typically fails -- meaning a bad fit shows up as the
  whole system becoming unresponsive for an extended period, rather
  than a fast, clear error.

### Finding 3: download eventually succeeded; first generation attempt crashed on VAE decode
Downloading Wan2.1-T2V-1.3B (~17.6GB) via `hf download` stalled twice
at an identical 8.7GB (confirmed via `du -sh` checks 20-30s apart
showing zero byte growth), likely a network/ISP or HF-server-side
issue. A third attempt, unassisted, completed successfully at
12.7-66.2MB/s -- the stalls were transient, not a fundamental blocker.

Converted to MLX format cleanly (transformer: 825 tensors; T5 encoder:
242 tensors, required installing `torch` as a one-time loader
dependency for the original `.pth` weights, not a runtime dependency;
VAE: 194 tensors; then 4-bit quantization: 300 layers / 1426 tensors).

First generation attempt (480x480, 33 frames/~2s, 20 steps, default
`--tiling auto`):
- T5 text encoding: 124.8s
- Denoising: 484.2s (8.1 min) -- **completed successfully**, all 20 steps
- VAE decode: **crashed**
  ```
  RuntimeError: [metal::malloc] Attempting to allocate 11324620800 bytes
  which is greater than the maximum allowed buffer size of 9534832640 bytes.
  ```
  Root cause: VAE decode needs one *contiguous* ~10.5GB Metal buffer to
  materialize the full spatio-temporal video tensor from latents in a
  single operation. macOS's Metal API hard-caps any single allocation
  at ~8.9GB, independent of total system RAM -- this is an OS/GPU-driver
  ceiling, not a "not enough memory" condition. A Mac with 128GB RAM
  would hit the identical wall for the identical operation. Confirmed
  via `mlx-video`'s own DeepWiki troubleshooting docs and multiple
  independent GitHub issues across the wider Wan ecosystem (Wan2.1
  upstream, Wan2.2/diffusers, stable-diffusion.cpp/ggml) reporting the
  same VAE-decode-needs-one-giant-buffer problem back to at least
  February 2025 -- not specific to this project's setup or `mlx-video`.
- Memory monitor during this run: peak 13.37GB used, **peak swap
  22.25GB** (exceeding total physical RAM), average 7.40GB used.

### Finding 4: forcing explicit `--tiling aggressive` avoided the crash -- but exposed the real cost
`mlx-video`'s Wan generate script does expose `--tiling
{auto,none,default,aggressive,conservative,spatial,temporal}` --
tiling support exists. Its `auto` mode did not select an aggressive
enough tile size to avoid the crash above; forcing `aggressive`
explicitly did:
- Same 480x480/33-frame/20-step test, `--tiling aggressive`:
- Denoising: 461.4s (7.7 min, consistent with the first attempt)
- VAE decode: **succeeded**, `Tiling (aggressive): spatial=256px,
  temporal=32f` -- 65.9s, no crash
- Total: 643.4s (10.7 min) for 2 seconds of output video
- Memory monitor: peak 13.34GB used, **peak swap 20.29GB** -- still
  swapping over the entire physical RAM even in the successful run
- Real, sustained thermal load (fan audibly working hard for the
  duration) -- not just a memory number, a genuine hardware stress test

**Critically: the test prompt was a deliberately generic smoke-test**
("a simple animated news anchor icon, minimalist style, blue glow"),
not real story content -- written to check "does this run without
crashing," not to represent achievable output quality. The resulting
video was an abstract blue/white icon-like blob with no
anchor/face/scene quality whatsoever -- confirming the pipeline
*mechanically completes* end-to-end when tiling is forced, but saying
nothing about whether real-content prompts would produce genuinely
usable output.

### Decision
**Deferred, not abandoned -- but with a real cost baseline now
established rather than a guess.** Even in the successful, non-crashing
configuration: **~10.7 minutes and sustained heavy swap/thermal load
per 2-second clip**, on the smallest possible test case (lowest
resolution, fewest frames, shortest prompt). A real 60-90s video needs
several clips per story across 3 stories -- scaling this honestly
implies 30-60+ minutes of sustained heavy-swap, hot-running generation
per video, every day, before even attempting the separate unsolved
problem of keeping an "anchor" character visually consistent across
those separately-generated clips (no built-in mechanism for this in
Wan2.1 T2V; would need LoRA fine-tuning, its own project).

Proceeding instead with a lightweight, non-ML-model alternative for
Agent 7/8's visual layer: a pure PIL/numpy-rendered reactive graphic
(pulsing/glowing abstract "anchor" orb driven by the real audio's
amplitude envelope, plus ffmpeg-burned source-citation lower-thirds).
Already prototyped and tested against a real 83s pipeline audio file
(`voiceover_20260713_084836.wav`) -- renders in ~2 minutes total, pure
CPU, zero MPS/CUDA dependency, zero swap, zero thermal concern, and
directly reuses `docs/audio-demo.html`'s existing color/typography
tokens for visual consistency with the rest of the project.

Revisit Wan2.1 (or a future, better-suited model) later only if: (a) a
faster VAE-decode path emerges upstream (e.g. `mlx-video` improving
its default `auto` tiling heuristics, or a lower-memory decode
algorithm), and (b) there's appetite to also solve character
consistency across stitched clips. Until then, this is off the
Agent 7/8 critical path.

---

## ISSUE-21: Agent 8 `_load_font()` silently used a tiny fallback font on macOS -- requested size was ignored entirely

**Status:** Fixed. Confirmed via before/after pixel measurement, not just visual inspection.
**Affects:** Agent 8 (`_load_font()`, used by `_draw_source_lowerthird()` and `_draw_branding()`)

### Symptom
Lower-third title/source text and branding text rendered as tiny,
barely-legible text on the actual target machine (macOS, M4 Pro) despite
the font `size` parameter being repeatedly increased across several
iterations (38px -> 56px -> 72px -> 88px -> 130px) with **no visible
change at any step**. Each iteration was verified to render correctly
in the dev sandbox (Linux) before being handed off, yet every real
render on the actual Mac still showed unreadably small text, leading to
several rounds of "still too small" reports that looked like a tuning
problem but were actually a single silent failure repeating itself.

### Root cause
```python
def _load_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()
```
The only font path checked was Linux-specific
(`/usr/share/fonts/truetype/dejavu/...`). That path does not exist on
macOS, so `Path(c).exists()` was always `False` on the actual target
machine, and every call silently fell through to
`ImageFont.load_default()` -- PIL's built-in bitmap font, which **completely
ignores the `size` argument**. The requested size was never wrong; it
was never being used at all on macOS. This is why increasing the point
size repeatedly produced identical output: the number was discarded
before it could have any effect.

The dev sandbox used to test each iteration is Linux and genuinely has
the DejaVu path, so every test there passed silently, masking the bug
until it was checked against a real render from the actual Mac.

### Why this was hard to catch
- No exception was raised -- `ImageFont.load_default()` is a legitimate
  fallback path in PIL, not an error condition, so nothing crashed.
- Visual inspection of cropped preview images (zoomed into just the
  text region) made the tiny bitmap font *look* like a legitimate,
  if small, rendering choice rather than an obviously broken one.
- The bug is platform-specific and silent -- it can only be caught by
  either testing on the actual target OS, or by objectively measuring
  rendered output rather than eyeballing it.

### Fix
`_load_font()` now checks real macOS system font paths
(`/System/Library/Fonts/Supplemental/Arial*.ttf`,
`/System/Library/Fonts/Helvetica.ttc`, etc.) before Linux paths, and
**raises `RuntimeError` instead of silently falling back** if no real
scalable font is found anywhere on the candidate list -- a crashed
render with a clear error message is strictly better than a silently
wrong one. Each candidate is also sanity-checked after loading (measured
glyph height compared against the requested size) to catch a font that
loads "successfully" but doesn't actually scale, rather than trusting
`ImageFont.truetype()`'s return value blindly.

### How this was actually confirmed fixed (not just claimed)
Rendered the same frame before and after the fix, then measured actual
text pixel height programmatically (numpy: threshold for bright pixels
in the known lower-third region, measure contiguous band height) rather
than relying on visual inspection a second time:
- Before fix: tallest text band = **9px = 0.47% of frame height**
- After fix: tallest text band = **126px = 6.56% of frame height**,
  matching the requested 130px font size almost exactly

### Lesson for future agent/rendering work in this project
When a visual fix is "verified" only in a dev sandbox that may differ
from the real target machine (different OS, different fonts, different
GPU backend -- see ISSUE-20's MPS-vs-CUDA distinction for the same
category of issue), treat that verification as provisional until
confirmed against real output from the actual target hardware. Prefer
an objective, measurable check (pixel measurements, file sizes, output
duration -- see the Agent 8 notebook cell's sanity-check block) over
visual inspection alone, since visual inspection of a small crop or a
scaled-down preview can look "fine" even when the underlying value is
completely wrong.

---

## ISSUE-22: Agent 7 `build_shot_list()` crashed with `KeyError: 'selection_rank'` on any run with an Agent-3-discarded story

**Status:** Fixed.
**Affects:** Agent 7 (`build_shot_list()`)

### Symptom
A real second pipeline run (2026-07-14, Climate.gov / Apple
SpeechAnalyzer / Linux-0.11-in-Rust) crashed Agent 7 outright:
```
KeyError: 'selection_rank'
```
The first run that day (Beavis Ultrasound / Cyberpunk Comics / Tiny
Emulators) had worked fine with identical code.

### Root cause
`state["stories"]` holds **every** story seen that run (6-8 typically),
not just the 3 ultimately selected. The original code assumed every
story dict in `state["stories"]` had a `selection_rank` key:
```python
stories_by_rank = {s["selection_rank"]: s for s in state["stories"].values()}
```
This is false for a story that Agent 3 discarded (contradicted/low
credibility) -- a discarded story never reaches Agent 4's editorial
scoring step at all, so it has **no `selection_rank` key whatsoever**,
not `None`. Confirmed via a real checkpoint inspection: the discarded
story ("Building and Shipping Mac and iOS Apps Without Ever Opening
Xcode", contradicted per Agent 3's cross-verify) had a visibly shorter
key list than every selected/scored story, missing `editorial_score`,
`selection_rank`, `selection_reason`, and every other Agent 4+ field.

The first run that day happened not to have any Agent-3 discards in
its batch, so the missing-key case was never exercised -- this bug
existed from Agent 7's first version but wasn't triggered until a run
with a genuine discard occurred.

### Fix
```python
stories_by_rank = {
    s["selection_rank"]: s for s in all_stories
    if "selection_rank" in s and s.get("selection_rank") is not None
}
```
Now explicitly checks for key presence before access, rather than
assuming every story in `state["stories"]` was scored. Verified against
a reconstruction of the exact real checkpoint shape that crashed (7
stories, one missing the key entirely) -- no crash, correct 3-story
mapping.

### Lesson
`state["stories"]` is best understood as "every story this run ever
looked at, at any stage," not "the 3 selected stories" -- any code
touching it needs to filter explicitly, not assume uniform shape across
entries. This is the same category of assumption-not-checked bug as
ISSUE-18 (word_count not re-validated) -- worth grep'ing other
downstream code for similar unguarded key access into `state["stories"]`
before it surfaces the same way.

---

## ISSUE-23: Agent 6.1 chunk-drop (ISSUE-19) recurred, dropping 2 chunks instead of 1

**Status:** Open, same root cause as ISSUE-19, new supporting evidence.
**Affects:** Agent 6.1 (`voice_over_node`)

### Symptom
The 2026-07-14 Climate.gov/Apple/Linux run dropped **two** consecutive
chunks (chunks 8 and 9 of 9), not just the final one as in ISSUE-19's
original occurrence:
```
[voiceover] chunk 8: mlx_audio exited cleanly but produced no audio_*.wav file
[voiceover] chunk 8 text: 'The Linux 0.11 kernel has been rewritten in idiomatic Rust,
  allowing it to boot on emulated i386 hardware and run a full init shell
  coreutils stack.' (26 words)
[voiceover] chunk 9: mlx_audio exited cleanly but produced no audio_*.wav file
[voiceover] chunk 9 text: "This Rust rewrite preserves the original kernel's semantics
  while rethinking its expression, making it an interesting project for
  developers and researchers. Follow for daily tech news" (26 words)
```
Result: the shipped audio/video for this run is missing S3_CORE,
S3_TWIST, and the entire CTA -- ends abruptly right after the Linux
0.11 hook sentence. Decision made to accept this run as-is (see
conversation log) rather than block on re-generating, since the goal
was validating the full pipeline end-to-end, not a perfect sample.

### New evidence toward root cause
Both occurrences now share a specific pattern: the dropped chunk(s) are
**short (8 and 26 words respectively) and near the end of the script**.
This is now two independent data points, not one, supporting candidate
fix #1 already listed in ISSUE-19 ("detect a failed chunk that's
disproportionately short and merge its text into the previous chunk
before retrying"). Still not confirmed as the actual mechanism --
worth testing directly (generate several short, late-script chunks in
isolation) before committing to that fix, but the pattern is no longer
a single anecdote.

### Not yet done
No code change made for this issue yet -- still deferred per ISSUE-19's
original reasoning (project focus is Agent 7/8, not further hardening
Agent 6.1 in isolation). Logged here specifically to preserve the
second data point before it's forgotten, since it materially
strengthens the case for candidate fix #1 whenever this is revisited.

---

## ISSUE-24: Agent 8 lower-third text can visually overlap/desync from spoken content; long titles needed a follow-up fix

**Status:** Partially fixed (silent truncation resolved), timing-sync misalignment still open.
**Affects:** Agent 8 (`_draw_source_lowerthird()`, section-to-frame timing)

### Symptom 1 (fixed): long titles silently lost text
A real render (`"Climate.gov was destroyed. Open data saved it"` as the
lower-third title) needed 3 lines to fit at the fixed 92px font size,
but the code only rendered `title_lines[:2]` -- the third line ("data
saved it") was silently dropped with no error, no log, nothing to
indicate content was lost. Confirmed via screenshot and reproduced
exactly in a standalone render.

**Fix:** `_fit_title_to_two_lines()` now auto-shrinks the font (92px
down to a 56px floor, in 4px steps) until the title genuinely fits in
2 lines, instead of truncating at a fixed size. Verified three ways:
the exact broken title now renders at 60px with zero words dropped
(checked by diffing the word set of the original title against the
wrapped lines, not just visually); short titles ("Tiny Emulators")
are confirmed unaffected, still rendering at the full 92px; a
medium-length title shrinks modestly (72px) as expected. See
`AGENT8_VERSION = "v7-title-autofit-2026-07-14"`.

### Symptom 2 (open, not yet fixed): lower-third text doesn't reliably line up with what's being said at that moment
Observed directly by the project owner across multiple real renders:
the on-screen title/source for a section can appear noticeably before
or after the corresponding audio actually starts discussing that
story. This is a **known, expected consequence of the current timing
approximation**, not a new surprise -- Agent 7's per-section timing is
word-count-proportional against total `audio_duration`
(`start_share = start_words / total_words`), which assumes constant
speaking pace throughout the script. Real speech doesn't have constant
pace: pauses, emphasis, and natural rhythm variation mean a
word-count-proportional estimate will drift from the true audio
timing, more so for later sections (error accumulates) and more so
when TTS chunk boundaries don't line up with sentence/section
boundaries in the actual audio waveform.

**Root fix (not yet built):** this requires real per-section
timestamps (`beat_timestamps`), not a proportional estimate -- already
flagged as an open dependency from Agent 6.1 in both README's Phase
7-10 checklist and AGENTS.md's Agent 7 section, going back to before
Agent 7 was even implemented. This issue is the concrete, observed
consequence of not having built that yet, not a new root cause.
Options worth evaluating when this gets prioritized:
1. Modify Agent 6.1 to record each TTS chunk's actual rendered
   duration (Kokoro/mlx_audio should know this per-chunk) and map that
   back to section boundaries, rather than relying purely on word
   count.
2. A lighter-weight partial fix: extend the existing fade-in logic so
   the lower-third fades in more conservatively (later, with a longer
   fade) to reduce the visual jarring of a mistimed transition, without
   solving the underlying timing accuracy -- treats the symptom, not
   the cause, but may be a reasonable stop-gap given real
   `beat_timestamps` is a larger piece of work.

---

## Summary for future sessions

```
Agent 4+ debugging: if stories are missing, check Agent 3 discard logic
  → only stories with content=0 should score <0.0 in new design (ISSUE-6 for edge cases)

Agent 5 thin scripts: check if story has background or is content-only
  → content-only = ISSUE-1 (GitHub/arXiv), not a script-writer bug

Background quality issues: check synthesis routing print
  → "[synth] compound-mini failed" → big boss → 8B fallback = ISSUE-7 (normal)
  → "[synth] llama3.1:8b → N chars" = working correctly
  → citation brackets 【...】 in background = ISSUE-14, should be fixed now

Credibility all 0.50 across every story in a run: check for 429 errors
  → "Rate limit reached... tokens per day (TPD)" = ISSUE-7 quota conflict
  → wait for midnight UTC reset, or revert Agent 2 to `till-agent3-completed`

Credibility occasional 0.50 (1-2 stories, not all): check [cred DEBUG] raw=
  → raw='' for some = ISSUE-6 (safety filter, expected)
  → raw='REAL'/'OPINION' for others = working correctly

Any local ollama.generate() call showing "invalid option provided
option=keep_alive": this is ISSUE-15 — check the call actually has
keep_alive as a top-level kwarg, not nested inside options{}

Agent 6 rewrite producing blank/filler-heavy sections: check qc_notes
for empty reason strings — this is ISSUE-16, confirm the reasons-list
filter fix is present in _parse_judgment()

Agent 6 approved script with word count outside 150-225: check qc_notes
for the ISSUE-18 drift warning — this is expected visibility, not a
new bug, but worth investigating why 2 rewrite iterations pushed it
out of range (often traces back to ISSUE-16 if reasons were blank)

Agent 6.1 "chunks_skipped" > 0 in the final printout: check WHICH
chunk index was skipped, not just the count — if it's the LAST chunk,
the CTA (and possibly the closing sentence) is silently missing from
the shipped audio. This is ISSUE-19, currently open/deferred. Print
the skipped chunk's text (already logged) to see exactly what was lost
before deciding whether that sample is still usable as-is.

Considering an AI-generated host/avatar for Agent 7/8 instead of stock
footage: this was already researched AND real-hardware-tested in depth
— see ISSUE-20 before re-investigating. Short version: no cloud
provider offers genuinely free automatable video generation (checked
Synthesia, HeyGen, Canva, Veo — all either cap far below daily use or
have no free API at all). Local generation (Wan2.1 1.3B via
mlx-video) was fully tested end-to-end on this project's actual 16GB
M4 Pro: it *can* complete without crashing if `--tiling aggressive` is
forced explicitly (default `auto` tiling crashes on VAE decode), but
even the smallest possible test (480x480, 2s) took ~10.7 minutes with
peak swap over 20GB and sustained heavy thermal load. Not viable for
daily automated use. Current approach is a PIL/ffmpeg reactive-graphic
renderer instead — already built and tested, see docs/samples/ for
output.

Agent 8 text renders tiny/unreadable no matter how much you increase a
font size parameter: this is ISSUE-21 — check `_load_font()` is
actually finding a real scalable font on the current machine (it now
raises loudly if not, rather than silently falling back to a
size-ignoring bitmap font). If you see this again on a new machine/OS,
add that platform's real font path to the candidate list rather than
assuming the size number itself needs to change.

Agent 7 crashes with KeyError: 'selection_rank': this is ISSUE-22 —
happens on any run where Agent 3 discarded a story, since a discarded
story never reaches Agent 4's scoring and has no selection_rank key at
all (not None, genuinely absent). Fixed by filtering on key presence
before access; if you see a similar KeyError elsewhere touching
state["stories"], assume the same "not every story has every field"
shape rather than a fluke.

Agent 6.1 dropped 2 consecutive chunks (not just 1) near the end of a
script: this is ISSUE-23, the same root cause as ISSUE-19 with a
second, stronger data point — both occurrences were short, late-script
chunks. Still open/deferred; the pattern is worth acting on next time
Agent 6.1 gets real attention, not just re-logging a third occurrence.

Agent 8 lower-third title text doesn't match what's currently being
said, or a long title gets cut off: two separate things under
ISSUE-24. The cutoff (silent 3rd-line drop) is fixed — check
AGENT8_VERSION says v7-title-autofit or later. The timing mismatch is
NOT fixed — it's the expected result of Agent 7's word-count-
proportional timing estimate, not a new bug; the real fix is
per-section beat_timestamps, still an open dependency from Agent 6.1.
```