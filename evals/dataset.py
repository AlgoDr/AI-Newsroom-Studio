"""Data loading helpers for checkpoint-based evals.

Loads the golden pipeline checkpoint and stories cache so the eval
functions can score pipeline output without re-running agents.

Paths are relative to the project root (two levels up from evals/).

On CI the full experiments/data/ tree is git-ignored, so we fall back
to committed fixtures in evals/fixtures/.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Project root: evals/ sits one level below the repo root
_EVALS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _EVALS_DIR.parent

# ── CI fixtures (committed, always available) ────────────────────
_FIXTURES = _EVALS_DIR / "fixtures"

# ── Checkpoint paths ─────────────────────────────────────────────
# DEFAULT: the frozen, committed fixture. Evals must be repeatable, and a
# live pipeline run overwrites experiments/data/checkpoints/*.json (a
# 148-word script from one run failed the 150-225 word check while the
# code was unchanged).
# To eval your latest real run instead:  EVAL_LIVE_CHECKPOINT=1 python evals/run_all.py
_LIVE_CHECKPOINTS = [
    _PROJECT_ROOT / "experiments" / "data" / "checkpoints" / "till-agent9.json",
    _PROJECT_ROOT / "experiments" / "data" / "checkpoints" / "till-agent8.json",
    _PROJECT_ROOT / "experiments" / "data" / "checkpoints" / "till-agent7.json",
    _PROJECT_ROOT / "experiments" / "data" / "checkpoints" / "till-agent6_1.json",
    _PROJECT_ROOT / "experiments" / "data" / "checkpoints" / "till-agent6.json",
    _PROJECT_ROOT / "experiments" / "data" / "checkpoints" / "till-agent5.json",
]
_CHECKPOINT_CANDIDATES = (
    _LIVE_CHECKPOINTS + [_FIXTURES / "golden_checkpoint.json"]
    if os.getenv("EVAL_LIVE_CHECKPOINT")
    else [_FIXTURES / "golden_checkpoint.json"] + _LIVE_CHECKPOINTS
)

_STORIES_CACHE = _PROJECT_ROOT / "experiments" / "data" / "stories_cache.json"
_STORIES_CACHE_CI = _FIXTURES / "stories_cache.json"


def load_golden_checkpoint() -> dict:
    """Load the most complete pipeline checkpoint available."""
    for path in _CHECKPOINT_CANDIDATES:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    raise FileNotFoundError(
        f"No checkpoint found. Searched:\n"
        + "\n".join(f"  {p}" for p in _CHECKPOINT_CANDIDATES)
    )


def load_stories_cache() -> dict:
    """Load the stories cache (slug -> story dict)."""
    for path in [_STORIES_CACHE, _STORIES_CACHE_CI]:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    raise FileNotFoundError(
        f"Stories cache not found at {_STORIES_CACHE} or {_STORIES_CACHE_CI}"
    )


def golden_script(state: dict) -> dict:
    """Extract the script dict from a checkpoint state."""
    script = state.get("script")
    if not script:
        raise ValueError("Checkpoint has no 'script' key")
    return script


def selected_stories(state: dict) -> list[dict]:
    """Return stories with a selection_rank, sorted by rank.

    The checkpoint stores stories as a dict (slug -> story).
    Stories chosen by Agent 4 have a 'selection_rank' field.
    """
    stories = state.get("stories", {})
    if isinstance(stories, dict):
        all_stories = list(stories.values())
    elif isinstance(stories, list):
        all_stories = stories
    else:
        return []

    ranked = [s for s in all_stories
              if isinstance(s, dict) and s.get("selection_rank")]
    ranked.sort(key=lambda s: s["selection_rank"])
    return ranked


def checkpoint_summary(state: dict) -> str:
    """One-line summary of a checkpoint for eval output."""
    n_stories = len(state.get("stories", {}))
    script = state.get("script", {})
    wc = script.get("word_count", "?")
    approved = script.get("approved", False)
    has_shots = bool(state.get("shot_list"))
    has_seo = bool(state.get("seo", {}).get("title"))
    has_video = bool(state.get("video_path"))
    return (
        f"checkpoint: {n_stories} stories, script({wc}w, "
        f"{'approved' if approved else 'not approved'}), "
        f"shots={'yes' if has_shots else 'no'}, "
        f"seo={'yes' if has_seo else 'no'}, "
        f"video={'yes' if has_video else 'no'}"
    )
