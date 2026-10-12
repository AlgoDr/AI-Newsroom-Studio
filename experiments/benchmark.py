"""
measure_chunk_boundary_silence.py -- Tier 1 validation, NOT assumption.

Question: does Kokoro's own generation already produce natural
trailing/leading silence at sentence boundaries (since every chunk
boundary in our pipeline IS a sentence boundary), or does concatenating
independently-generated chunks produce an unnaturally abrupt cut?

This does NOT assume an answer -- it generates two real sentences as
two SEPARATE Kokoro calls (matching our actual _generate_one_call()
pattern exactly), then measures the actual silence duration at the
tail of clip 1 and the head of clip 2 using amplitude thresholding.

Reference point: natural inter-sentence pauses in real human speech
and professional audiobook narration typically fall in the 150-400ms
range. If Kokoro's own output already lands in that range at chunk
boundaries, Tier 1 is a non-issue -- no code change needed. If it's
near-zero, the silence-insertion fix is justified by evidence, not
assumption.

Run standalone: python3 measure_chunk_boundary_silence.py
"""

import os
import sys
import glob
import shutil
import subprocess
import wave
import numpy as np

KOKORO_MODEL = "mlx-community/Kokoro-82M-bf16"
VOICE = "af_heart"
OUTPUT_DIR = "data/audio/_boundary_test"
SILENCE_AMPLITUDE_THRESHOLD = 500   # int16 scale; below this = "silence"

# two real sentences, deliberately picked to have a clean full-stop
# boundary between them -- same shape as a real chunk boundary
SENTENCE_1 = "The Ant Silver engine is hand-built, not a wrapper around V8, JSC, or SpiderMonkey."
SENTENCE_2 = "This means developers can run real npm packages instantly."


def _find_venv_python() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "multi-agent-env", "bin", "python3"),
        os.path.join(here, "..", "multi-agent-env", "bin", "python3"),
        os.path.join(here, "..", "..", "multi-agent-env", "bin", "python3"),
        os.environ.get("VIRTUAL_ENV", "") and os.path.join(os.environ["VIRTUAL_ENV"], "bin", "python3"),
        sys.executable,
    ]
    for c in candidates:
        if not c:
            continue
        c = os.path.abspath(c)
        if os.path.isfile(c):
            check = subprocess.run([c, "-c", "import mlx_audio"], capture_output=True)
            if check.returncode == 0:
                return c
    return sys.executable


PYTHON_BIN = _find_venv_python()
print(f"Using Python: {PYTHON_BIN}")


def generate_one(text: str, tag: str) -> str:
    """Exactly mirrors agent6_1.py's _generate_one_call() pattern."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for stray in glob.glob(os.path.join(OUTPUT_DIR, "audio_*.wav")):
        os.remove(stray)

    result = subprocess.run(
        [PYTHON_BIN, "-m", "mlx_audio.tts.generate",
         "--model", KOKORO_MODEL, "--text", text, "--voice", VOICE],
        cwd=OUTPUT_DIR, capture_output=True, text=True, timeout=60,
    )

    # ALWAYS show what actually happened -- this is exactly the visibility
    # gap that caused real confusion earlier in this project (KNOWN_ISSUES
    # pattern: never swallow subprocess output on failure)
    print(f"  returncode: {result.returncode}")
    if result.stdout.strip():
        print(f"  stdout: {result.stdout.strip()[-300:]}")
    if result.stderr.strip():
        print(f"  stderr: {result.stderr.strip()[-500:]}")

    produced = glob.glob(os.path.join(OUTPUT_DIR, "audio_*.wav"))
    if not produced:
        raise RuntimeError(f"no file produced for: {text!r} -- see returncode/stdout/stderr above")

    final = os.path.join(OUTPUT_DIR, f"{tag}.wav")
    shutil.move(produced[0], final)
    return final


def load_samples(path: str) -> tuple:
    with wave.open(path, "rb") as wf:
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        samples = np.frombuffer(frames, dtype=np.int16)
    return samples, rate


def measure_trailing_silence(samples: np.ndarray, rate: int) -> float:
    """Walk backward from the end, find where amplitude first exceeds
    the silence threshold. Returns silence duration in ms."""
    idx = len(samples) - 1
    while idx > 0 and abs(samples[idx]) < SILENCE_AMPLITUDE_THRESHOLD:
        idx -= 1
    silent_samples = len(samples) - 1 - idx
    return (silent_samples / rate) * 1000


def measure_leading_silence(samples: np.ndarray, rate: int) -> float:
    """Walk forward from the start, find where amplitude first exceeds
    the silence threshold. Returns silence duration in ms."""
    idx = 0
    while idx < len(samples) and abs(samples[idx]) < SILENCE_AMPLITUDE_THRESHOLD:
        idx += 1
    return (idx / rate) * 1000


def run_test():
    print("Generating two real Kokoro clips, exactly as the pipeline does...")
    path1 = generate_one(SENTENCE_1, "clip1")
    path2 = generate_one(SENTENCE_2, "clip2")

    samples1, rate1 = load_samples(path1)
    samples2, rate2 = load_samples(path2)

    trailing_ms = measure_trailing_silence(samples1, rate1)
    leading_ms = measure_leading_silence(samples2, rate2)
    total_gap_ms = trailing_ms + leading_ms

    print(f"\nClip 1 (\"{SENTENCE_1[:50]}...\")")
    print(f"  trailing silence at the END:  {trailing_ms:.0f} ms")

    print(f"\nClip 2 (\"{SENTENCE_2[:50]}...\")")
    print(f"  leading silence at the START: {leading_ms:.0f} ms")

    print(f"\n{'=' * 60}")
    print(f"TOTAL natural gap if concatenated with ZERO extra silence: {total_gap_ms:.0f} ms")
    print(f"Typical natural human inter-sentence pause: 150-400 ms")
    print(f"{'=' * 60}")

    if total_gap_ms >= 150:
        print("\nVERDICT: Kokoro's own output already provides a natural-range")
        print("gap at sentence boundaries. Tier 1's proposed fix (hardcoding")
        print("extra silence) is NOT needed -- would likely make it worse,")
        print("not better. No code change justified by this evidence.")
    elif total_gap_ms >= 50:
        print("\nVERDICT: Some natural gap exists but on the short side.")
        print(f"Consider inserting a SMALL top-up (~{max(0, 200-total_gap_ms):.0f}ms)")
        print("rather than a full 200ms — adding on top of what's already there.")
    else:
        print("\nVERDICT: Near-zero natural gap. The original Tier 1 concern")
        print("was justified — concatenation IS producing an abrupt cut.")
        print("A ~200ms insertion is reasonable here, backed by measurement.")


if __name__ == "__main__":
    run_test()