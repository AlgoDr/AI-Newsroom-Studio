"""
Agent 8 -- Video Assembler

Role: consume Agent 7's shot list + Agent 6.1's stitched audio, produce
the final MP4. Two visual modes, sharing all timing/audio/lower-third
logic:

  MODE "reactive" (default, proven -- see KNOWN_ISSUES ISSUE-20):
    Pure PIL/numpy rendered frames -- pulsing/glowing abstract "anchor"
    orb reacting to the audio's amplitude envelope, plus a waveform-bar
    indicator and source-citation lower-thirds. No ML model, no GPU,
    ~2 min render time for a full video on this hardware. This is what
    was actually prototyped and tested end-to-end today against a real
    83s pipeline audio file.

  MODE "broll" (scaffolded, NOT yet tested against a live API key):
    Fetches stock footage per shot_list entry's query from Pexels
    (primary) / Pixabay (fallback), trims/loops to each shot's duration,
    concatenates via ffmpeg, still burns the same lower-thirds on top.
    Requires PEXELS_API_KEY / PIXABAY_API_KEY env vars. Not exercised in
    this session -- no API key available in the dev sandbox. Treat as a
    first draft to validate against your own keys, not as proven code.

Output resolution: 1080x1920 (9:16), matching YouTube's actual
*recommended* Shorts spec -- upgraded from the 720x1280 minimum used in
the original prototype, per today's dimension research.
"""

# Real, importable version marker -- print(agent8.AGENT8_VERSION) or the
# "[agent8] running ..." line printed at the start of every
# video_assembler_node() call confirms which copy of this file actually
# executed. If your local numbers don't match the ones below, you're
# running a stale copy -- re-copy this exact file over
# experiments/agents/agent8.py.
AGENT8_VERSION = "v7-title-autofit-2026-07-14 (auto-shrinks title font to fit 2 lines instead of silently dropping overflow text; orb_r=260 bar_h=460)"

import math
import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import wave

W, H = 1080, 1920  # YouTube Shorts recommended (not just minimum) resolution
FPS = 30
BG_COLOR = (13, 17, 23)
ACCENT_COLOR = (88, 166, 255)
TEXT_COLOR = (201, 209, 217)
DIM_COLOR = (139, 148, 158)


# ---------------------------------------------------------------------
# Audio envelope (unchanged logic from today's prototype, confirmed
# working against real 83s pipeline audio)
# ---------------------------------------------------------------------
def get_amplitude_envelope(wav_path: str, fps: int = FPS) -> np.ndarray:
    with wave.open(wav_path, "rb") as wf:
        n_channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if n_channels == 2:
        audio = audio.reshape(-1, 2).mean(axis=1)

    duration = n_frames / sample_rate
    n_video_frames = max(1, int(duration * fps))
    samples_per_video_frame = len(audio) / n_video_frames

    envelope = np.zeros(n_video_frames)
    for i in range(n_video_frames):
        start = int(i * samples_per_video_frame)
        end = int((i + 1) * samples_per_video_frame)
        chunk = audio[start:end]
        if len(chunk) > 0:
            envelope[i] = np.sqrt(np.mean(chunk ** 2))

    if envelope.max() > 0:
        envelope = envelope / envelope.max()
    window = max(1, fps // 15)
    kernel = np.ones(window) / window
    envelope = np.convolve(envelope, kernel, mode="same")
    return np.clip(envelope, 0, 1)


def _load_font(size: int, bold: bool = False):
    """
    Cross-platform font loading. THE PREVIOUS VERSION OF THIS FUNCTION
    ONLY CHECKED A LINUX PATH -- on macOS it silently fell through to
    PIL's ImageFont.load_default(), which ignores the requested size
    entirely and always renders a tiny fixed-size bitmap font. This is
    the actual root cause of every "text still looks small" report
    despite repeatedly increasing the font size parameter -- the size
    was being silently discarded on macOS the whole time.

    Now checks real macOS system font paths first (since this project
    runs on an M4 Pro Mac), then Linux paths, then raises a loud error
    instead of silently degrading to an unreadable fallback -- a
    crashed render is more useful than a silently-wrong one.
    """
    macos_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",  # has both weights in one file
        "/System/Library/Fonts/Supplemental/Verdana Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Verdana.ttf",
    ]
    linux_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]

    for candidate in macos_candidates + linux_candidates:
        if Path(candidate).exists():
            font = ImageFont.truetype(candidate, size)
            # sanity check: confirm this actually IS a scalable font at
            # the requested size, not something that silently clamped
            measured_height = font.getbbox("Test")[3] - font.getbbox("Test")[1]
            expected_min_height = size * 0.4  # rough sanity floor
            if measured_height < expected_min_height:
                continue  # this candidate didn't actually scale -- try the next
            return font

    # No usable system font found on this machine at all -- fail loudly
    # rather than silently rendering unreadable tiny text again. Better
    # to crash with a clear message than repeat today's multi-hour
    # confusion a second time.
    raise RuntimeError(
        f"_load_font: no usable TrueType font found on this system "
        f"(checked {len(macos_candidates + linux_candidates)} known paths "
        f"for macOS and Linux). Falling back to PIL's default bitmap font "
        f"would silently ignore the requested size={size} and render "
        f"unreadably small text -- refusing to do that again. "
        f"Find a real .ttf/.ttc font file on this machine "
        f"(e.g. `find /System/Library/Fonts -iname '*.ttf' -o -iname '*.ttc'` "
        f"on macOS) and add its path to this function's candidate list."
    )


