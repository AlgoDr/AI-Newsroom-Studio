#!/usr/bin/env python3
"""
generate_demo_pages.py -- build-time generator for docs/audio-showcase.html
and docs/video-showcase.html.

WHY THIS EXISTS (read before "why doesn't the page just update itself"):
audio-showcase.html/video-showcase.html are static files with no server behind
them (GitHub Pages). Static HTML cannot read your filesystem at
view-time -- there is no way for a visitor's browser to ask "what's in
output/ right now". The only way to show real, current samples on a
static page is to regenerate the HTML file itself, ahead of time, with
the real data already baked in as plain text/audio/video tags. That's
what this script does.

This is NOT wired into the pipeline automatically -- run it manually
whenever you want the public demo pages to reflect your latest runs.
Auto-running this on every pipeline execution would mean every daily
run -- including ones with QC issues or content you wouldn't want
showcased -- publishes to your public GitHub Pages site with no review
step. That's a deliberate choice, not an oversight; revisit only if you
want that tradeoff.

Usage:
    python generate_demo_pages.py
    python generate_demo_pages.py --count 5          # default
    python generate_demo_pages.py --output-root output --docs-dir docs

What it does:
    1. Reads agent_tools/output_organization.py's list_runs() to find
       the most recent N runs under output/
    2. For each run, reads its metadata.json (written by
       organize_run_output() -- see that module for the schema)
    3. Copies each run's audio/video files into docs/samples/ and
       docs/video-samples/ respectively (GitHub Pages serves from
       docs/, matching the existing audio-showcase.html convention)
    4. Renders audio-showcase.html and video-showcase.html from the templates
       below, with real sample-card blocks for each run found

Runs with missing/incomplete metadata (e.g. an older run from before
metadata.json existed) are skipped with a warning, not silently
included with blank data -- see _load_run_metadata().
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

# PATCH (2026-07-14): resolve the project root from THIS SCRIPT'S OWN
# location, not the caller's current working directory. Previously the
# --output-root/--docs-dir defaults were bare "output"/"docs" strings,
# resolved relative to cwd -- when this script was invoked from a
# Jupyter notebook via subprocess.run(cwd="."), "." was the kernel's
# cwd (experiments/), not the project root. That silently created a
# duplicate experiments/docs/ and experiments/output/ tree that GitHub
# Pages never serves from, while the real root docs/ stayed stale. This
# script lives at <project_root>/experiments/agent_tools/, so walking
# up two directories reliably finds the project root regardless of cwd.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent

sys.path.insert(0, str(Path(__file__).parent))
try:
    from output_organization import list_runs
except ImportError:
    def list_runs(output_root: str = "output") -> list:
        root = Path(output_root)
        if not root.exists():
            return []
        return sorted((p for p in root.iterdir() if p.is_dir()),
                       key=lambda p: p.name, reverse=True)


def _load_run_metadata(run_dir: Path):
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        print(f"  skipping {run_dir.name}: no metadata.json (older run?)")
        return None
    try:
        with open(metadata_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  skipping {run_dir.name}: couldn't read metadata.json ({e})")
        return None


def _format_duration(seconds):
    if seconds is None:
        return "?"
    return f"~{round(seconds)}s"


def _format_title(titles):
    if not titles:
        return "<em style=\"color:var(--text-dim); font-style:italic;\">untitled run</em>"
    return ", ".join(titles)


def _escape_html(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


AUDIO_CARD_TEMPLATE = """
        <div class="sample-card">
            <div class="sample-meta">
                <span class="meta-pill">Real pipeline output</span>
                <span>{n_stories} stories \u00b7 one continuous script</span>
            </div>

            <h2 class="sample-title">{title}</h2>

            <audio controls preload="metadata">
                <source src="./samples/{audio_filename}" type="audio/wav">
                Your browser does not support the audio element.
                <a href="./samples/{audio_filename}">Download the audio file</a> instead.
            </audio>

            <span class="script-toggle" onclick="this.nextElementSibling.classList.toggle('open')">
                \u25b8 show the script this audio was generated from
            </span>
            <div class="script-text">{script_text}</div>

            <div class="stat-row">
                <div class="stat">
                    <span class="stat-label">Word count</span>
                    <span class="stat-value">{word_count}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Duration</span>
                    <span class="stat-value">{duration}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">QC iterations</span>
                    <span class="stat-value">{qc_iterations}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Voice</span>
                    <span class="stat-value">{voice}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Cost</span>
                    <span class="stat-value good">$0 \u2014 fully local</span>
                </div>
            </div>
        </div>
