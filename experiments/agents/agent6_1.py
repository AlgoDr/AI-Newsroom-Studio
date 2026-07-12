"""
agent6_1.py -- Voice-Over Generator (Kokoro / MLX)

Role: Convert Agent 6's QC'd tts_ready_text into actual voice-over audio,
      using Kokoro (via mlx-audio, Apple Metal GPU acceleration).

FIX HISTORY (bugs found via actual test runs):

  Bug 1 -- Kokoro truncating long single-call input: real testing
  showed inconsistent behavior on ~170-190 word single calls -- one
  run auto-split into 3 files (~26-28s each), another produced only
  1 file (~28.5s) covering roughly one story, silently dropping the
  rest with no error and exit code 0. Fixed by pre-splitting text
  into ~40-word chunks ourselves before ever calling Kokoro, rather
  than relying on its own internal (unreliable) chunking.

  Bug 2 -- filename collision between chunks: once pre-chunking was
  added, chunk 2 of 7 failed silently (no error printed, no exception
  -- the before/after file-diff just came back empty). Root cause:
  mlx_audio resets its own internal file counter on every fresh
  subprocess invocation, always starting from audio_000.wav. Fixed by
  clearing stray audio_*.wav files BEFORE each chunk call, and
  immediately renaming output to a unique chunk-specific filename after.

  Bug 3 -- silent chunk failure on certain text content: chunk 5 of 8
  (23 words, well under the 40-word ceiling) caused mlx_audio to exit
  0 with no output file and no error message. Root cause: mlx_audio/
  misaki/espeak-ng silently fails on certain Unicode characters --
  em dashes, smart quotes, ellipsis chars, markdown artifacts. Fixed by:
    a) NEW _sanitize_for_tts(): replaces known problematic chars with
       safe ASCII equivalents BEFORE each chunk call
    b) Retry once after sanitizing if first attempt produced no file
    c) SKIP the failed chunk rather than aborting the whole pipeline --
       partial audio covering most of the script is better than no audio
    d) Print the actual chunk text on failure so the cause is visible

Responsibilities:
  1. _split_text_for_tts()   -- pure Python, splits into TTS-safe chunks
  2. _sanitize_for_tts()     -- NEW: replaces chars that trip mlx_audio
  3. _generate_one_call()    -- clears stray files, calls mlx_audio,
                                renames output to unique chunk-specific name
  4. _generate_audio()       -- orchestrates 1-3, skip-not-abort on failure
  5. _concatenate_wavs()     -- pure Python WAV concatenation
  6. _get_audio_duration()   -- reads actual .wav duration
  7. _verify_duration()      -- sanity-checks duration vs word count
  8. voice_over_node()       -- LangGraph node, always sets all keys

What Agent 6.1 does NOT do:
  - Does not rewrite or QC text (Agent 6's job)
  - Does not add pause/emphasis markup (Kokoro can't render it --
    see KNOWN_ISSUES ISSUE-13)
  - Does not decide video scene timing (a future agent's job)
  - Does not run if Agent 6 has not approved the script

New state keys added (ALWAYS present after this node runs, even on
failure -- default values shown):
  state["script"]["audio_path"]        str | None   default None
  state["script"]["audio_duration"]    float        default 0.0
  state["script"]["audio_generated"]   bool         default False
  state["script"]["duration_verified"] bool         default False
  state["script"]["voice_used"]        str          default DEFAULT_VOICE
  state["script"]["audio_chunks"]      int          default 0
  state["script"]["chunks_skipped"]    int          default 0  (NEW)

Model: mlx-community/Kokoro-82M-bf16 via mlx_audio (Apple Metal GPU)
Cost: $0 -- fully local, no API key, no quota, no network dependency

Dependency chain required (see KNOWN_ISSUES ISSUE-12 for full details):
  pip install mlx-audio misaki num2words phonemizer
  brew install espeak-ng
"""

import os
import re
import sys
import glob
import shutil
import subprocess
import unicodedata
import wave
from datetime import datetime, timezone

KOKORO_MODEL         = "mlx-community/Kokoro-82M-bf16"
DEFAULT_VOICE        = "af_heart"
OUTPUT_DIR           = "data/audio"
WORDS_PER_SECOND     = 2.5
DURATION_TOLERANCE   = 0.5
GENERATION_TIMEOUT   = 120
MAX_WORDS_PER_CALL   = 40

