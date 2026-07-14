"""
agent_tools/output_organization.py

Groups a completed pipeline run's finished artifacts (video + its
source audio) into a single timestamped folder under output/, separate
from data/ (working/intermediate files: checkpoints, raw audio chunks,
frame PNGs). Kept deliberately separate from Agent 8 -- "render a
video" and "organize finished deliverables" are different concerns,
and Agent 9/10 (SEO, publishing) will want to reuse this same
organization logic without depending on Agent 8's internals.

output/{YYYYMMDD_HHMMSS}/
    final_video.mp4
    <original audio filename>.wav   (copied, not moved -- data/audio/
                                      keeps its own copy so re-running
                                      Agent 8 doesn't need to re-fetch it)

Usage (as its own notebook cell, after Agent 8):
    from agent_tools.output_organization import organize_run_output
    run_dir = organize_run_output(call8)
    print(f"Finished run available at: {run_dir}")
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

# PATCH (2026-07-14): resolve the project root from THIS SCRIPT'S OWN
# location, not the caller's current working directory -- same fix
# applied to generate_showcase_pages.py after a real bug on 2026-07-14
# where a bare "output" default (resolved relative to cwd) silently
# created a duplicate experiments/output/ tree when called from a
# Jupyter notebook whose kernel cwd is experiments/, not the project
# root. This file lives at <project_root>/experiments/agent_tools/, so
# walking up two directories reliably finds the project root regardless
# of cwd.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_OUTPUT_ROOT = str(PROJECT_ROOT / "output")


def _make_run_slug(state: dict, max_len: int = 60) -> str:
    """
    Builds a short, filesystem-safe slug from the run's story titles,
    e.g. 'beavis-ultrasound-cyberpunk-comics-tiny-emulators' (truncated
    if too long). Falls back to 'run' if shot_list/stories aren't
    available for any reason -- naming is a nice-to-have, never worth
    failing the whole organize step over.
    """
    import re

    titles = []
    shot_list = state.get("shot_list", [])
    seen = set()
    for shot in shot_list:
        title = shot.get("story_title")
        if title and title not in seen:
            seen.add(title)
            titles.append(title)

    if not titles:
        return "run"

    slug = "-".join(titles)
    slug = slug.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)  # non-alphanumeric -> hyphen
    slug = re.sub(r"-+", "-", slug).strip("-")  # collapse repeats, trim ends
    return slug[:max_len].rstrip("-") or "run"


def organize_run_output(state: dict, output_root: str = DEFAULT_OUTPUT_ROOT) -> Path:
    """
    Takes Agent 8's output state (must contain state["video_path"] and
    state["script"]["audio_path"]), copies both into a new folder named
    output/{YYYYMMDD_HHMMSS}_{story-slug}/, and returns that folder's Path.

    Does not modify state -- this is a post-processing step, not a
    pipeline node, so it doesn't need the state-in/state-out node
    pattern the agents use. Call it after Agent 8, pass it Agent 8's
    returned state directly.
    """
    video_path = state.get("video_path")
    if not video_path:
        raise ValueError(
            "state['video_path'] not found -- pass this the state "
            "returned by Agent 8's video_assembler_node(), not an "
            "earlier checkpoint."
        )
    if not Path(video_path).exists():
        raise FileNotFoundError(
            f"state['video_path'] points to {video_path}, but that "
            f"file doesn't exist on disk. Was Agent 8 actually run, "
            f"and did it succeed?"
        )

    audio_path = state["script"]["audio_path"]
    if not Path(audio_path).exists():
        raise FileNotFoundError(
            f"state['script']['audio_path'] points to {audio_path}, "
            f"but that file doesn't exist on disk."
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _make_run_slug(state)
    run_id = f"{timestamp}_{slug}"
    run_dir = Path(output_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    final_video_path = run_dir / "final_video.mp4"
    shutil.copy2(video_path, final_video_path)

    audio_copy_path = run_dir / Path(audio_path).name
    shutil.copy2(audio_path, audio_copy_path)

    metadata = _build_metadata(state, run_id, final_video_path.name, audio_copy_path.name)
    metadata_path = run_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"[output_organization] created {run_dir}")
    print(f"[output_organization]   video: {final_video_path.name} "
          f"({final_video_path.stat().st_size / (1024*1024):.1f} MB)")
    print(f"[output_organization]   audio: {audio_copy_path.name}")
    print(f"[output_organization]   metadata: {metadata_path.name}")

    return run_dir


def _build_metadata(state: dict, run_id: str, video_filename: str, audio_filename: str) -> dict:
    """
    Pulls real, already-known fields out of state into a flat JSON
    structure -- this is what the audio-demo.html generator reads, so
    it never has to re-derive titles/word counts/etc from filenames or
    guess at anything already computed earlier in the pipeline.
    Missing fields are stored as None rather than omitted, so the
    generator can decide how to handle gaps explicitly instead of
    hitting a KeyError.
    """
    script = state.get("script", {})

    titles = []
    seen = set()
    for shot in state.get("shot_list", []):
        title = shot.get("story_title")
        if title and title not in seen:
            seen.add(title)
            titles.append(title)

    return {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(),
        "video_filename": video_filename,
        "audio_filename": audio_filename,
        "story_titles": titles,
        "full_text": script.get("tts_ready_text") or script.get("full_text"),
        "word_count": script.get("word_count"),
        "qc_iterations": script.get("iterations"),
        "audio_duration_s": script.get("audio_duration"),
        "video_duration_s": state.get("video_stats", {}).get("duration_s"),
        "voice_used": script.get("voice_used", "af_heart (Kokoro-82M)"),
    }


def list_runs(output_root: str = DEFAULT_OUTPUT_ROOT) -> list[Path]:
    """
    Lists all existing run folders under output_root, most recent
    first -- useful for a quick 'what have I already generated' check
    without digging through the filesystem manually.
    """
    root = Path(output_root)
    if not root.exists():
        return []
    runs = sorted(
        (p for p in root.iterdir() if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    return runs


def prune_old_runs(output_root: str = DEFAULT_OUTPUT_ROOT, keep: int = 5, dry_run: bool = False) -> list[Path]:
    """
    Deletes run folders beyond the most recent `keep`, so output/ doesn't
    grow without bound. The demo page (generate_demo_pages.py) only ever
    shows the `keep` most recent runs anyway -- older runs sitting on
    disk aren't reachable from the page, only taking up space.

    Set dry_run=True to see what WOULD be deleted without actually
    deleting anything -- worth running once before trusting this with
    dry_run=False, since deletion is irreversible.

    Returns the list of folders that were (or, if dry_run, would be)
    deleted.
    """
    import shutil as _shutil

    runs = list_runs(output_root)
    to_delete = runs[keep:]  # everything past the `keep` most recent

    if not to_delete:
        print(f"[output_organization] {len(runs)} run(s) found, "
              f"within the keep={keep} limit -- nothing to prune")
        return []

    verb = "Would delete" if dry_run else "Deleting"
    for run_dir in to_delete:
        size_mb = sum(f.stat().st_size for f in run_dir.rglob("*") if f.is_file()) / (1024 * 1024)
        print(f"[output_organization] {verb}: {run_dir} ({size_mb:.1f} MB)")
        if not dry_run:
            _shutil.rmtree(run_dir)

    if dry_run:
        print(f"[output_organization] dry run -- nothing actually deleted. "
              f"Re-run with dry_run=False to actually prune.")
    else:
        print(f"[output_organization] pruned {len(to_delete)} old run(s), "
              f"kept the {keep} most recent")

    return to_delete