"""

VIDEO_CARD_TEMPLATE = """
        <div class="sample-card">
            <div class="sample-meta">
                <span class="meta-pill">Real pipeline output</span>
                <span>{n_stories} stories \u00b7 one continuous script</span>
            </div>

            <h2 class="sample-title">{title}</h2>

            <video controls preload="metadata" style="width:100%; max-width:360px; border-radius:8px; margin-bottom:20px; display:block;">
                <source src="./video-samples/{video_filename}" type="video/mp4">
                Your browser does not support the video element.
                <a href="./video-samples/{video_filename}">Download the video file</a> instead.
            </video>

            <div class="stat-row">
                <div class="stat">
                    <span class="stat-label">Duration</span>
                    <span class="stat-value">{duration}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Word count</span>
                    <span class="stat-value">{word_count}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Resolution</span>
                    <span class="stat-value">1080x1920</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Cost</span>
                    <span class="stat-value good">$0 \u2014 fully local</span>
                </div>
            </div>
        </div>
"""

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Newsroom Studio \u2014 {page_title}</title>
    <style>
        :root {{
            --bg: #0d1117;
            --card: #161b22;
            --border: #30363d;
            --text: #c9d1d9;
            --text-dim: #8b949e;
            --accent: #58a6ff;
            --accent-soft: #1f6feb22;
            --green: #3fb950;
            --mono: 'SF Mono', 'Consolas', 'Liberation Mono', Menlo, monospace;
        }}

        * {{ box-sizing: border-box; }}

        body {{
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 0;
            line-height: 1.6;
        }}

        .wrap {{ max-width: 760px; margin: 0 auto; padding: 56px 24px 80px; }}
        header {{ margin-bottom: 48px; }}

        .eyebrow {{
            font-family: var(--mono);
            font-size: 13px;
            color: var(--accent);
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 12px;
        }}

        h1 {{ font-size: 32px; font-weight: 700; margin: 0 0 12px; letter-spacing: -0.02em; }}
        .subtitle {{ color: var(--text-dim); font-size: 16px; max-width: 560px; }}

        .back-link {{
            display: inline-block;
            margin-top: 20px;
            margin-right: 20px;
            color: var(--accent);
            text-decoration: none;
            font-size: 14px;
            font-family: var(--mono);
        }}
        .back-link:hover {{ text-decoration: underline; }}

        .sample-card {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 28px;
            margin-bottom: 24px;
        }}

        .sample-meta {{
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
            margin-bottom: 18px;
            font-family: var(--mono);
            font-size: 12.5px;
            color: var(--text-dim);
        }}

        .meta-pill {{
            background: var(--accent-soft);
            color: var(--accent);
            padding: 3px 10px;
            border-radius: 100px;
            border: 1px solid #1f6feb44;
        }}

        .sample-title {{ font-size: 18px; font-weight: 600; margin: 0 0 16px; }}

        audio {{ width: 100%; height: 40px; margin-bottom: 20px; }}
        audio::-webkit-media-controls-panel {{ background-color: #0d1117; }}

        .script-toggle {{
            font-family: var(--mono);
            font-size: 13px;
            color: var(--accent);
            cursor: pointer;
            user-select: none;
            display: inline-block;
        }}

        .script-text {{
            display: none;
            margin-top: 16px;
            padding: 16px 18px;
            background: #0d1117;
            border: 1px solid var(--border);
            border-radius: 8px;
            font-family: var(--mono);
            font-size: 13.5px;
            line-height: 1.7;
            color: var(--text-dim);
            white-space: pre-wrap;
        }}
        .script-text.open {{ display: block; }}

        .stat-row {{
            display: flex;
            gap: 28px;
            margin-top: 18px;
            padding-top: 18px;
            border-top: 1px solid var(--border);
            flex-wrap: wrap;
        }}
        .stat {{ font-family: var(--mono); font-size: 12.5px; }}
        .stat-label {{ color: var(--text-dim); display: block; margin-bottom: 2px; }}
        .stat-value {{ color: var(--text); font-weight: 600; }}
        .stat-value.good {{ color: var(--green); }}

        footer {{
            margin-top: 48px;
            padding-top: 24px;
            border-top: 1px solid var(--border);
            font-size: 13px;
            color: var(--text-dim);
            font-family: var(--mono);
        }}
        footer a {{ color: var(--accent); text-decoration: none; }}
        footer a:hover {{ text-decoration: underline; }}

        .empty-note {{
            color: var(--text-dim);
            font-size: 14px;
            font-family: var(--mono);
            padding: 20px;
            border: 1px dashed var(--border);
            border-radius: 8px;
        }}
    </style>
</head>

<body>
    <div class="wrap">
        <header>
            <div class="eyebrow">AI Newsroom Studio</div>
            <h1>{page_title}</h1>
            <p class="subtitle">{subtitle}</p>
            <a class="back-link" href="https://github.com/AlgoDr/AI-Newsroom-Studio">&larr; back to the main repo</a>
            <a class="back-link" href="./{other_page}">{other_page_label} &rarr;</a>
        </header>

{cards}
        <footer>
            Generated by a 10-agent LangGraph pipeline \u2014 HackerNews trend
            detection through fact-checking, editorial selection, script
            writing, QC, and voice-over/video assembly, entirely autonomous.
            <br><br>
            Auto-generated from the {count} most recent real pipeline runs
            by <code>generate_demo_pages.py</code> \u2014 not hand-edited.
            <br><br>
            <a href="https://github.com/AlgoDr/AI-Newsroom-Studio">View the full project on GitHub</a>
        </footer>
    </div>
</body>
</html>
"""

