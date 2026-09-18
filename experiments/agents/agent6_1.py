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

# Per-chunk voice fallback ladder. mlx-audio 0.4.4's Kokoro crashes with
# a broadcast_shapes ValueError inside istftnet for SPECIFIC
# (text-length, voice) combinations -- reproduced 2026-09-18: the same
# text rendered fine with af_nova but crashed with af_heart and
# af_bella. Retrying a doomed chunk with a different voice is the only
# reliable recovery for that failure class.
VOICE_FALLBACKS = {
    "af_heart": ["af_nova"],
    "af_bella": ["af_nova"],
    "af_nova":  ["af_heart"],
}
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


def _metal_preflight(timeout: int = 60) -> tuple:
    """Verify the MLX/Metal runtime actually works BEFORE attempting
    any TTS chunks (see KNOWN_ISSUES ISSUE-31).

    When the MLX metallib is missing/stale, mlx_audio dies as a native
    subprocess crash ("Failed to load the default metallib") -- every
    chunk then fails as a silent skip and the run produces zero audio
    with only confusing per-chunk messages. This check runs the SAME
    interpreter used for the real generation calls and fails fast with
    the exact reason, instead of N doomed chunk attempts.

    Returns (True, '') when Metal compute works, else (False, reason).
    """
    try:
        check = subprocess.run(
            [PYTHON_BIN, "-c",
             "import mlx.core as mx; assert (mx.array([1.0]) * 2).item() == 2.0"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"Metal preflight timed out after {timeout}s"
    except Exception as e:
        return False, f"Metal preflight could not run: {e}"

    if check.returncode == 0:
        return True, ""

    tail = (check.stderr or "").strip().splitlines()[-3:]
    reason = " | ".join(tail) if tail else f"exit code {check.returncode}"
    return False, reason
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


def _strip_wrapping_straight_quotes(text: str) -> str:
    """Strip a matching pair of straight single/double quotes wrapped
    around the whole text.

    Root cause of the 2026-09-18 first-chunk silent failure (no file,
    exit 0, no stderr): the LLM script was delivered as ONE string
    wrapped in literal straight single quotes
    ('Microsoft execs called ... admissions.'). Straight quotes are NOT
    in _sanitize_for_tts's substitution list (it only handles curly
    ' ' " " -- straight ASCII quotes were assumed harmless), and
    espeak-ng/misaki treat a leading ' as an unclosed quote marker and
    phonemize to nothing -> mlx_audio exits cleanly, writes no file.

    Only strips when the SAME quote char wraps the entire text, so
    legitimate in-sentence quotes ("he said \"hello\".") are untouched.
    """
    t = text.strip()
    for q in ("'", '"'):
        if len(t) >= 2 and t.startswith(q) and t.endswith(q):
            inner = t[1:-1].strip()
            # don't un-wrap when the quote is actually used inside
            # (e.g. an apostrophe pair, not a text wrapper)
            if q not in inner:
                return inner
    return t


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
        # mlx-audio 0.4.4 swallows internal exceptions and still exits 0,
        # so the real crash reason only lives in the captured output.
        tail = (result.stdout or "")[-300:].strip()
        errtail = (result.stderr or "")[-300:].strip()
        print(f"  [voiceover] chunk {chunk_index + 1}: mlx_audio exited "
              f"cleanly but produced no audio_*.wav file")
        if tail:
            print(f"  [voiceover] chunk {chunk_index + 1} stdout tail: {tail!r}")
        if errtail:
            print(f"  [voiceover] chunk {chunk_index + 1} stderr tail: {errtail!r}")
        print(f"  [voiceover] chunk {chunk_index + 1} text: {text!r}")
        return []

    renamed = []
    for j, path in enumerate(produced):
        new_name = os.path.join(OUTPUT_DIR, f"chunk_{chunk_index:03d}_{j:02d}.wav")
        shutil.move(path, new_name)
        renamed.append(new_name)

    return renamed


def _generate_audio(text: str, voice: str, _regen_done: bool = False) -> tuple:
    """Generate audio for the FULL text by:
      1. Stripping whole-text wrapper quotes, then pre-sanitizing
         (catches most problematic chars before they reach mlx_audio)
      2. Pre-splitting into safe-size chunks
      3. Generating each chunk with a clean directory + unique rename;
         wrapper quotes are also stripped per-chunk before first attempt
      4. On chunk failure: retry once with a FALLBACK VOICE (mlx-audio
         0.4.4 Kokoro deterministically crashes on specific
         text-length x voice pairs -- same-voice retries are futile),
         then once verbatim with the original voice (covers transient
         failures voice-switching can't fix)
      5. If all retries fail: SKIP the chunk, continue to next
         (partial audio is better than no audio)
      6. If any chunk needed a fallback voice: regenerate the WHOLE
         script with that fallback voice -- chunks with mismatched
         voices sound broken in one video; consistency wins
      7. Concatenating all successful chunks into one file

    Returns (final_path, audio_file_count, skipped_count);
    (None, 0, N) if ALL chunks fail.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # strip whole-text wrapper quotes, then sanitize -- catches the
    # 2026-09-18 failure where the LLM delivered the script wrapped in
    # literal straight quotes (leading quote kills espeak phonemization)
    sanitized_text = _sanitize_for_tts(_strip_wrapping_straight_quotes(text))

    text_chunks = _split_text_for_tts(sanitized_text)
    print(f"  [voiceover] split script into {len(text_chunks)} TTS-safe "
          f"text chunk(s) (max {MAX_WORDS_PER_CALL} words each)")

    all_audio_files = []
    skipped_chunks = []
    failed_voices = set()  # chunk indices that needed a fallback voice
    perturbed_chunks = False  # any chunk saved only by text perturbation

    for i, chunk_text in enumerate(text_chunks):
        chunk_word_count = len(chunk_text.split())
        print(f"  [voiceover] generating chunk {i + 1}/{len(text_chunks)} "
              f"({chunk_word_count} words)...")

        # strip wrapper quotes from THIS chunk before the first attempt
        # (whole-text strip can't catch per-section wrapping by the LLM)
        chunk_text = _strip_wrapping_straight_quotes(chunk_text)

        chunk_files = _generate_one_call(chunk_text, voice, chunk_index=i)

        if not chunk_files:
            # First recovery: retry with a DIFFERENT VOICE. mlx-audio
            # 0.4.4's Kokoro deterministically crashes on specific
            # (text-length, voice) pairs with a broadcast_shapes error
            # inside istftnet -- retrying the same voice is futile, but
            # a different voice renders the same text fine (verified
            # 2026-09-18: chunk 1 crashed on af_heart AND af_bella,
            # rendered fine on af_nova).
            for fb_voice in VOICE_FALLBACKS.get(voice, []):
                print(f"  [voiceover] chunk {i + 1}: {voice} failed -- "
                      f"retrying with fallback voice {fb_voice}...")
                chunk_files = _generate_one_call(chunk_text, fb_voice,
                                                  chunk_index=i)
                if chunk_files:
                    failed_voices.add(i)
                    break

        if not chunk_files:
            # Last resort: retry the ORIGINAL voice verbatim. Covers
            # transient failures (model loading, GPU contention) that
            # voice-switching can't fix.
            print(f"  [voiceover] chunk {i + 1}: retrying with original "
                  f"voice...")
            chunk_files = _generate_one_call(chunk_text, voice, chunk_index=i)

        if not chunk_files and not perturbed_chunks:
            # Text-perturbation retry: mlx-audio 0.4.4's Kokoro crashes
            # deterministically on specific (text-length, voice) pairs
            # for EVERY voice in the ladder. Changing the text length by
            # even one word moves the input out of the crash window.
            # Appending a short filler sentence is content-neutral for a
            # news script and adds a natural closing beat.
            print(f"  [voiceover] chunk {i + 1}: all voices failed -- "
                  f"retrying with perturbed text (length change escapes "
                  f"the crash window)...")
            perturbed_text = chunk_text.rstrip() + " And that is the latest."
            chunk_files = _generate_one_call(perturbed_text, voice,
                                              chunk_index=i)
            if not chunk_files:
                for fb_voice in VOICE_FALLBACKS.get(voice, []):
                    chunk_files = _generate_one_call(perturbed_text, fb_voice,
                                                      chunk_index=i)
                    if chunk_files:
                        failed_voices.add(i)
                        break
            if chunk_files:
                perturbed_chunks = True

        if not chunk_files:
            # skip this chunk -- don't abort the whole pipeline
            print(f"  [voiceover] chunk {i + 1}: skipping after all "
                  f"retries failed (partial audio will be generated "
                  f"without this chunk)")
            skipped_chunks.append(i + 1)
            continue

        all_audio_files.extend(chunk_files)

    if skipped_chunks:
        print(f"  [voiceover] {len(skipped_chunks)} chunk(s) skipped: "
              f"{skipped_chunks}")

    if not all_audio_files:
        print("  [voiceover] no audio files were generated (all chunks failed)")
        return None, 0

    # Consistency pass: if any chunk needed a fallback voice, the audio
    # would be stitched from mismatched voices -- audibly broken in one
    # video. Regenerate the WHOLE script with the fallback voice instead
    # (_regen_done prevents infinite recursion if the fallback voice
    # hits the same class of failure on other chunks).
    if failed_voices and not _regen_done:
        fb_voice = VOICE_FALLBACKS.get(voice, [voice])[0]
        print(f"  [voiceover] {len(failed_voices)} chunk(s) needed fallback "
              f"voice {fb_voice} -- regenerating the WHOLE script with "
              f"{fb_voice} for consistent audio...")
        fb_final, fb_count, fb_skipped = _generate_audio(text, fb_voice,
                                                          _regen_done=True)
        if fb_final:
            print(f"  [voiceover] whole-script regeneration with {fb_voice} "
                  f"succeeded ({fb_count} chunk(s), {fb_skipped} skipped)")
            return fb_final, fb_count, fb_skipped
        print("  [voiceover] whole-script regeneration failed -- keeping "
              "mixed-voice audio")

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

    # ISSUE-31: fail fast + loud when the MLX/Metal runtime is broken.
    # Without this, every chunk dies as a silent skip and the run
    # produces zero audio with only confusing per-chunk messages.
    metal_ok, metal_err = _metal_preflight()
    if not metal_ok:
        print("  [voiceover] FATAL: MLX/Metal runtime is broken -- "
              "skipping voice generation entirely")
        print(f"  [voiceover] preflight error: {metal_err}")
        print("  [voiceover] fix: reinstall the MLX metal backend in the "
              "pipeline venv, e.g.")
        print("    multi-agent-env/bin/pip install --force-reinstall "
              "--no-deps mlx-metal==0.32.0")
        print("  (full diagnosis: KNOWN_ISSUES.md ISSUE-31)")
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