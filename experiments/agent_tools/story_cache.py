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
from datetime import datetime

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