EMPTY_STATE = """
        <div class="empty-note">
            No pipeline runs with saved metadata found yet. Run the pipeline
            through Agent 8 and the Output Organization step, then re-run
            this generator.
        </div>
"""


def generate_audio_page(runs_metadata, docs_dir):
    cards = []
    for meta in runs_metadata:
        if not meta.get("audio_filename"):
            continue
        script_text = meta.get("full_text") or "(script text not available for this run)"
        cards.append(AUDIO_CARD_TEMPLATE.format(
            n_stories=len(meta.get("story_titles", [])) or "?",
            title=_format_title([_escape_html(t) for t in meta.get("story_titles", [])]),
            audio_filename=meta["audio_filename"],
            script_text=_escape_html(script_text),
            word_count=meta.get("word_count") or "?",
            duration=_format_duration(meta.get("audio_duration_s")),
            qc_iterations=meta.get("qc_iterations") or "?",
            voice=meta.get("voice_used") or "af_heart (Kokoro-82M)",
        ))

    body = "".join(cards) if cards else EMPTY_STATE
    return PAGE_TEMPLATE.format(
        page_title="Voice-Over Samples",
        subtitle=("Real audio output from Agent 6.1, generated end-to-end by the "
                   "pipeline \u2014 Kokoro TTS running locally, from a script that was "
                   "researched, fact-checked, edited, written, and quality-checked "
                   "by the earlier agents with zero human editing."),
        other_page="video-showcase.html",
        other_page_label="Watch video samples",
        cards=body,
        count=len(cards),
    )


