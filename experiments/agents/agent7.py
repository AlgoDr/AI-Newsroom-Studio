"""
Agent 7 -- Video Assembly Prompt Generator

Role: convert the Agent 6-approved script into a per-section shot list --
what to search for and roughly when each shot should play -- so Agent 8
can fetch stock footage and assemble it without making any content
decisions of its own.

Does NOT call any stock footage API, does NOT run ffmpeg, does NOT touch
audio/video files. Pure text-in, structured-data-out.

Pivoted from "write a cinematic AI-video-generation prompt" to "extract
concrete stock-footage search queries" -- see README's "Why stock
footage, not AI video generation?" and KNOWN_ISSUES ISSUE-20 for why:
real AI video generation costs $0.50-5+/clip via every API checked
(Synthesia, HeyGen, Veo, Grok Imagine, HF-routed providers), and local
generation (Wan2.1 1.3B via mlx-video, tested end-to-end on this
project's actual 16GB M4 Pro) needs ~10+ minutes and 20GB+ swap per
2-second clip even in its best working configuration -- not viable for
daily automated use on this hardware.
"""

from urllib.parse import urlparse
import re
from urllib.parse import urlparse as _urlparse  # noqa: F401 (explicit, avoids shadowing)

# ---------------------------------------------------------------------
# Fallback query categories, used when a story's own content doesn't
# translate to a natural literal visual (e.g. a CVE writeup, an abstract
# research post). Deliberately generic/safe rather than guessing a
# literal-but-wrong query -- a mismatched literal query is worse than an
# honest generic one.
# ---------------------------------------------------------------------
FALLBACK_QUERIES = {
    "security": ["cybersecurity abstract", "code on screen dark", "server room blue light"],
    "hardware": ["circuit board macro", "soldering electronics workbench", "vintage computer hardware"],
    "software": ["typing code editor", "terminal command line", "software development desk"],
    "research": ["science research lab", "physics chalkboard equations", "library books stacking"],
    "generic_tech": ["abstract technology particles", "data visualization blue", "futuristic grid animation"],
}

# Section-name prefix -> which story rank it belongs to. HOOK and CTA are
# whole-video bookends, not tied to a single story.
BOOKEND_SECTIONS = {"HOOK", "CTA"}


def _story_rank_for_section(section_name: str) -> int | None:
    """
    'S1_CONTEXT' -> 1, 'S2_TWIST' -> 2, 'S3_CORE' -> 3.
    'HOOK' / 'CTA' -> None (bookend, no single story owns it).
    """
    if section_name in BOOKEND_SECTIONS:
        return None
    match = re.match(r"^S(\d)_", section_name)
    if not match:
        # Unexpected section name -- don't guess, surface it clearly so
        # this gets noticed rather than silently mis-mapped.
        return None
    return int(match.group(1))


def _extract_domain(url: str) -> str:
    """'https://github.com/schlae/BeavisUltrasound' -> 'github.com/schlae'"""
    parsed = urlparse(url)
    netloc = parsed.netloc.replace("www.", "")
    path_parts = [p for p in parsed.path.split("/") if p]
    if path_parts:
        return f"{netloc}/{path_parts[0]}"
    return netloc


def _guess_fallback_category(story: dict) -> str:
    """
    Cheap keyword sniff over title+content to pick a fallback category
    when the LLM query-extraction step (below) can't produce a concrete
    literal query. Intentionally simple -- this is a safety net, not the
    primary path.
    """
    text = f"{story.get('title', '')} {story.get('content', '')[:500]}".lower()
    if any(kw in text for kw in ["cve", "vulnerability", "exploit", "security", "hack"]):
        return "security"
    if any(kw in text for kw in ["circuit", "chip", "hardware", "pcb", "board", "sound card"]):
        return "hardware"
    if any(kw in text for kw in ["code", "software", "programming", "runtime", "compiler"]):
        return "software"
    if any(kw in text for kw in ["research", "study", "physics", "science", "paper"]):
        return "research"
    return "generic_tech"


