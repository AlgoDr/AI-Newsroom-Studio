"""
story_cache.py — Persist NewsroomState stories dict to disk.

Why: content fetch + background synthesis + credibility classification
     all cost time and API quota. Once a story is processed, we should
     never re-process it. This module handles save/load/merge.

Usage in workflow.ipynb:
    from agents.story_cache import save_stories, load_stories, filter_new_stories

File location: data/stories_cache.json
Format: { "story-slug-id": { full story dict with all agent fields }, ... }
"""

import json
import pathlib
from datetime import datetime, timedelta

CACHE_PATH = pathlib.Path("data/stories_cache.json")


def save_stories(stories: dict) -> None:
    """Save processed stories to disk.
    Merges with existing cache — never overwrites old stories.
    Adds 'cached_at' timestamp to each story for debugging.
    """
    CACHE_PATH.parent.mkdir(exist_ok=True)

    # load existing cache (if any)
    existing = _load_raw()

    # merge: new stories overwrite old ones with same ID
    # (in case a story was re-fetched with better content)
    now = datetime.now().isoformat(timespec="seconds")
    for sid, story in stories.items():
        story_copy = dict(story)
        story_copy["cached_at"] = now
        existing[sid] = story_copy

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"  [cache] saved {len(stories)} stories → "
          f"{CACHE_PATH} ({len(existing)} total in cache)")


def load_stories() -> dict:
    """Load all cached stories from disk.
    Returns empty dict if cache doesn't exist yet."""
    cache = _load_raw()
    print(f"  [cache] loaded {len(cache)} stories from {CACHE_PATH}")
    return cache


def filter_new_stories(fresh_stories: dict) -> tuple[dict, dict]:
    """Split fresh Agent 1 stories into:
      - new_stories:   never seen before → need Agent 2 + 3
      - known_stories: already in cache  → skip re-processing

    Returns: (new_stories, known_stories)
    """
    cached_ids = set(_load_raw().keys())

    new_stories   = {sid: s for sid, s in fresh_stories.items()
                     if sid not in cached_ids}
    known_stories = {sid: s for sid, s in fresh_stories.items()
                     if sid in cached_ids}

    print(f"  [cache] {len(fresh_stories)} stories from HN → "
          f"{len(new_stories)} new, {len(known_stories)} already cached")
    return new_stories, known_stories


def load_todays_pipeline_state() -> dict:
    """Load cached stories to resume a partial run.
    Use this if Agent 2 completed but Agent 3 failed —
    load from cache, skip Agent 2, run Agent 3 only.
    """
    stories = _load_raw()
    return {"stories": stories}


def cache_stats() -> None:
    """Print a summary of what's in the cache."""
    cache = _load_raw()
    if not cache:
        print("  [cache] empty — no stories cached yet")
        return

    has_content    = sum(1 for s in cache.values() if s.get("content"))
    has_background = sum(1 for s in cache.values() if s.get("background"))
    has_cred       = sum(1 for s in cache.values() if s.get("credibility_score") is not None)
    discarded      = sum(1 for s in cache.values() if s.get("discarded"))

    print(f"  [cache] {len(cache)} total stories")
    print(f"          {has_content} with content")
    print(f"          {has_background} with background")
    print(f"          {has_cred} with credibility score")
    print(f"          {discarded} marked discarded")


def _load_raw() -> dict:
    """Internal: load raw JSON, return empty dict if file missing."""
    if not CACHE_PATH.exists():
        return {}
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        print(f"  [cache] WARNING: could not read {CACHE_PATH}, starting fresh")
        return {}

def load_todays_session(hours_back: int = 6) -> dict:
    """
    Resume a recent, interrupted run WITHOUT re-running Agent 1-3.

    Unlike load_todays_pipeline_state() (which returns the ENTIRE cache,
    including stories from days-old sessions), this filters to only
    stories cached within the last `hours_back` hours -- i.e. this
    specific session's Agent 1-3 output, not everything ever fetched.

    hours_back=6 is a generous default (covers a normal work session)
    -- tighten it if you want stricter "only this exact run" behavior,
    but don't rely on this for anything more precise than "recent" --
    cached_at is a save-time timestamp, not a run-id, so two separate
    sessions within the window would both be included.
    """
    cache = _load_raw()
    cutoff = datetime.now() - timedelta(hours=hours_back)

    recent = {}
    skipped_old = 0
    for sid, story in cache.items():
        cached_at_str = story.get("cached_at")
        if not cached_at_str:
            continue  # no timestamp at all -- definitely not from this session
        try:
            cached_at = datetime.fromisoformat(cached_at_str)
        except ValueError:
            continue
        if cached_at >= cutoff:
            recent[sid] = story
        else:
            skipped_old += 1

    print(f"  [cache] load_todays_session(hours_back={hours_back}): "
          f"{len(recent)} recent stories, {skipped_old} older stories excluded")
    return recent


def get_stories_for_agent4(call3: dict | None, hours_back: int = 6) -> dict:
    """
    The single entry point Agent 4 should always call to get its input
    stories -- branches automatically so the notebook doesn't need an
    if/else at the call site:

      - call3 provided (Agent 1-3 just ran successfully, state is in
        RAM): use it directly, no disk read at all.
      - call3 is None (kernel/notebook was interrupted after
        save_stories() ran but before Agent 4 -- RAM was cleared):
        fall back to load_todays_session() to recover ONLY this
        session's stories from disk, never the full multi-day cache.

    Usage in workflow.ipynb, replacing the ad-hoc
    "cached_stories = load_stories(); call4 = editorial_node(cached_stories)"
    pattern entirely:

        from agent_tools.story_cache import get_stories_for_agent4
        from agents.agent4 import editorial_node, route_after_editorial

        # normal path, right after Agent 3 in the same session:
        stories_for_agent4 = get_stories_for_agent4(call3["stories"])

        # OR, resuming after an interruption (call3 no longer in RAM):
        stories_for_agent4 = get_stories_for_agent4(None)

        call4 = editorial_node({"stories": stories_for_agent4})
        route = route_after_editorial(call4)
    """
    if call3 is not None:
        print(f"  [cache] call3 provided ({len(call3)} stories) -- "
              f"using in-RAM state directly, no disk read")
        return call3

    print(f"  [cache] call3 not provided -- resuming from disk "
          f"(this session's stories only, not the full cache)")
    return load_todays_session(hours_back=hours_back)