def generate_video_page(runs_metadata, docs_dir):
    cards = []
    for meta in runs_metadata:
        if not meta.get("video_filename"):
            continue
        cards.append(VIDEO_CARD_TEMPLATE.format(
            n_stories=len(meta.get("story_titles", [])) or "?",
            title=_format_title([_escape_html(t) for t in meta.get("story_titles", [])]),
            video_filename=meta["video_filename"],
            duration=_format_duration(meta.get("video_duration_s")),
            word_count=meta.get("word_count") or "?",
        ))

    body = "".join(cards) if cards else EMPTY_STATE
    return PAGE_TEMPLATE.format(
        page_title="Video Samples",
        subtitle=("Real video output from Agent 8, assembled end-to-end by the "
                   "pipeline \u2014 a PIL/ffmpeg reactive presenter graphic reacting "
                   "to the real voice-over audio, with source-citation lower-thirds, "
                   "entirely local and $0 by design."),
        other_page="audio-showcase.html",
        other_page_label="Listen to audio samples",
        cards=body,
        count=len(cards),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=5,
                         help="Number of most recent runs to include (default: 5)")
    parser.add_argument("--output-root", default=None,
                         help="Where organize_run_output() writes runs "
                              "(default: <project_root>/output, resolved from "
                              "this script's own location, NOT the caller's cwd)")
    parser.add_argument("--docs-dir", default=None,
                         help="Where to write the HTML + copy samples "
                              "(default: <project_root>/docs, resolved from "
                              "this script's own location, NOT the caller's cwd)")
    args = parser.parse_args()

    # PATCH (2026-07-14): only the default resolution changed -- explicit
    # --output-root/--docs-dir flags (if passed) still work exactly as
    # before, resolved relative to cwd. Only the *unset* case now
    # anchors to PROJECT_ROOT instead of a bare "output"/"docs" string.
    output_root = Path(args.output_root) if args.output_root else PROJECT_ROOT / "output"
    docs_dir = Path(args.docs_dir) if args.docs_dir else PROJECT_ROOT / "docs"

    print(f"Project root resolved to: {PROJECT_ROOT}")
    print(f"Reading runs from:        {output_root}")
    print(f"Writing showcase pages to: {docs_dir}")

    samples_dir = docs_dir / "samples"
    video_samples_dir = docs_dir / "video-samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    video_samples_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nScanning {output_root}/ for runs...")
    all_runs = list_runs(str(output_root))
    print(f"Found {len(all_runs)} total run(s), taking up to {args.count} most recent")

    runs_metadata = []
    for run_dir in all_runs[:args.count]:
        meta = _load_run_metadata(run_dir)
        if meta is None:
            continue

        if meta.get("audio_filename"):
            src = run_dir / meta["audio_filename"]
            if src.exists():
                shutil.copy2(src, samples_dir / meta["audio_filename"])
                print(f"  copied audio: {meta['audio_filename']}")
            else:
                print(f"  warning: {run_dir.name} metadata references "
                      f"{meta['audio_filename']} but that file is missing")
        if meta.get("video_filename"):
            src = run_dir / meta["video_filename"]
            if src.exists():
                # PATCH (2026-07-14): every run's metadata.json names its
                # video "final_video.mp4" (organize_run_output.py always
                # uses that name inside each timestamped folder) -- copying
                # verbatim into one flat video_samples_dir let a later run
                # silently overwrite an earlier one. Disambiguate using the
                # run folder's own (unique, timestamped) name instead.
                dest_name = f"{run_dir.name}.mp4"
                shutil.copy2(src, video_samples_dir / dest_name)
                meta["video_filename"] = dest_name  # HTML must reference the renamed copy
                print(f"  copied video: {dest_name}")
            else:
                print(f"  warning: {run_dir.name} metadata references "
                      f"{meta['video_filename']} but that file is missing")

        runs_metadata.append(meta)

    if not runs_metadata:
        print("No runs with usable metadata found -- generating empty-state pages.")

    audio_html = generate_audio_page(runs_metadata, docs_dir)
    video_html = generate_video_page(runs_metadata, docs_dir)

    (docs_dir / "audio-showcase.html").write_text(audio_html)
    (docs_dir / "video-showcase.html").write_text(video_html)

    print(f"\nWrote {docs_dir / 'audio-showcase.html'} ({len(runs_metadata)} sample(s))")
    print(f"Wrote {docs_dir / 'video-showcase.html'} ({len(runs_metadata)} sample(s))")


if __name__ == "__main__":
    main()