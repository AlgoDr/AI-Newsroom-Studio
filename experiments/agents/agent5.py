"""
agent5.py — Script Writer Agent

Role: "Turn the top 3 selected stories into a 60-90 second YouTube Shorts script."

Responsibilities:
  1. _get_selected_stories()  — extract top 3 from Agent 4's output
  2. _tone_instruction()      — map credibility_score → tone string
  3. _build_prompt()          — assemble full LLM prompt with all 3 stories
  4. _parse_script()          — extract labelled sections from raw output
  5. _enforce_word_count()    — trim/expand if outside 150-225 word target
  6. script_writer_node()     — LangGraph node (orchestrates 1-5)

What Agent 5 does NOT do:
  - Does not re-fetch content (Agent 2 did that)
  - Does not re-score credibility (Agent 3 did that)
  - Does not pick stories (Agent 4 did that)
  - Does not check SEO (Agent 9 will do that)
  - Does not generate video (Agent 8 will do that)

New state key added:
  state["script"] = {
      "full_text":    str,   # complete script
      "word_count":   int,   # verified word count
      "est_duration": str,   # estimated speaking time e.g. "74s"
      "sections":     dict,  # parsed labelled sections
      "stories_used": list,  # selection ranks included [1, 2, 3]
      "attempt":      int,   # 1 or 2 (audit trail for word count enforcement)
  }

Model: llama-3.3-70b-versatile (Groq)
  - Strong creative writing — better than 8B for generation tasks
  - Separate quota from gpt-oss-120b (Agent 3) and gpt-oss-20b (Agent 2)
  - 1-2 calls per pipeline run maximum
"""

import os
import re
import dotenv
from groq import Groq

dotenv.load_dotenv(".env")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

MODEL       = "llama-3.3-70b-versatile"   # creative generation model
TARGET_MIN  = 150    # minimum words (60 sec at 2.5 words/sec)
TARGET_MAX  = 225    # maximum words (90 sec at 2.5 words/sec)
MAX_ATTEMPTS = 2     # max word count correction attempts before accepting

# ─────────────────────────────────────────────────────────────────────────────
# CLIENT — module level, instantiated once
# ─────────────────────────────────────────────────────────────────────────────

groq_client = Groq(api_key=os.getenv("GROQ_KEY"))


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 1 — _get_selected_stories
# ─────────────────────────────────────────────────────────────────────────────

def _get_selected_stories(stories: dict) -> list:
    """Extract Agent 4's selected stories, sorted by selection_rank.

    Only processes stories where selected=True.
    Sorts by selection_rank so rank 1 always leads the script.

    Returns list of story dicts, length 1-3.
    Returns empty list if Agent 4 selected nothing (pipeline should
    have exited via route_after_editorial — this is a safety net).
    """
    selected = [
        story for story in stories.values()
        if story.get("selected", False)
    ]
    selected.sort(key=lambda s: s.get("selection_rank", 99))

    print(f"  [script] {len(selected)} selected stories found")
    for s in selected:
        print(f"  [script]   #{s.get('selection_rank')} "
              f"ed={s.get('editorial_score', 0):.3f} | {s['title'][:55]}")

    return selected


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 2 — _tone_instruction
# ─────────────────────────────────────────────────────────────────────────────

def _tone_instruction(cred_score: float) -> str:
    """Map credibility_score to a tone instruction for the LLM.

    Agent 3 scored stories — we use that score to calibrate language:
      High cred  (>0.5): state facts confidently, use specific numbers
      Mid cred (0.15-0.5): attribute clearly, avoid overstatement
      Low cred   (<0.15): cautious framing, signal uncertainty to viewer

    The LLM reads this instruction and adjusts its language accordingly.
    We are NOT doing tone detection — we're injecting tone instructions
    based on a number we already have from Agent 3.
    """
    if cred_score > 0.5:
        return (
            "Write confidently. State facts directly. "
            "Use specific numbers, names, and dates from the content. "
            "Example: 'Rocket Lab just acquired Iridium for $8B'"
        )
    elif cred_score > 0.15:
        return (
            "Attribute claims clearly. Use phrases like "
            "'According to the report', 'The company says', "
            "'One developer argues'. Never state as absolute fact."
        )
    else:
        return (
            "Use cautious framing throughout. "
            "Use phrases like 'Reports suggest', 'Unconfirmed but', "
            "'If accurate, this means'. "
            "Signal to the viewer that this is emerging or unverified."
        )


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 3 — _build_prompt
# ─────────────────────────────────────────────────────────────────────────────