# ---------------------------------------------------------------------
# Shared visual elements -- used by BOTH modes, so lower-thirds look
# identical whether the background is the reactive orb or real footage
# ---------------------------------------------------------------------
def _fit_title_to_two_lines(text: str, max_width: int, start_size: int = 92,
                             min_size: int = 56, bold: bool = True) -> tuple:
    """
    Finds the largest font size (down to min_size) at which `text` wraps
    into 2 lines or fewer at max_width. Returns (font, lines).

    Root cause this fixes: a fixed 92px font + a hard title_lines[:2]
    truncation silently DROPPED any 3rd line of text for longer titles
    -- confirmed via a real render (title "Climate.gov was destroyed.
    Open data saved it" needs 3 lines at 92px; the old code rendered
    only "Climate.gov was" / "destroyed. Open" and silently discarded
    "data saved it" entirely, with no error, no log line, nothing to
    indicate content was lost). Shrinking the font to fit is strictly
    better than truncating -- readers see the whole title, just smaller,
    rather than a sentence that appears to end mid-word for no reason.

    Stops shrinking at min_size and accepts 3 lines rather than
    shrinking indefinitely -- an extremely long title still won't
    overflow silently, it'll just be smaller and possibly 3 lines,
    which is a visible tradeoff, not a silent one.
    """
    size = start_size
    while size >= min_size:
        font = _load_font(size, bold=bold)
        lines = _wrap_text(text, font, max_width=max_width)
        if len(lines) <= 2:
            return font, lines
        size -= 4
    # hit min_size and still >2 lines -- accept it rather than shrink
    # forever; this is a visible "smaller text, more lines" tradeoff,
    # not a silent drop
    font = _load_font(min_size, bold=bold)
    lines = _wrap_text(text, font, max_width=max_width)
    return font, lines


def _draw_source_lowerthird(img: Image.Image, source_domain: str | None,
                             story_title: str | None, fade_in: float = 1.0):
    if not story_title:
        return  # HOOK/CTA bookends: no per-story attribution to show
    draw = ImageDraw.Draw(img, "RGBA")
    bar_h = 460
    bar_y0 = H - bar_h
    # solid (not semi-transparent) backing bar -- semi-transparent text
    # over a busy background reads poorly on a small phone screen at a
    # glance, which is the actual viewing context for Shorts
    alpha = int(255 * fade_in)
    draw.rectangle([0, bar_y0, W, bar_y0 + bar_h], fill=(8, 10, 14, alpha))
    draw.rectangle([0, bar_y0, W, bar_y0 + 8], fill=ACCENT_COLOR + (alpha,))

    title_font, title_lines = _fit_title_to_two_lines(story_title, max_width=W - 96)
    source_font = _load_font(50)
    text_alpha = int(255 * fade_in)

    line_height = int(title_font.size * 1.15)
    y = bar_y0 + 55
    for line in title_lines:
        draw.text((48, y), line, font=title_font, fill=(255, 255, 255, text_alpha))
        y += line_height

    if source_domain:
        draw.text((48, bar_y0 + bar_h - 80), f"Source: {source_domain}",
                   font=source_font, fill=ACCENT_COLOR + (text_alpha,))


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    """Greedy word-wrap using the font's actual measured width, not a
    guessed character count -- avoids overflow on titles with wide
    characters (capitals, numerals) that a fixed char-count wrap would
    misjudge."""
    words = text.split()
    lines = []
    current = []
    for word in words:
        trial = " ".join(current + [word])
        bbox = font.getbbox(trial)
        width = bbox[2] - bbox[0]
        if width <= max_width or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def _draw_branding(draw: ImageDraw.Draw):
    font = _load_font(62, bold=True)
    small_font = _load_font(36)
    draw.text((48, 100), "AI NEWSROOM STUDIO", font=font, fill=ACCENT_COLOR + (255,))
    draw.text((48, 170), "autonomous \u00b7 zero human editing", font=small_font,
              fill=DIM_COLOR + (220,))


