"""
pipeline_cache.py — Full pipeline state checkpointing

Saves and loads the complete NewsroomState at any agent checkpoint.
Unlike story_cache.py (which only saves per-story fields),
pipeline_cache saves the FULL state including top-level keys like script.

Usage:
    from agent_tools.pipeline_cache import save_checkpoint, load_checkpoint

    # Save after Agent 5
    save_checkpoint(call5, name="till-agent5")

    # Load for Agent 6 testing
    state = load_checkpoint("till-agent5")
    print(state["script"]["full_text"])

Checkpoint files saved to: data/checkpoints/<name>.json
"""

import os
import json
from datetime import datetime, timezone

# ── checkpoint directory ───────────────────────────────────────────────────
CHECKPOINT_DIR = "data/checkpoints"


def save_checkpoint(state: dict, name: str) -> str:
    """Save complete pipeline state to a named checkpoint.

    Args:
        state: the full NewsroomState dict (stories + script + any future keys)
        name:  checkpoint name e.g. "till-agent5", "till-agent4"

    Returns:
        filepath of the saved checkpoint

    Example:
        save_checkpoint(call5, "till-agent5")
        # saves to data/checkpoints/till-agent5.json
    """
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    filepath = os.path.join(CHECKPOINT_DIR, f"{name}.json")

    # add metadata
    payload = {
        "_checkpoint_name":    name,
        "_saved_at":           datetime.now(timezone.utc).isoformat(),
        "_stories_count":      len(state.get("stories", {})),
        "_has_script":         "script" in state,
        **state
    }

    with open(filepath, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    stories_count = len(state.get("stories", {}))
    has_script = "script" in state
    print(f"[checkpoint] saved '{name}' → {filepath}")
    print(f"[checkpoint]   stories: {stories_count}")
    if has_script:
        wc = state["script"].get("word_count", 0)
        dur = state["script"].get("est_duration", "?")
        print(f"[checkpoint]   script:  {wc} words, ~{dur}")

    return filepath


def load_checkpoint(name: str) -> dict:
    """Load a named checkpoint and return the pipeline state.

    Args:
        name: checkpoint name e.g. "till-agent5"

    Returns:
        full NewsroomState dict ready to feed into the next agent

    Example:
        state = load_checkpoint("till-agent5")
        call6 = script_qc_node(state)
    """
    filepath = os.path.join(CHECKPOINT_DIR, f"{name}.json")

    if not os.path.exists(filepath):
        raise FileNotFoundError(
            f"[checkpoint] '{name}' not found at {filepath}\n"
            f"Available checkpoints: {list_checkpoints()}"
        )

    with open(filepath) as f:
        payload = json.load(f)

    # remove metadata keys before returning
    state = {k: v for k, v in payload.items() if not k.startswith("_")}

    saved_at = payload.get("_saved_at", "unknown")
    stories_count = len(state.get("stories", {}))
    has_script = "script" in state

    print(f"[checkpoint] loaded '{name}' (saved: {saved_at})")
    print(f"[checkpoint]   stories: {stories_count}")
    if has_script:
        wc = state["script"].get("word_count", 0)
        dur = state["script"].get("est_duration", "?")
        print(f"[checkpoint]   script:  {wc} words, ~{dur}")

    return state


def list_checkpoints() -> list:
    """List all available checkpoint names."""
    if not os.path.exists(CHECKPOINT_DIR):
        return []
    files = [f.replace(".json", "")
             for f in os.listdir(CHECKPOINT_DIR)
             if f.endswith(".json")]
    return sorted(files)


def checkpoint_info(name: str) -> dict:
    """Return metadata about a checkpoint without loading full state."""
    filepath = os.path.join(CHECKPOINT_DIR, f"{name}.json")
    if not os.path.exists(filepath):
        return {}
    with open(filepath) as f:
        payload = json.load(f)
    return {k: v for k, v in payload.items() if k.startswith("_")}