def _build_prompt(selected: list) -> str:
    """Build the complete LLM prompt for script generation.

    Sends ALL selected stories in ONE prompt — one model call total.
    Each story gets:
      - title (what it's about)
      - background[:300] (context paragraph from Agent 2)
      - content[:500]    (article text from Agent 2)
      - tone instruction (derived from Agent 3 credibility score)

    Word allocation by rank:
      Rank 1: ~75 words (most important story)
      Rank 2: ~60 words
      Rank 3: ~45 words (brief, leads to CTA)

    Section labels for parsing:
      HOOK        → opens the whole video (story 1's grabber)
      S1_CONTEXT  → background for story 1
      S1_CORE     → key facts for story 1
      S1_TWIST    → implication/surprise for story 1
      S2_HOOK     → transition + grabber for story 2
      S2_CORE     → key facts for story 2
      S2_TWIST    → implication for story 2
      S3_HOOK     → transition + grabber for story 3
      S3_CORE     → key facts for story 3
      CTA         → closes the whole video (one for all 3 stories)
    """
    story_blocks = []
    word_targets = [75, 60, 45]

    for i, story in enumerate(selected[:3]):
        rank    = i + 1
        target  = word_targets[i] if i < len(word_targets) else 40
        tone    = _tone_instruction(story.get("credibility_score", 0))
        title   = story.get("title", "")
        bg      = story.get("background", "")[:300]
        content = story.get("content",    "")[:500]

        block = f"""STORY {rank} (rank {rank}, ~{target} words):
  Title:      {title}
  Background: {bg}
  Content:    {content}
  Tone:       {tone}"""
        story_blocks.append(block)

    stories_text = "\n\n".join(story_blocks)

    # number of sections depends on how many stories were selected
    n = len(selected[:3])
    if n == 1:
        label_format = "HOOK:\nS1_CONTEXT:\nS1_CORE:\nS1_TWIST:\nCTA:"
    elif n == 2:
        label_format = "HOOK:\nS1_CONTEXT:\nS1_CORE:\nS1_TWIST:\nS2_HOOK:\nS2_CORE:\nS2_TWIST:\nCTA:"
    else:
        label_format = "HOOK:\nS1_CONTEXT:\nS1_CORE:\nS1_TWIST:\nS2_HOOK:\nS2_CORE:\nS2_TWIST:\nS3_HOOK:\nS3_CORE:\nCTA:"

    prompt = f"""Write ONE continuous YouTube Shorts script covering {n} tech news stories.
Total target: {TARGET_MIN}-{TARGET_MAX} words (60-90 seconds at spoken pace).

{stories_text}

USE EXACTLY THESE LABELS — one per line, content immediately after the colon:
{label_format}

RULES:
- HOOK must be punchy and under 15 words — grab attention immediately
- S2_HOOK and S3_HOOK must include a natural transition
  e.g. "Meanwhile...", "But that's not all...", "And finally..."
- Spoken English only: short sentences, active voice, contractions
  BAD: "Furthermore the implications are significant"
  GOOD: "And here's why this matters"
- Never invent facts not present in the Title, Background, or Content
- Follow the Tone instruction for each story exactly
- CTA must be exactly one of:
  "Follow for daily tech news" or "Comment below" or "Link in bio"
- Do not add any text outside the labelled sections
- Count your words — stay between {TARGET_MIN} and {TARGET_MAX} total"""

    return prompt


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 4 — _parse_script
# ─────────────────────────────────────────────────────────────────────────────

def _parse_script(raw: str) -> dict:
    """Extract labelled sections from raw LLM output.

    Model outputs:
      HOOK: This open source map app just made Google Maps look lazy.
      S1_CONTEXT: CoMaps is a free offline maps app...
      S1_CORE: Released last month with 2M downloads...
      ...

    Returns dict:
      {
        "HOOK":       "This open source map...",
        "S1_CONTEXT": "CoMaps is a free...",
        "S1_CORE":    "Released last month...",
        ...
      }

    Known labels:
      HOOK, S1_CONTEXT, S1_CORE, S1_TWIST,
      S2_HOOK, S2_CORE, S2_TWIST,
      S3_HOOK, S3_CORE, CTA
    """
    known_labels = [
        "HOOK",
        "S1_CONTEXT", "S1_CORE", "S1_TWIST",
        "S2_HOOK",    "S2_CORE", "S2_TWIST",
        "S3_HOOK",    "S3_CORE",
        "CTA",
    ]

    sections = {}
    pattern  = "|".join(re.escape(lbl) for lbl in known_labels)

    # split on label markers — handles single-line and multi-line content
    parts = re.split(rf"({pattern}):", raw)

    # parts alternates: [pre_text, LABEL, content, LABEL, content, ...]
    i = 1
    while i < len(parts) - 1:
        label   = parts[i].strip()
        content = parts[i + 1].strip()
        if label in known_labels:
            sections[label] = content
        i += 2

    found = list(sections.keys())
    print(f"  [script] parsed {len(found)} sections: {found}")
    return sections


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 5 — _enforce_word_count
# ─────────────────────────────────────────────────────────────────────────────