# ---------------------------------------------------------------------
# MODE: reactive (proven today)
# ---------------------------------------------------------------------
_BG_CACHE = None
ORB_CENTER_Y_OFFSET = -80  # orb sits slightly above true vertical center


def _make_background() -> Image.Image:
    global _BG_CACHE
    if _BG_CACHE is not None:
        return _BG_CACHE
    cx, cy = W // 2, H // 2 + ORB_CENTER_Y_OFFSET
    max_dist = math.hypot(W, H) * 0.6
    pixels = np.zeros((H, W, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:H, 0:W]
    dist = np.clip(np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / max_dist, 0, 1)
    lighter = np.array([22, 27, 34])
    darker = np.array(BG_COLOR)
    for c in range(3):
        pixels[:, :, c] = (lighter[c] * (1 - dist) + darker[c] * dist).astype(np.uint8)
    _BG_CACHE = Image.fromarray(pixels, "RGB")
    return _BG_CACHE


def _draw_anchor_graphic(draw: ImageDraw.Draw, cx: int, cy: int, amplitude: float, base_r: int = 260):
    for i in range(3, 0, -1):
        glow_r = base_r + i * 27 * (0.4 + amplitude)
        alpha = int(40 * amplitude / i)
        if alpha > 0:
            draw.ellipse([cx - glow_r, cy - glow_r, cx + glow_r, cy + glow_r],
                         fill=ACCENT_COLOR + (alpha,))
    core_r = base_r * (0.85 + 0.25 * amplitude)
    draw.ellipse([cx - core_r, cy - core_r, cx + core_r, cy + core_r],
                 fill=ACCENT_COLOR + (255,))
    inner_r = core_r * 0.55
    draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
                 outline=BG_COLOR + (255,), width=max(2, int(core_r * 0.06)))


