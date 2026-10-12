#!/usr/bin/env python3
"""
hindi_tts_from_checkpoint.py -- fun experiment, NOT part of the
production pipeline. Loads Agent 6's REAL checkpoint (till-agent6),
translates its actual tts_ready_text into Devanagari Hindi, then
generates real Hindi audio -- reusing the same mlx_audio/Kokoro
integration as production Agent 6.1.

WHY LOAD THE CHECKPOINT (vs. hardcoded Hindi text used in the earlier
version of this experiment): today's real script changes every run --
different stories, different word count, different content. Loading
till-agent6 means this test always uses whatever script actually went
through Agent 1-6 in your current session, not a stale copy-pasted
snapshot from an earlier conversation turn.

TRANSLATION NOTE: automated translation (Argos Translate) was tried
and abandoned earlier -- it pulls in spacy -> thinc -> blis, which
fails to build on Python 3.13 (blis/thinc don't support 3.13 yet).
This script's translate_to_hindi() is a placeholder you fill in
yourself (paste a translation from Claude, Google Translate, or a
working Argos Translate install in a Python 3.10-3.12 venv) -- see
the function's docstring for exactly what shape it needs to return.

CRITICAL: does NOT call agent6_1._sanitize_for_tts() on the Hindi
text -- that function strips all non-ASCII characters (ord(c) < 128)
and would silently delete every Devanagari character. See
agent6_1.py's own docstring (Bug 3) for why that function exists for
English text specifically.

Setup: none beyond what Agent 6.1 already needs --
    pip install mlx-audio misaki num2words phonemizer
    brew install espeak-ng

Usage (run from experiments/, so it can import agents/agent6_1.py and
agent_tools/pipeline_cache.py):
    python hindi_tts_from_checkpoint.py
    python hindi_tts_from_checkpoint.py --checkpoint till-agent6 --voice hf_beta
"""

import argparse
import os
import sys


# ---------------------------------------------------------------------
# SECTION 1: imports from the real, already-debugged production code
# ---------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Try both possible locations: script sits directly in experiments/
# (agents/ is a direct sibling), or script sits in the project root
# (agents/ is under experiments/agents/). Works regardless of which
# folder you actually saved this file into.
_candidate_agents_dirs = [
    os.path.join(SCRIPT_DIR, "agents"),
    os.path.join(SCRIPT_DIR, "experiments", "agents"),
    os.path.join(SCRIPT_DIR, "..", "agents"),  # script in a subfolder
                                                # (e.g. experiments/extras/)
                                                # that's a SIBLING of
                                                # agents/, not a parent
]
_candidate_tools_dirs = [
    os.path.join(SCRIPT_DIR, "agent_tools"),
    os.path.join(SCRIPT_DIR, "experiments", "agent_tools"),
    os.path.join(SCRIPT_DIR, "..", "agent_tools"),  # sibling-folder case
]

for _dir in _candidate_agents_dirs:
    if os.path.isdir(_dir):
        sys.path.insert(0, _dir)
        break
for _dir in _candidate_tools_dirs:
    if os.path.isdir(_dir):
        sys.path.insert(0, _dir)
        break

try:
    from agent6_1 import (
        _concatenate_wavs,
        _get_audio_duration,
        PYTHON_BIN,
        KOKORO_MODEL,
        OUTPUT_DIR,
        GENERATION_TIMEOUT,
    )
except ImportError as e:
    print(f"Could not import from agent6_1.py: {e}")
    print(f"Script location: {SCRIPT_DIR}")
    print(f"Searched for agents/ at: {_candidate_agents_dirs}")
    print("Neither location has agent6_1.py -- move this script into your "
          "project root or experiments/ folder, or adjust "
          "_candidate_agents_dirs above to point at the right place.")
    sys.exit(1)

import glob
import re
import shutil
import subprocess


def _split_hindi_text_for_tts(text: str, max_words: int = 40) -> list:
    """
    Hindi-aware variant of agent6_1._split_text_for_tts() -- splits on
    Devanagari sentence-ending punctuation (danda '।' and double danda
    '॥'), not just Latin '.', '!', '?'.

    REAL BUG THIS FIXES: a real test run using the original English-only
    splitter (regex `(?<=[.!?])\\s+`) produced only 2 giant chunks from
    a 186-word, ~10-sentence Hindi script -- because Hindi sentences end
    in '।', which that regex doesn't recognize as a boundary at all. The
    splitter fell back to only breaking on the rare literal '.'/'?'
    characters embedded from English loanwords (Xcode, API, etc), not
    real Hindi sentence boundaries. The resulting oversized chunks are
    the most likely cause of an audible 1.2s silence gap found via
    waveform analysis of that test's output, right at the chunk-1/
    chunk-2 stitch point -- concatenating two independently-generated
    long chunks can stack trailing/leading silence from each, whereas
    more, smaller, sentence-aligned chunks reduce how much of that
    per-chunk silence padding ends up audible in the final stitch.

    Deliberately a SEPARATE function from the original -- English text
    already works correctly with '.', '!', '?' as boundaries; forcing
    Hindi punctuation recognition into that same function for text that
    will never contain it adds complexity without benefit there.
    """
    # split on Hindi sentence-enders (।, ॥) OR Latin ones (.!?), keeping
    # the split point attached to the preceding sentence
    sentences = [s.strip() for s in re.split(r"(?<=[।॥.!?])\s+", text.strip()) if s.strip()]

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