def _enforce_word_count(raw: str, attempt: int = 1) -> tuple:
    """Check word count and request trim/expand if needed.

    Returns: (final_text, word_count, attempts_used)

    Three outcomes:
      150-225 words → pass through, no second call
      > 225 words   → trim call → re-check → accept result
      < 150 words   → expand call → re-check → accept result

    Never blocks pipeline — if attempt 2 is still wrong, accepts
    and logs a warning. Agent 6 (QC) will review it.

    Uses the same model (llama-3.3-70b-versatile) for consistency.
    """
    word_count = len(raw.split())
    print(f"  [script] word count after attempt {attempt}: {word_count} words")

    if TARGET_MIN <= word_count <= TARGET_MAX:
        print(f"  [script] ✅ within target ({TARGET_MIN}-{TARGET_MAX})")
        return raw, word_count, attempt

    if attempt >= MAX_ATTEMPTS:
        print(f"  [script] ⚠️ still {word_count} words after {attempt} attempts "
              f"— accepting as-is (Agent 6 will review)")
        return raw, word_count, attempt

    if word_count > TARGET_MAX:
        correction_prompt = (
            f"Shorten this YouTube Shorts script to under {TARGET_MAX} words. "
            f"Keep ALL labelled sections (HOOK, S1_CONTEXT, etc). "
            f"Cut filler words and shorten sentences. "
            f"Do not remove any story or section label.\n\n{raw}"
        )
        print(f"  [script] {word_count} > {TARGET_MAX} → trimming...")
    else:
        correction_prompt = (
            f"Expand this YouTube Shorts script to at least {TARGET_MIN} words. "
            f"Keep ALL labelled sections. "
            f"Add one more specific detail to S1_CORE or S2_CORE.\n\n{raw}"
        )
        print(f"  [script] {word_count} < {TARGET_MIN} → expanding...")

    try:
        resp = groq_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": correction_prompt}],
            temperature=0.3,
            max_tokens=600,
        )
        corrected = resp.choices[0].message.content.strip()
        # recurse for one more check (attempt 2)
        return _enforce_word_count(corrected, attempt + 1)

    except Exception as e:
        print(f"  [script] word count correction failed ({e}) — accepting original")
        return raw, word_count, attempt


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 6 — script_writer_node (LangGraph node)
# ─────────────────────────────────────────────────────────────────────────────

def script_writer_node(state: dict) -> dict:
    """LangGraph node — orchestrates the full Agent 5 pipeline.

    Calls functions 1-5 in sequence:
      get_selected → build_prompt → LLM call → enforce_word_count → parse

    Adds state["script"] — first TOP-LEVEL key added to NewsroomState.
    (All previous agents enriched per-story inside state["stories"].)

    Returns updated state with script added at the top level.
    """
    stories = state["stories"]

    print("=" * 70)
    print("AGENT 5: Script Writer")
    print("=" * 70)

    # Step 1: get selected stories from Agent 4
    selected = _get_selected_stories(stories)

    if not selected:
        print("  [script] ❌ no selected stories — cannot generate script")
        state["script"] = {
            "full_text":    "",
            "word_count":   0,
            "est_duration": "0s",
            "sections":     {},
            "stories_used": [],
            "attempt":      0,
            "error":        "no selected stories from Agent 4",
        }
        return state

    # Step 2: build prompt
    prompt = _build_prompt(selected)
    print(f"  [script] prompt built ({len(prompt)} chars, "
          f"{len(selected)} stories)")

    # Step 3: call LLM — one call for all 3 stories
    try:
        resp = groq_client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a YouTube Shorts script writer for a daily tech news channel. "
                        "Write punchy, conversational scripts optimised for spoken delivery. "
                        "Always follow the labelled section format exactly as instructed."
                    )
                },
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            temperature=0.7,    # creative but not chaotic
            max_tokens=500,
        )
        raw = resp.choices[0].message.content.strip()
        print(f"  [script] LLM response: {len(raw)} chars, "
              f"~{len(raw.split())} words (before enforcement)")

    except Exception as e:
        print(f"  [script] LLM call failed: {e}")
        state["script"] = {
            "full_text":    "",
            "word_count":   0,
            "est_duration": "0s",
            "sections":     {},
            "stories_used": [],
            "attempt":      0,
            "error":        str(e),
        }
        return state

    # Step 4: enforce word count (trim/expand if needed)
    final_text, word_count, attempts = _enforce_word_count(raw, attempt=1)

    # Step 5: parse into labelled sections
    sections = _parse_script(final_text)

    # Step 6: estimate speaking duration (2.5 words/second)
    est_seconds = round(word_count / 2.5)
    est_duration = f"{est_seconds}s"

    # Step 7: assemble output
    state["script"] = {
        "full_text":    final_text,
        "word_count":   word_count,
        "est_duration": est_duration,
        "sections":     sections,
        "stories_used": [s.get("selection_rank") for s in selected],
        "attempt":      attempts,
    }

    print(f"\n  [script] ✅ script complete")
    print(f"  [script]    words:    {word_count}")
    print(f"  [script]    duration: ~{est_duration}")
    print(f"  [script]    sections: {len(sections)}")
    print(f"  [script]    attempts: {attempts}")
    print(f"  [script]    stories:  {state['script']['stories_used']}")

    return state