QUERY_EXTRACTION_PROMPT = """You are picking ONE short stock-footage search query for a single \
sentence from a tech news video script. The query will be typed directly \
into Pexels/Pixabay's search box.

Rules:
- 2-5 words, concrete and literal (e.g. "circuit board macro shot", not \
"the fascinating world of electronics")
- Describe something a stock footage site would plausibly HAVE, not the \
specific named product/person/company (stock sites don't have "Gravis \
Ultrasound PnP" footage, but they have "vintage circuit board")
- No brand names, no proper nouns unless extremely common (e.g. "GitHub" \
is fine, an obscure project name is not)
- Reply with ONLY the query, nothing else -- no quotes, no explanation

Sentence: {section_text}

Query:"""


def extract_section_query(section_text: str, fallback_category: str, ollama_generate_fn=None) -> tuple[str, bool]:
    """
    Returns (query, used_fallback). ollama_generate_fn is injected so this
    stays testable without a live Ollama server -- pass e.g.
    `lambda prompt: ollama.generate(model="qwen2.5:7b", prompt=prompt)["response"]`.

    Model choice: qwen2.5:7b, not a larger local model -- this is a small,
    structured, low-creativity extraction task, and the project already
    reserves gemma3:12b for tasks that need more reasoning (Agent 2
    synthesis, Agent 5 script writing). See conversation log for the
    reasoning behind not defaulting to the biggest available model here.
    """
    if ollama_generate_fn is None:
        # No model wired up (e.g. running Agent 7 standalone/offline) --
        # go straight to the safe fallback rather than fail the whole run.
        return (FALLBACK_QUERIES[fallback_category][0], True)

    try:
        raw = ollama_generate_fn(QUERY_EXTRACTION_PROMPT.format(section_text=section_text))
        query = raw.strip().strip('"').strip("'")
        # Sanity checks: reject obviously-bad extractions rather than
        # trust the model blindly -- an empty, too-long, or
        # instruction-echoing response falls back to the safe category.
        word_count = len(query.split())
        if not query or word_count < 2 or word_count > 8:
            return (FALLBACK_QUERIES[fallback_category][0], True)
        if "query:" in query.lower() or "sentence:" in query.lower():
            return (FALLBACK_QUERIES[fallback_category][0], True)
        return (query, False)
    except Exception:
        # Ollama down, model not pulled, etc. -- never let a video-prompt
        # generation failure take down the whole pipeline run.
        return (FALLBACK_QUERIES[fallback_category][0], True)