# Resolve the correct Python interpreter at module load time.
# sys.executable alone is unreliable when Jupyter spawns subprocesses --
# it may point to the system Python rather than the active venv.
# Strategy: walk up from the current file's location to find the venv's
# python3, falling back to sys.executable if not found.
def _find_venv_python() -> str:
    """Find the venv Python that has mlx_audio installed."""
    import shutil
    candidates = [
        # explicit venv relative to project structure
        os.path.join(os.path.dirname(__file__), "..", "..", "multi-agent-env",
                     "bin", "python3"),
        os.path.join(os.path.dirname(__file__), "..", "multi-agent-env",
                     "bin", "python3"),
        # VIRTUAL_ENV env var (set by activate script)
        os.path.join(os.environ.get("VIRTUAL_ENV", ""), "bin", "python3"),
        # sys.executable as last resort
        sys.executable,
    ]
    for candidate in candidates:
        candidate = os.path.abspath(candidate)
        if os.path.isfile(candidate):
            # verify it actually has mlx_audio
            check = subprocess.run(
                [candidate, "-c", "import mlx_audio"],
                capture_output=True
            )
            if check.returncode == 0:
                return candidate
    return sys.executable   # give up, use whatever we have

PYTHON_BIN = _find_venv_python()


def _split_text_for_tts(text: str, max_words: int = MAX_WORDS_PER_CALL) -> list:
    """Split text into TTS-safe chunks, respecting sentence boundaries.
    Never splits mid-sentence."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    chunks = []
    current = []
    count = 0

    for sentence in sentences:
        word_count = len(sentence.split())
        if count + word_count > max_words and current:
            chunks.append(" ".join(current))
            current = []
            count = 0
        current.append(sentence)
        count += word_count

    if current:
        chunks.append(" ".join(current))

    return chunks


def _sanitize_for_tts(text: str) -> str:
    """Replace characters that cause mlx_audio/misaki/espeak-ng to exit
    cleanly but produce no output file.

    Observed in real run: chunk 5 of 8, 23 words, silent failure with
    exit code 0 and no error message -- the most common cause is
    Unicode typographic characters that espeak-ng's phonemizer cannot
    process (em dashes, smart quotes, ellipsis chars).

    All substitutions are phonetically neutral -- the text still reads
    naturally when spoken. This runs BEFORE every chunk call and also
    as a retry step when a chunk fails without error.
    """
    substitutions = [
        ("\u2014", " -- "),   # em dash
        ("\u2013", " - "),    # en dash
        ("\u2018", "'"),      # left single quote
        ("\u2019", "'"),      # right single quote
        ("\u201c", '"'),      # left double quote
        ("\u201d", '"'),      # right double quote
        ("\u2026", "..."),    # ellipsis character
        ("\u00b7", "."),      # middle dot
        ("\u2022", "."),      # bullet point
        ("*", ""),            # markdown bold/italic artifacts
        ("#", ""),            # markdown header artifacts
        ("__", ""),           # markdown underline artifacts
    ]
    for old, new in substitutions:
        text = text.replace(old, new)

    # catch any remaining non-ASCII characters that might trip espeak-ng
    # by normalizing to closest ASCII equivalent where possible
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if ord(c) < 128 or c in ".,!?;:'\"- ")

    # collapse any double spaces created by the substitutions
    text = re.sub(r"  +", " ", text).strip()
    return text


def _concatenate_wavs(wav_paths: list, output_path: str) -> bool:
    """Concatenate multiple .wav files into one, in the given order.
    Pure Python via the stdlib wave module."""
    if not wav_paths:
        return False
    try:
        with wave.open(wav_paths[0], "rb") as first:
            params = first.getparams()
            all_frames = [first.readframes(first.getnframes())]

        for path in wav_paths[1:]:
            with wave.open(path, "rb") as wf:
                all_frames.append(wf.readframes(wf.getnframes()))

        with wave.open(output_path, "wb") as out:
            out.setparams(params)
            for frames in all_frames:
                out.writeframes(frames)
        return True
    except Exception as e:
        print(f"  [voiceover] concatenation failed: {e}")
        return False


def _generate_one_call(text: str, voice: str, chunk_index: int) -> list:
    """Run mlx_audio.tts.generate ONCE for a single text chunk.

    Clears any stray audio_*.wav files BEFORE running to prevent
    filename collisions (see Bug 2 in module docstring). Immediately
    renames output to a unique chunk-specific filename.

    Returns list of audio file paths, or empty list on failure.
    """
    for stray in glob.glob(os.path.join(OUTPUT_DIR, "audio_*.wav")):
        try:
            os.remove(stray)
        except OSError:
            pass

    try:
        result = subprocess.run(
            [
                PYTHON_BIN, "-m", "mlx_audio.tts.generate",
                "--model", KOKORO_MODEL,
                "--text", text,
                "--voice", voice,
            ],
            cwd=OUTPUT_DIR,
            capture_output=True,
            text=True,
            timeout=GENERATION_TIMEOUT,
        )
        if result.returncode != 0:
            print(f"  [voiceover] generation failed for chunk: {result.stderr[:200]}")
            return []
    except subprocess.TimeoutExpired:
        print(f"  [voiceover] generation timed out after {GENERATION_TIMEOUT}s")
        return []
    except Exception as e:
        print(f"  [voiceover] generation error: {e}")
        return []

    produced = sorted(glob.glob(os.path.join(OUTPUT_DIR, "audio_*.wav")))
    if not produced:
        print(f"  [voiceover] chunk {chunk_index + 1}: mlx_audio exited "
              f"cleanly but produced no audio_*.wav file")
        print(f"  [voiceover] chunk {chunk_index + 1} text: {text!r}")
        return []

    renamed = []
    for j, path in enumerate(produced):
        new_name = os.path.join(OUTPUT_DIR, f"chunk_{chunk_index:03d}_{j:02d}.wav")
        shutil.move(path, new_name)
        renamed.append(new_name)

    return renamed


def _generate_audio(text: str, voice: str) -> tuple:
    """Generate audio for the FULL text by:
      1. Pre-sanitizing the full text (catches most problematic chars
         before they ever reach mlx_audio)
      2. Pre-splitting into safe-size chunks
      3. Generating each chunk with a clean directory + unique rename
      4. On chunk failure: retry once with extra sanitization
      5. If retry also fails: SKIP the chunk, continue to next
         (partial audio is better than no audio)
      6. Concatenating all successful chunks into one file

    Returns (final_path, audio_file_count) or (None, 0) if ALL chunks fail.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # sanitize the whole text first -- catches most issues before chunking
    sanitized_text = _sanitize_for_tts(text)

    text_chunks = _split_text_for_tts(sanitized_text)
    print(f"  [voiceover] split script into {len(text_chunks)} TTS-safe "
          f"text chunk(s) (max {MAX_WORDS_PER_CALL} words each)")

    all_audio_files = []
    skipped_chunks = []

    for i, chunk_text in enumerate(text_chunks):
        chunk_word_count = len(chunk_text.split())
        print(f"  [voiceover] generating chunk {i + 1}/{len(text_chunks)} "
              f"({chunk_word_count} words)...")

        chunk_files = _generate_one_call(chunk_text, voice, chunk_index=i)

        if not chunk_files:
            # retry with an even more aggressive sanitization pass
            # (the full-text sanitize above may have missed something
            # that only becomes obvious per-chunk)
            retry_text = _sanitize_for_tts(chunk_text)
            if retry_text != chunk_text:
                print(f"  [voiceover] chunk {i + 1}: retrying with "
                      f"additional sanitization...")
                chunk_files = _generate_one_call(retry_text, voice,
                                                  chunk_index=i)

        if not chunk_files:
            # skip this chunk -- don't abort the whole pipeline
            print(f"  [voiceover] chunk {i + 1}: skipping after retry "
                  f"failed (partial audio will be generated without this chunk)")
            skipped_chunks.append(i + 1)
            continue

        all_audio_files.extend(chunk_files)

    if skipped_chunks:
        print(f"  [voiceover] {len(skipped_chunks)} chunk(s) skipped: "
              f"{skipped_chunks}")

    if not all_audio_files:
        print("  [voiceover] no audio files were generated (all chunks failed)")
        return None, 0

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    final_path = os.path.join(OUTPUT_DIR, f"voiceover_{timestamp}.wav")

    if len(all_audio_files) == 1:
        shutil.move(all_audio_files[0], final_path)
        return final_path, 1, len(skipped_chunks)

    print(f"  [voiceover] stitching {len(all_audio_files)} audio files "
          f"into one continuous file")
    success = _concatenate_wavs(all_audio_files, final_path)
    if not success:
        return None, 0, len(skipped_chunks)

    for f in all_audio_files:
        try:
            os.remove(f)
        except OSError:
            pass

    return final_path, len(all_audio_files), len(skipped_chunks)


