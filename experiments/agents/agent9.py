"""
Agent 9 -- SEO Optimizer

Role: turn everything upstream agents already know about the finished
video into the actual publish-ready YouTube metadata package -- title,
description, tags, category, thumbnail frame. Does NOT call the
YouTube API itself (Agent 10's job) -- pure text/selection logic,
state in, state out, same as every other agent in this pipeline.

Design decisions locked in before writing this file:
  Title       -- reuse Agent 5's HOOK verbatim (rule-based truncation
                 only, no new LLM call) -- HOOK is already written to
                 be front-loaded/attention-grabbing per Agent 5's own
                 rules, and reusing it guarantees the title never
                 promises something the video doesn't actually say.
  Description -- full script text + explicit per-story source
                 attribution (already tracked via shot_list's
                 source_domain) + hashtags.
  Tags        -- qwen2.5:7b per-story extraction with a rule-based
                 fallback, same injected-function pattern as Agent 7's
                 extract_section_query() -- tag relevance benefits from
                 light semantic understanding a pure keyword-match
                 would miss (e.g. "Kokoro TTS" / "text-to-speech" as
                 related tags for the same story).
  Category    -- fixed constant (Science & Technology). Not computed
                 per-video -- this channel's content doesn't vary
                 category story to story.
  Thumbnail   -- a specific frame selected from Agent 8's already-
                 rendered frames, not YouTube's auto-picked default.
                 REQUIRES Agent 8's frames_dir to still exist on disk
                 when this agent runs -- see thumbnail section below
                 for why this creates a real ordering dependency.

Real numbers this design is built against (verified via web search,
not assumed -- see conversation log):
  TITLE_HARD_MAX_CHARS  = 100   API upload REJECTS anything longer
  TITLE_SHORTS_VISIBLE  = 40    practical Shorts-feed truncation point
                                 (informational only -- HOOK is already
                                 front-loaded by Agent 5's own design,
                                 so no additional truncation logic
                                 needed here beyond the hard cap)
  TAGS_TOTAL_BUDGET     = 500   combined character budget across ALL
                                 tags, per YouTube's API -- accumulate
                                 and stop, not "N tags per story" blindly
  DESCRIPTION_ABOVE_FOLD = 157  chars visible before "show more" --
                                 most important line goes first
"""

import os
import re
from pathlib import Path

TITLE_HARD_MAX_CHARS = 100
TAGS_TOTAL_BUDGET = 500
CATEGORY_ID = "28"  # Science & Technology -- fixed, not computed per-video

CHANNEL_TAGLINE = "AI Newsroom Studio -- autonomous, zero human editing"


# ---------------------------------------------------------------------
# TITLE -- reuse Agent 5's HOOK, rule-based truncation only
# ---------------------------------------------------------------------

def _build_title(hook_text: str) -> str:
    """
    Reuses Agent 5's HOOK verbatim rather than generating a new title.
    HOOK is already written to name one specific fact and front-load
    the compelling part (Agent 5's own prompt rules), and it's already
    what the video actually opens with -- generating a SEPARATE title
    risks a mismatch between what's promised in the title and what's
    delivered in the video, a real trust problem, not just a style one.

    Only does rule-based cleanup + hard-cap truncation. Never an LLM
    call -- this is the same "deterministic tasks stay in Python"
    principle already applied to word-count checks and TTS-readiness
    scanning elsewhere in this project.
    """
    title = hook_text.strip()

    if len(title) <= TITLE_HARD_MAX_CHARS:
        return title

    # truncate at a word boundary, never mid-word, leave room for "..."
    truncated = title[:TITLE_HARD_MAX_CHARS - 3]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated.rstrip(",;: ") + "..."


# ---------------------------------------------------------------------
# DESCRIPTION -- full script + source attribution + hashtags
# ---------------------------------------------------------------------