def _draw_waveform_bars(draw: ImageDraw.Draw, cx: int, cy: int,
                         envelope_window: np.ndarray, bar_w=9, gap=7, max_h=105):
    n = len(envelope_window)
    total_w = n * (bar_w + gap) - gap
    x0 = cx - total_w // 2
    for i, amp in enumerate(envelope_window):
        h = max(6, int(amp * max_h))
        x = x0 + i * (bar_w + gap)
        draw.rounded_rectangle([x, cy - h // 2, x + bar_w, cy + h // 2],
                               radius=bar_w // 2, fill=ACCENT_COLOR + (200,))


def render_reactive_frame(frame_idx: int, envelope: np.ndarray, shot: dict,
                           segment_start_frame: int) -> Image.Image:
    amplitude = float(envelope[frame_idx]) if frame_idx < len(envelope) else 0.0
    img = _make_background().convert("RGBA").copy()
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_branding(draw)

    cx, cy = W // 2, H // 2 + ORB_CENTER_Y_OFFSET
    _draw_anchor_graphic(draw, cx, cy, amplitude)

    win_start = max(0, frame_idx - 19)
    window = envelope[win_start:frame_idx + 1]
    if len(window) < 20:
        window = np.pad(window, (20 - len(window), 0))
    _draw_waveform_bars(draw, cx, cy + 330, window)

    frames_into_segment = frame_idx - segment_start_frame
    fade = min(1.0, frames_into_segment / 15)
    _draw_source_lowerthird(img, shot["source_domain"], shot["story_title"], fade_in=fade)

    return img.convert("RGB")


# ---------------------------------------------------------------------
# MODE: broll (SCAFFOLDED, UNTESTED -- no API key in this session)
# ---------------------------------------------------------------------
def fetch_pexels_clip(query: str, api_key: str, min_duration_s: float) -> str | None:
    """
    Returns a local file path to a downloaded clip, or None if nothing
    usable was found. NOT EXERCISED in this session -- no PEXELS_API_KEY
    available. Written against Pexels' documented video search endpoint
    shape; verify against a live key before trusting this in production.
    """
    import requests  # local import: only needed for this untested path

    resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": api_key},
        params={"query": query, "per_page": 5, "orientation": "portrait"},
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json().get("videos", [])
    for video in results:
        if video.get("duration", 0) >= min_duration_s:
            # pick the highest-res portrait file under a sane size cap
            files = sorted(
                (f for f in video["video_files"] if f.get("width", 0) <= 1920),
                key=lambda f: f.get("width", 0),
                reverse=True,
            )
            if files:
                return files[0]["link"]  # caller downloads this URL
    return None  # no candidate met the duration requirement


def assemble_broll_mode(shot_list: list[dict], audio_path: str, output_path: str,
                         pexels_api_key: str | None = None) -> None:
    """
    NOT TESTED END-TO-END. Scaffolding for the stock-footage path,
    written to the same interface as assemble_reactive_mode so swapping
    modes is a one-line change once this is validated against a real
    API key. Left deliberately unfinished past the fetch step -- the
    ffmpeg concat/trim/mux logic should be copied from
    assemble_reactive_mode's pattern once fetch_pexels_clip is confirmed
    working, rather than writing untestable assembly code against an
    unverified fetch step.
    """
    raise NotImplementedError(
        "broll mode is scaffolded but not implemented past fetch_pexels_clip. "
        "Validate fetch_pexels_clip against a real PEXELS_API_KEY first -- "
        "see KNOWN_ISSUES for why 'reactive' is the current default mode."
    )


# ---------------------------------------------------------------------
# Assembly (reactive mode -- proven path)
# ---------------------------------------------------------------------
def assemble_reactive_mode(shot_list: list[dict], audio_path: str, output_path: str,
                            frames_dir: str = "frames_agent8") -> dict:
    """
    Renders every frame, then muxes against the real audio with ffmpeg.
    Returns a small dict of stats (frame count, render time) for the
    caller to log/verify -- mirrors today's monitor_memory.py habit of
    always getting a real number back rather than just "it ran."
    """
    import time

    envelope = get_amplitude_envelope(audio_path, fps=FPS)
    total_frames = len(envelope)

    out_dir = Path(frames_dir)
    # PATCH (2026-07-14): clear any leftover frames from a PREVIOUS run
    # before this run starts, rather than just mkdir(exist_ok=True) (which
    # only creates the folder if missing -- it does NOT clear existing
    # contents). Without this, a run with fewer frames than the previous
    # one (shorter audio) leaves the old run's trailing frames
    # (frame_02000.png onward, say) sitting on disk untouched, since this
    # run never writes those filenames -- silently mixing two runs'
    # frames in one folder. Deletion happens at the START of a new run,
    # not the end, so a crashed/interrupted run's partial frames remain
    # on disk for debugging until the next real run actually begins.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(exist_ok=True)

    # Map each frame index to the shot_list entry covering it, using
    # Agent 7's real start_s/end_s (not the word-share approximation the
    # standalone prototype used -- this is the actual upgrade Agent 8
    # brings over today's earlier PIL prototype).
    def shot_for_frame(frame_idx: int) -> dict:
        t = frame_idx / FPS
        for shot in shot_list:
            if shot["start_s"] <= t < shot["end_s"]:
                return shot
        return shot_list[-1]  # last shot covers any trailing rounding

    last_title = None
    segment_start_frame = 0
    start_time = time.time()

    for i in range(total_frames):
        shot = shot_for_frame(i)
        if shot["story_title"] != last_title:
            segment_start_frame = i
            last_title = shot["story_title"]
        frame = render_reactive_frame(i, envelope, shot, segment_start_frame)
        frame.save(out_dir / f"frame_{i:05d}.png")

    render_time = time.time() - start_time

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", str(out_dir / "frame_%05d.png"),
            "-i", audio_path,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            "-movflags", "+faststart",
            output_path,
        ],
        check=True,
        capture_output=True,
    )

    return {
        "total_frames": total_frames,
        "duration_s": total_frames / FPS,
        "render_time_s": round(render_time, 1),
        "output_path": output_path,
    }


def video_assembler_node(state: dict, mode: str = "reactive") -> dict:
    """
    LangGraph-style node wrapper. mode="reactive" is the only tested
    path -- see module docstring. Reads state["shot_list"] (Agent 7) and
    state["script"]["audio_path"] (Agent 6.1).

    Writes to data/video/ (working/intermediate location) -- see
    agent_tools/output_organization.py for moving a finished run into
    output/{run_id}/ as a separate, explicit step.
    """
    audio_path = state["script"]["audio_path"]
    shot_list = state["shot_list"]
    output_path = audio_path.replace("data/audio/", "data/video/").replace(".wav", ".mp4")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    print(f"[agent8] running {AGENT8_VERSION}")

    if mode == "reactive":
        stats = assemble_reactive_mode(shot_list, audio_path, output_path)
    elif mode == "broll":
        stats = assemble_broll_mode(shot_list, audio_path, output_path)
    else:
        raise ValueError(f"Unknown mode '{mode}', expected 'reactive' or 'broll'")

    print(f"[agent8] assembled video: {stats}")
    state["video_path"] = output_path
    state["video_stats"] = stats
    return state