def _get_audio_duration(audio_path: str) -> float:
    """Read the actual duration of a generated .wav file in seconds."""
    try:
        with wave.open(audio_path, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return round(frames / float(rate), 2)
    except Exception as e:
        print(f"  [voiceover] could not read duration: {e}")
        return 0.0


def _verify_duration(actual_seconds: float, word_count: int) -> bool:
    """Sanity-check: does the generated audio's actual duration roughly
    match what the word count predicts?"""
    expected_seconds = word_count / WORDS_PER_SECOND
    if expected_seconds == 0:
        return False

    ratio = actual_seconds / expected_seconds
    within_tolerance = (1 - DURATION_TOLERANCE) <= ratio <= (1 + DURATION_TOLERANCE)

    print(f"  [voiceover] expected ~{expected_seconds:.1f}s, got "
          f"{actual_seconds:.1f}s "
          f"({'within tolerance' if within_tolerance else 'MISMATCH'})")

    return within_tolerance


def voice_over_node(state: dict, voice: str = DEFAULT_VOICE) -> dict:
    """LangGraph node -- generates production voice-over audio from
    Agent 6's QC'd tts_ready_text. Only runs if Agent 6 approved.

    ALWAYS sets every state["script"][...] key this node owns on every
    code path including failures -- downstream code can never KeyError.
    """
    script = state.get("script", {})
    state.setdefault("script", {})

    # safe defaults -- set up front, overwritten only on success paths
    state["script"].setdefault("audio_path", None)
    state["script"].setdefault("audio_duration", 0.0)
    state["script"].setdefault("audio_generated", False)
    state["script"].setdefault("duration_verified", False)
    state["script"].setdefault("voice_used", voice)
    state["script"].setdefault("audio_chunks", 0)
    state["script"].setdefault("chunks_skipped", 0)

    print("=" * 70)
    print("AGENT 6.1: Voice-Over Generator (Kokoro)")
    print("=" * 70)

    if not script.get("approved", False):
        print("  [voiceover] script not approved by Agent 6 -- skipping")
        return state

    tts_text = script.get("tts_ready_text", "")
    if not tts_text.strip():
        print("  [voiceover] tts_ready_text is empty -- nothing to synthesize")
        return state

    total_words = len(tts_text.split())
    print(f"  [voiceover] generating audio ({total_words} words total)...")

    result = _generate_audio(tts_text, voice)

    # _generate_audio returns 3-tuple or (None, 0) on total failure
    if result[0] is None:
        print("  [voiceover] generation failed")
        return state

    audio_path, chunk_count, chunks_skipped = result

    duration = _get_audio_duration(audio_path)
    word_count = script.get("word_count", total_words)
    duration_ok = _verify_duration(duration, word_count)

    state["script"]["audio_path"]        = audio_path
    state["script"]["audio_duration"]    = duration
    state["script"]["audio_generated"]   = True
    state["script"]["duration_verified"] = duration_ok
    state["script"]["voice_used"]        = voice
    state["script"]["audio_chunks"]      = chunk_count
    state["script"]["chunks_skipped"]    = chunks_skipped

    print(f"\n  [voiceover] audio generated")
    print(f"  [voiceover]    path:          {audio_path}")
    print(f"  [voiceover]    duration:      {duration}s")
    print(f"  [voiceover]    files stitched: {chunk_count}")
    print(f"  [voiceover]    chunks skipped: {chunks_skipped}")
    print(f"  [voiceover]    voice:          {voice}")
    print(f"  [voiceover]    verified:       {duration_ok}")

    return state