def _build_description(script_full_text: str, shot_list: list[dict]) -> str:
    """
    Most important line goes FIRST -- only ~157 chars show above the
    "show more" fold, so front-load a real summary line rather than
    starting with boilerplate branding.

    Source attribution pulls source_domain directly from Agent 7's
    shot_list (already computed there via _extract_domain()) -- no
    re-fetching or re-deriving needed, just reusing what's already
    in state.
    """
    # dedupe stories by title, preserving first-seen order (HOOK/CTA
    # entries have story_title=None and should be skipped here)
    seen_titles = set()
    sources = []
    for shot in shot_list:
        title = shot.get("story_title")
        domain = shot.get("source_domain")
        if title and title not in seen_titles:
            seen_titles.add(title)
            sources.append((title, domain))

    summary_line = (
        f"{len(sources)} tech stories, researched and fact-checked by an "
        f"autonomous AI pipeline -- zero human editing."
    )

    source_lines = "\n".join(
        f"- {title}" + (f" (source: {domain})" if domain else "")
        for title, domain in sources
    )

    parts = [
        summary_line,
        "",
        "Sources:",
        source_lines,
        "",
        script_full_text.strip(),
        "",
        CHANNEL_TAGLINE,
        "",
        "#Shorts #TechNews #AI",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------
# TAGS -- qwen2.5:7b per-story extraction, rule-based fallback
# ---------------------------------------------------------------------

TAG_EXTRACTION_PROMPT = """You are picking 4-6 SEO tags for a YouTube video \
about this tech news story. Tags help viewers who search for RELATED \
terms find this video, so include both the literal topic AND closely \
related terms a viewer might search instead.

Rules:
- 4-6 tags, each 1-3 words
- Include the literal subject AND at least one related/broader term
  (e.g. story about "Kokoro TTS" -> also include "text to speech")
- No made-up terms, nothing not grounded in the actual story
- Reply with ONLY a comma-separated list, nothing else

Story: {story_title}
Content: {story_content}

Tags:"""


def _extract_tags_for_story(story: dict, ollama_generate_fn=None) -> tuple[list[str], bool]:
    """
    Returns (tags, used_fallback). ollama_generate_fn injected for
    testability, same pattern as Agent 7's extract_section_query() --
    pass e.g. `lambda prompt: ollama.generate(model="qwen2.5:7b",
    prompt=prompt)["response"]`.

    Fallback (no model wired up, or model output fails sanity checks):
    rule-based extraction pulling capitalized multi-word phrases and
    the story's own title words directly -- never returns an empty
    tag list, since SOME tags are always better than none for discovery.
    """
    title = story.get("title", "")
    content = story.get("content", "")[:500]

    def _rule_based_fallback() -> list[str]:
        # capitalized multi-word phrases (likely product/project names)
        phrases = re.findall(r'\b[A-Z][a-zA-Z0-9]*(?:\s+[A-Z][a-zA-Z0-9]*){0,2}\b', title)
        # individual significant words (>3 chars, not common stopwords)
        stopwords = {"the", "and", "for", "with", "this", "that", "from"}
        words = [w for w in re.findall(r'\b[a-zA-Z]{4,}\b', title.lower())
                 if w not in stopwords]
        tags = list(dict.fromkeys(phrases + words))[:5]  # dedupe, preserve order
        return tags if tags else ["technology", "tech news"]

    if ollama_generate_fn is None:
        return (_rule_based_fallback(), True)

    try:
        raw = ollama_generate_fn(
            TAG_EXTRACTION_PROMPT.format(story_title=title, story_content=content)
        )
        tags = [t.strip() for t in raw.strip().split(",") if t.strip()]
        # sanity checks -- reject obviously-bad extractions rather than
        # trust the model blindly, same discipline as Agent 7
        if not tags or len(tags) > 10:
            return (_rule_based_fallback(), True)
        if any(len(t) > 40 for t in tags):  # a "tag" that long is echoing the prompt
            return (_rule_based_fallback(), True)
        return (tags, False)
    except Exception:
        return (_rule_based_fallback(), True)


def _build_tags(stories_by_rank: dict, ollama_generate_fn=None) -> tuple[list[str], int]:
    """
    Aggregates tags across all stories, respecting YouTube's 500-char
    TOTAL budget across all tags combined -- stops adding tags once
    the budget would be exceeded, rather than generating a fixed count
    per story and truncating arbitrarily at the end.

    Returns (final_tag_list, fallback_count) for the caller to log.
    """
    all_tags = []
    fallback_count = 0
    seen = set()

    for rank in sorted(stories_by_rank.keys()):
        story = stories_by_rank[rank]
        tags, used_fallback = _extract_tags_for_story(story, ollama_generate_fn)
        if used_fallback:
            fallback_count += 1
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                all_tags.append(tag)

    # channel-level tags always included first (small, fixed cost)
    channel_tags = ["AI Newsroom Studio", "tech news", "shorts"]
    final_tags = []
    budget_used = 0
    for tag in channel_tags + all_tags:
        # +1 accounts for the comma YouTube's API uses to join tags
        cost = len(tag) + 1
        if budget_used + cost > TAGS_TOTAL_BUDGET:
            break
        final_tags.append(tag)
        budget_used += cost

    return final_tags, fallback_count


# ---------------------------------------------------------------------
# THUMBNAIL -- select a real frame from Agent 8's already-rendered output
# ---------------------------------------------------------------------

def _select_thumbnail_frame(frames_dir: str, fps: int = 30,
                              hook_duration_hint_s: float = 4.0) -> str | None:
    """
    Picks a frame from WITHIN the HOOK section's opening seconds, not
    a random or mid-video frame -- a thumbnail's job is to earn the
    click, and the HOOK is deliberately the most attention-grabbing
    part of the script by Agent 5's own design. Picks the LAST frame
    in that window rather than the first, since Agent 8's fade-in logic
    means frame 0 is still fading the lower-third in (see
    render_reactive_frame's `fade` calculation) -- a slightly later
    frame in the window is more visually "settled."

    REAL DEPENDENCY WARNING: this requires Agent 8's frames_dir
    (default "frames_agent8/") to still exist on disk when Agent 9
    runs. Agent 8's assemble_reactive_mode() does NOT delete this
    directory after muxing -- confirmed by reading its actual code,
    frames persist post-run. But if any future cleanup step is added
    to Agent 8 or a wrapper script, Agent 9 must run BEFORE that
    cleanup, or this function will find nothing and return None. This
    ordering dependency should be called out explicitly in AGENTS.md
    once this agent is finalized, not left implicit.

    Returns the file path, or None if the frames directory doesn't
    exist / is empty (caller should fall back to YouTube's default
    auto-generated thumbnail in that case, not crash the pipeline).
    """
    frames_path = Path(frames_dir)
    if not frames_path.exists():
        print(f"  [agent9] WARNING: {frames_dir} not found -- Agent 8's "
              f"frames were likely already cleaned up. Falling back to "
              f"YouTube's default auto-thumbnail.")
        return None

    target_frame_idx = int(hook_duration_hint_s * fps) - 1
    target_frame_idx = max(0, target_frame_idx)

    candidate = frames_path / f"frame_{target_frame_idx:05d}.png"
    if candidate.exists():
        return str(candidate)

    # exact target frame missing (shorter HOOK than hinted, etc.) --
    # fall back to the earliest available frame past a small warm-up
    # window, rather than failing outright
    all_frames = sorted(frames_path.glob("frame_*.png"))
    if not all_frames:
        print(f"  [agent9] WARNING: {frames_dir} exists but contains no "
              f"frame files. Falling back to YouTube's default thumbnail.")
        return None

    warmup_frames = max(1, fps // 2)  # skip the first ~0.5s (fade-in)
    return str(all_frames[min(warmup_frames, len(all_frames) - 1)])


# ---------------------------------------------------------------------
# ORCHESTRATION
# ---------------------------------------------------------------------

def seo_optimizer_node(state: dict) -> dict:
    """
    LangGraph-style node wrapper, matching the pattern used by every
    other agent in this pipeline (state in, state out).

    Reads: state["script"] (Agent 6), state["shot_list"] (Agent 7),
           state["stories"] (original), state["video_path"] (Agent 8)
    Writes: state["seo"] = {title, description, tags, category_id,
                             thumbnail_path}
    """
    import ollama

    def _ollama_query(prompt: str) -> str:
        response = ollama.generate(
            model="qwen2.5:7b",
            prompt=prompt,
            options={"temperature": 0.3},  # low temp: extraction, not creative writing
        )
        return response["response"]

    sections = state["script"]["sections"]
    hook_text = sections.get("HOOK", "")
    script_full_text = state["script"]["full_text"]
    shot_list = state["shot_list"]

    all_stories = (state["stories"].values() if isinstance(state["stories"], dict)
                   else state["stories"])
    stories_by_rank = {
        s["selection_rank"]: s for s in all_stories
        if "selection_rank" in s and s.get("selection_rank") is not None
    }

    title = _build_title(hook_text)
    description = _build_description(script_full_text, shot_list)
    tags, fallback_count = _build_tags(stories_by_rank, ollama_generate_fn=_ollama_query)

    frames_dir = os.environ.get("AGENT8_FRAMES_DIR", "frames_agent8")
    thumbnail_path = _select_thumbnail_frame(frames_dir)

    print(f"[agent9] title ({len(title)} chars): {title}")
    print(f"[agent9] description: {len(description)} chars")
    print(f"[agent9] tags: {len(tags)} tags, {fallback_count} used fallback "
          f"extraction, {sum(len(t)+1 for t in tags)} chars of {TAGS_TOTAL_BUDGET} budget")
    print(f"[agent9] thumbnail: {thumbnail_path or '(none -- using YouTube default)'}")

    state["seo"] = {
        "title": title,
        "description": description,
        "tags": tags,
        "category_id": CATEGORY_ID,
        "thumbnail_path": thumbnail_path,
    }
    return state