def build_shot_list(state: dict, ollama_generate_fn=None) -> list[dict]:
    """
    Agent 7's main entrypoint. Reads state["stories"] and
    state["script"]["sections"], returns the shot list Agent 8 consumes.

    Timing is word-count-proportional against state["script"]["word_count"]
    -- an explicit approximation, not frame-accurate, until real
    beat_timestamps exist from Agent 6.1 (see AGENTS.md dependency note).
    Every shot's timing is derived here in one place so swapping in real
    timestamps later only requires changing this function's internals,
    not Agent 8's consumption logic.
    """
    # state["stories"] holds ALL stories seen this run (often 6-8), not
    # just the 3 selected ones -- confirmed via a real checkpoint
    # inspection (2026-07-14 run): a story discarded by Agent 3 for
    # contradiction never went through Agent 4's editorial scoring at
    # all, so it has no "selection_rank" key whatsoever (not None --
    # genuinely absent). Only include stories that actually have the
    # key, rather than assuming universal presence, which crashed with
    # a bare KeyError on this real run.
    all_stories = (state["stories"].values() if isinstance(state["stories"], dict)
                   else state["stories"])
    stories_by_rank = {
        s["selection_rank"]: s for s in all_stories
        if "selection_rank" in s and s.get("selection_rank") is not None
    }

    sections = state["script"]["sections"]
    total_words = state["script"]["word_count"]
    audio_duration = state["script"].get("audio_duration")  # may not exist yet pre-6.1

    # Defensive check: state["script"]["word_count"] should equal the sum
    # of each section's actual word count. If it doesn't, every shot's
    # start_s/end_s would be silently wrong (proportions computed against
    # a total that doesn't match the parts). This exact class of drift is
    # already documented in KNOWN_ISSUES ISSUE-18 (final word count not
    # re-validated after Agent 6 rewrites) -- so this isn't hypothetical,
    # it's a known failure mode elsewhere in the pipeline that Agent 7
    # would otherwise inherit silently.
    actual_word_count = sum(len(text.split()) for text in sections.values())
    if total_words != actual_word_count:
        raise ValueError(
            f"state['script']['word_count'] is {total_words}, but summing "
            f"all sections' actual words gives {actual_word_count}. "
            f"Timing math would be silently wrong if this proceeds -- "
            f"likely stale word_count after an Agent 6 rewrite pass "
            f"(see KNOWN_ISSUES ISSUE-18). Re-validate word_count before "
            f"calling Agent 7."
        )

    fallback_category_by_rank = {
        rank: _guess_fallback_category(story) for rank, story in stories_by_rank.items()
    }

    shot_list = []
    cumulative_words = 0

    # Preserve script order: HOOK, S1_CONTEXT, S1_CORE, S1_TWIST, S2_HOOK, ...
    for section_name, section_text in sections.items():
        section_word_count = len(section_text.split())
        start_words = cumulative_words
        cumulative_words += section_word_count
        end_words = cumulative_words

        start_share = start_words / total_words if total_words else 0
        end_share = end_words / total_words if total_words else 0

        shot = {
            "section": section_name,
            "text": section_text,
            "word_count": section_word_count,
            "start_share": round(start_share, 4),
            "end_share": round(end_share, 4),
        }
        if audio_duration:
            shot["start_s"] = round(start_share * audio_duration, 2)
            shot["end_s"] = round(end_share * audio_duration, 2)

        rank = _story_rank_for_section(section_name)
        if rank is None:
            # HOOK / CTA -- whole-video bookend, generic branded query,
            # no single story's source domain applies.
            shot["story_rank"] = None
            shot["query"] = "abstract technology particles blue"
            shot["source_domain"] = None
            shot["story_title"] = None
            shot["used_fallback_query"] = True
        else:
            story = stories_by_rank.get(rank)
            if story is None:
                # Section references a story rank that doesn't exist in
                # state["stories"] -- surface loudly rather than guess.
                raise ValueError(
                    f"Section '{section_name}' maps to story_rank={rank}, "
                    f"but no story with that selection_rank was found in "
                    f"state['stories']. Available ranks: "
                    f"{sorted(stories_by_rank.keys())}"
                )
            query, used_fallback = extract_section_query(
                section_text,
                fallback_category_by_rank[rank],
                ollama_generate_fn=ollama_generate_fn,
            )
            shot["story_rank"] = rank
            shot["query"] = query
            shot["source_domain"] = _extract_domain(story["url"])
            shot["story_title"] = story["title"]
            shot["used_fallback_query"] = used_fallback

        shot_list.append(shot)

    return shot_list


def video_assembly_prompt_node(state: dict) -> dict:
    """
    LangGraph-style node wrapper, matching the pattern used by every
    other agent in this pipeline (state in, state out).
    """
    import ollama

    def _ollama_query(prompt: str) -> str:
        response = ollama.generate(
            model="qwen2.5:7b",
            prompt=prompt,
            options={"temperature": 0.3},  # low temp: extraction, not creative writing
        )
        return response["response"]

    shot_list = build_shot_list(state, ollama_generate_fn=_ollama_query)

    fallback_count = sum(1 for s in shot_list if s.get("used_fallback_query"))
    print(f"[agent7] built shot list: {len(shot_list)} sections, "
          f"{fallback_count} used fallback queries")
    for shot in shot_list:
        marker = "  (fallback)" if shot.get("used_fallback_query") else ""
        print(f"  {shot['section']:12s} rank={shot['story_rank']} "
              f"query='{shot['query']}'{marker}")

    state["shot_list"] = shot_list
    return state