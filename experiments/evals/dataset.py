"""Golden-dataset loaders.

The eval suite does NOT fetch live trends or hit network APIs. It replays
REAL pipeline state that already exists from past runs:

  * data/checkpoints/till-agent9.json  -- full NewsroomState after Agent 9
                                          (stories, script, shot_list, seo)
  * data/stories_cache.json            -- 100+ processed stories

This is the same dual use as a unit-test fixture: deterministic, offline,
and representative of production reality.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from . import config


def load_json(path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_golden_checkpoint(name: str | None = None) -> dict:
    """Returns the golden full-pipeline state checkpoint."""
    name = name or config.GOLDEN_CHECKPOINT
    return load_json(config.CHECKPOINT_DIR / name)


def load_stories_cache() -> dict:
    """Returns the full story cache {story-key: story-dict}."""
    return load_json(config.STORIES_CACHE_PATH)


def selected_stories(state: dict) -> list[dict]:
    """Stories that survived editorial (have a selection_rank), sorted."""
    stories = state.get("stories", {})
    values = stories.values() if isinstance(stories, dict) else stories
    ranked = [s for s in values if s.get("selection_rank") is not None]
    return sorted(ranked, key=lambda s: s["selection_rank"])


def golden_script(state: dict) -> dict:
    """Returns state['script'] or raises a descriptive error."""
    script = state.get("script")
    if not script:
        raise ValueError("checkpoint has no 'script' -- not a post-Agent5 state")
    return script


def golden_checkpoints() -> Iterator[dict]:
    """All checkpoints in data/checkpoints, oldest first (they are
    snapshots of progressively later pipeline stages)."""
    for path in sorted(config.CHECKPOINT_DIR.glob("till-agent*.json")):
        yield load_json(path)


def checkpoint_summary(state: dict) -> str:
    return (
        f"checkpoint={state.get('_checkpoint_name')!r} "
        f"stories={state.get('_stories_count', len(state.get('stories', {})))} "
        f"has_script={bool(state.get('script'))} "
        f"has_shots={bool(state.get('shot_list'))} "
        f"has_seo={bool(state.get('seo'))}"
    )