def _generate_one_call_with_lang(text: str, voice: str, lang_code: str,
                                  chunk_index: int) -> list:
    """
    Hindi-aware variant of agent6_1._generate_one_call() -- adds
    --lang_code to the mlx_audio.tts.generate call, which the original
    production function never passes at all.

    REAL BUG THIS FIXES: without --lang_code, a real test run produced
    audio described as "Spanish pronounced by a Hindi person" --
    Hindi voice characteristics (pitch/timbre) applied via the wrong
    (likely default/English) phoneme path, since mlx_audio wasn't told
    which language's G2P rules to actually use for this text.
    Confirmed via `python -m mlx_audio.tts.generate --help`, which
    lists a real --lang_code LANG_CODE flag that agent6_1.py's
    _generate_one_call() silently never passes -- fine for English
    (apparently defaults correctly), NOT fine for Hindi.

    Deliberately a SEPARATE function rather than modifying
    agent6_1._generate_one_call() itself -- English voice-over already
    works correctly without this flag; adding it there risks
    regressing something proven, for a fix this experiment doesn't
    need there.

    Otherwise structurally identical to the original: same stray-file
    clearing (Bug 2 fix), same chunk-specific renaming, same
    silent-failure detection (Bug 3 pattern).
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
                "--lang_code", lang_code,
            ],
            cwd=OUTPUT_DIR,
            capture_output=True,
            text=True,
            timeout=GENERATION_TIMEOUT,
        )
        if result.returncode != 0:
            print(f"  [hindi-tts] generation failed for chunk: {result.stderr[:200]}")
            return []
    except subprocess.TimeoutExpired:
        print(f"  [hindi-tts] generation timed out after {GENERATION_TIMEOUT}s")
        return []
    except Exception as e:
        print(f"  [hindi-tts] generation error: {e}")
        return []

    produced = sorted(glob.glob(os.path.join(OUTPUT_DIR, "audio_*.wav")))
    if not produced:
        print(f"  [hindi-tts] chunk {chunk_index + 1}: mlx_audio exited "
              f"cleanly but produced no audio_*.wav file")
        print(f"  [hindi-tts] chunk {chunk_index + 1} text: {text!r}")
        return []

    renamed = []
    for j, path in enumerate(produced):
        new_name = os.path.join(OUTPUT_DIR, f"hindi_chunk_{chunk_index:03d}_{j:02d}.wav")
        shutil.move(path, new_name)
        renamed.append(new_name)
    return renamed

try:
    from pipeline_cache import load_checkpoint
except ImportError as e:
    print(f"Could not import from pipeline_cache.py: {e}")
    print(f"Searched for agent_tools/ at: {_candidate_tools_dirs}")
    sys.exit(1)


# ---------------------------------------------------------------------
# SECTION 2: load the real checkpoint
# ---------------------------------------------------------------------
def load_english_sections(checkpoint_name: str) -> dict:
    """
    Pulls state["script"]["sections"] from a real saved checkpoint --
    the actual script that went through Agent 1-6 this session, not a
    hardcoded snapshot.
    """
    print(f"[checkpoint] loading '{checkpoint_name}'...")
    state = load_checkpoint(checkpoint_name)

    sections = state.get("script", {}).get("sections")
    if not sections:
        raise ValueError(
            f"Checkpoint '{checkpoint_name}' has no state['script']['sections'] "
            f"-- pass a checkpoint from Agent 5 or later (till-agent5, "
            f"till-agent6, till-agent6_1, etc)."
        )

    word_count = state.get("script", {}).get("word_count", "?")
    print(f"[checkpoint]   {len(sections)} sections, {word_count} words\n")
    return sections


# ---------------------------------------------------------------------
# SECTION 3: translation -- YOU fill this in (see docstring)
# ---------------------------------------------------------------------
def translate_to_hindi(english_sections: dict) -> dict:
    """
    Translates each section's English text to Devanagari Hindi.

    PLACEHOLDER -- automated translation (Argos Translate) failed to
    build on Python 3.13 (see module docstring). Fill this dict in
    manually per run: paste each section's English text into Claude,
    Google Translate, or a working Argos Translate install elsewhere,
    then hardcode the results here, OR wire up a real translation call
    if you get one working (Argos in a 3.10-3.12 venv, a translation
    API, etc).

    MUST return a dict with the exact same keys as english_sections
    (HOOK, S1_CONTEXT, S1_CORE, ... CTA) so downstream code can stay
    section-aware. If you don't have a translation for a given run's
    exact section keys yet, this raises NotImplementedError rather
    than silently generating audio from untranslated English text.
    """
    # EXAMPLE from today's real till-agent6 checkpoint
    # (2026-07-14: Japan lithium / Xcode-free shipping / SpeechAnalyzer)
    # -- delete/replace this block once you have a translation for
    # YOUR current checkpoint's actual sections.
    known_translations = {
        "HOOK": "जापान ने हाल ही में एक ऐसी तकनीक विकसित की है जो इस्तेमाल की गई EV बैटरियों से 90% तक लिथियम वापस निकाल सकती है।",
        "S1_CONTEXT": "इलेक्ट्रिक वाहनों की लोकप्रियता जैसे-जैसे बढ़ रही है, पुरानी बैटरियों के निपटान के लिए बेहतर तरीके खोजने का दबाव भी बढ़ता जा रहा है।",
        "S1_CORE": "जापान के वैज्ञानिकों ने इस्तेमाल की गई EV बैटरियों से 90 प्रतिशत तक लिथियम निकालने की एक नई विधि विकसित की है।",
        "S1_TWIST": "यह एक बड़ी उपलब्धि है जो आने वाले वर्षों में EV बैटरियों के निर्माण और पुनः उपयोग के तरीके को बदल सकती है।",
        "S2_HOOK": "अब बात करते हैं, क्या आप बिना Xcode खोले Mac और iOS ऐप्स बना सकते हैं?",
        "S2_CORE": "डेवलपर्स xcodebuild, notarytool, और devicectl जैसे टूल्स का इस्तेमाल करके बिना Xcode खोले Mac और iOS ऐप्स बना सकते हैं।",
        "S2_TWIST": "इसका मतलब है कि अब आप बिना Xcode देखे भी अपनी मर्ज़ी से कोड लिख सकते हैं।",
        "S3_HOOK": "अब, Apple का नया SpeechAnalyzer API, Whisper मॉडल्स से बेहतर प्रदर्शन कर रहा है।",
        "S3_CORE": "SpeechAnalyzer ने साफ आवाज़ पर 2.12% और शोर वाली आवाज़ पर 4.56% की वर्ड-एरर-रेट हासिल की।",
        "S3_TWIST": "यह Whisper Small से लगभग तीन गुना तेज़ भी है, जो इसे सबसे सटीक ऑन-डिवाइस स्पीच इंजन बनाता है।",
        "CTA": "रोज़ाना टेक न्यूज़ के लिए फॉलो करें।",
    }

    missing = set(english_sections.keys()) - set(known_translations.keys())
    if missing:
        raise NotImplementedError(
            f"No Hindi translation available for section(s): {missing}. "
            f"This checkpoint's sections don't match the hardcoded "
            f"example translation in translate_to_hindi() -- you're "
            f"likely running against a different/newer checkpoint than "
            f"the one this placeholder was written for. Translate the "
            f"English text below yourself and update known_translations:\n"
            + "\n".join(f"  {k}: {english_sections[k]}" for k in missing)
        )

    hindi_sections = {name: known_translations[name] for name in english_sections}

    print("[translate] English -> Hindi (placeholder/manual translations):")
    for name in english_sections:
        print(f"  {name}:")
        print(f"    EN: {english_sections[name]}")
        print(f"    HI: {hindi_sections[name]}")
    print()

    return hindi_sections


# ---------------------------------------------------------------------
# SECTION 4: TTS generation -- reuses real Agent 6.1 building blocks
# ---------------------------------------------------------------------
def generate_hindi_audio(hindi_sections: dict, voice: str = "hf_alpha",
                          lang_code: str = "h",
                          output_path: str = "hindi_test.wav") -> dict:
    """
    Generates Hindi audio via the same mlx_audio subprocess call
    pattern as production Agent 6.1, chunked the same way, but:
      1. explicitly passes --lang_code (the real fix for the
         "sounds like Spanish spoken by a Hindi person" bug -- see
         _generate_one_call_with_lang()'s docstring)
      2. does NOT call _sanitize_for_tts() (would strip all
         Devanagari characters)

    Returns a stats dict, mirroring the shape of Agent 6.1's own
    result fields (audio_path, audio_duration, audio_chunks,
    chunks_skipped) for consistency with how the real pipeline reports
    results.
    """
    full_text = " ".join(hindi_sections.values())

    print(f"[tts] PYTHON_BIN: {PYTHON_BIN}")
    print(f"[tts] model:      {KOKORO_MODEL}")
    print(f"[tts] voice:      {voice}")
    print(f"[tts] lang_code:  {lang_code}")
    print(f"[tts] NOTE: skipping _sanitize_for_tts() -- would strip all "
          f"Devanagari characters (non-ASCII)\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    chunks = _split_hindi_text_for_tts(full_text)
    print(f"[tts] {len(hindi_sections)} sections -> {len(chunks)} chunk(s)\n")

    all_wav_paths = []
    skipped_chunks = []
    for i, chunk_text in enumerate(chunks):
        word_count = len(chunk_text.split())
        print(f"[tts] generating chunk {i+1}/{len(chunks)} ({word_count} words)...")

        wav_paths = _generate_one_call_with_lang(
            chunk_text, voice=voice, lang_code=lang_code, chunk_index=i
        )

        if not wav_paths:
            print(f"[tts] chunk {i+1}: produced no audio, skipping")
            print(f"[tts] chunk {i+1} text: {chunk_text!r}")
            skipped_chunks.append(i + 1)
            continue

        all_wav_paths.extend(wav_paths)

    result = {
        "audio_path": None,
        "audio_duration": 0.0,
        "audio_generated": False,
        "audio_chunks": len(all_wav_paths),
        "chunks_skipped": len(skipped_chunks),
        "voice_used": voice,
    }

    if not all_wav_paths:
        print("\n[tts] ERROR: no audio generated at all -- every chunk failed.")
        return result

    output_full_path = os.path.join(OUTPUT_DIR, output_path)
    print(f"\n[tts] stitching {len(all_wav_paths)} audio file(s)...")
    success = _concatenate_wavs(all_wav_paths, output_full_path)

    if not success:
        print("[tts] ERROR: concatenation failed.")
        return result

    duration = _get_audio_duration(output_full_path)
    result["audio_path"] = output_full_path
    result["audio_duration"] = duration
    result["audio_generated"] = True

    _cleanup_chunk_files(all_wav_paths)

    return result


def _cleanup_chunk_files(chunk_paths: list) -> None:
    """
    Deletes ONLY the intermediate chunk .wav files created by THIS run
    (the exact paths returned by _generate_one_call_with_lang() and
    collected into all_wav_paths above) -- never a blanket wipe of
    data/audio/, which also holds real production voiceover_*.wav
    files from actual pipeline runs that must NOT be touched.

    Called only AFTER the final stitched output file is confirmed
    written and its duration successfully read -- if concatenation had
    failed, this function is never reached, so the source chunks stay
    on disk for debugging rather than being deleted alongside a failed
    result.
    """
    print(f"\n[tts] cleaning up {len(chunk_paths)} intermediate chunk file(s)...")
    removed = 0
    for path in chunk_paths:
        try:
            os.remove(path)
            removed += 1
        except OSError as e:
            print(f"[tts]   could not remove {path}: {e}")
    print(f"[tts]   removed {removed}/{len(chunk_paths)} chunk file(s) "
          f"(final stitched output was kept)")


# ---------------------------------------------------------------------
# SECTION 5: orchestration
# ---------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", default="till-agent6",
                         help="Checkpoint to load (default: till-agent6)")
    parser.add_argument("--voice", default="hf_alpha",
                         help="Kokoro Hindi voice (default: hf_alpha). "
                              "Also try hf_beta, hm_omega, hm_psi.")
    parser.add_argument("--lang-code", default="h",
                         help="Language code passed to mlx_audio.tts.generate "
                              "(default: h for Hindi). This is the REAL FIX "
                              "for audio that sounds like the wrong language's "
                              "phonemes -- confirmed via a real test run.")
    parser.add_argument("--output", default="hindi_test.wav",
                         help="Output filename, saved inside data/audio/")
    args = parser.parse_args()

    english_sections = load_english_sections(args.checkpoint)
    hindi_sections = translate_to_hindi(english_sections)
    result = generate_hindi_audio(hindi_sections, voice=args.voice,
                                   lang_code=args.lang_code,
                                   output_path=args.output)

    print("\n" + "=" * 60)
    print("RESULT")
    print("=" * 60)
    print(f"audio_path:      {result['audio_path']}")
    print(f"audio_duration:  {result['audio_duration']:.1f}s")
    print(f"audio_generated: {result['audio_generated']}")
    print(f"audio_chunks:    {result['audio_chunks']}")
    print(f"chunks_skipped:  {result['chunks_skipped']}")
    print(f"voice_used:      {result['voice_used']}")


if __name__ == "__main__":
    main()