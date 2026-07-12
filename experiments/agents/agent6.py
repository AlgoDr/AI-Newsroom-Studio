"""
agent6.py -- Script QC Agent

Role: Validate and polish Agent 5's script until it is genuinely ready
      for voice-over generation -- fixing format violations surgically
      and adding the human voice Agent 5 was never asked to have.

Two-stage model split:
  JUDGE   (openai/gpt-oss-120b)       -- reasoning-tuned, finds problems
  REWRITE (llama-3.3-70b-versatile)   -- creative fluency, fixes ONLY
                                         what was flagged, never the
                                         whole script

TTS-readiness (dense alphanumeric identifiers, e.g. firmware version
strings like "US_FH1201V1.0BR_V1.2.0.14") is detected via pure Python
regex and merged DIRECTLY into the same rewrite loop as human-voice/
transition/twist issues -- real testing showed Kokoro badly rushing
through such strings (a 192-word script generated ~28s of audio
against a ~77s estimate) when this was left as advisory-only logging
instead of actually driving a rewrite.

New state keys added:
  state["script"]["approved"]        bool
  state["script"]["qc_notes"]        list[str]  audit trail
  state["script"]["annotated_text"]  str        has [BEAT]/[EMPHASIS] markers
  state["script"]["tts_ready_text"]  str        clean, for Agent 6.1
  state["script"]["cta_category"]    str        "A" / "B" / "C"
  state["script"]["iterations"]      int        1 or 2
"""

import os
import re
import dotenv
import ollama
from datetime import datetime, timezone
from groq import Groq

dotenv.load_dotenv(".env")

JUDGE_MODEL             = "openai/gpt-oss-120b"
REWRITE_MODEL           = "llama-3.3-70b-versatile"
JUDGE_FALLBACK_MODEL    = "qwen2.5:7b"
REWRITE_FALLBACK_MODEL  = "gemma3:12b"
TARGET_MIN      = 150
TARGET_MAX      = 225
MAX_ITERATIONS  = 2

SECTION_ORDER = [
    "HOOK", "S1_CONTEXT", "S1_CORE", "S1_TWIST",
    "S2_HOOK", "S2_CORE", "S2_TWIST",
    "S3_HOOK", "S3_CORE",
    "CTA",
]

BEAT_AFTER = {"S1_TWIST", "S2_TWIST"}

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

DATE_PATTERN = re.compile(
    r"\b(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b",
    re.IGNORECASE,
)

groq_client = Groq(api_key=os.getenv("GROQ_KEY"))


def _humanize_dates(text: str) -> str:
    """Convert absolute dates to relative human phrasing using the REAL
    current date. Pure Python -- no LLM call, no guessing."""
    today = datetime.now(timezone.utc)

    def _replace(match) -> str:
        month_name, day, year = match.groups()
        month_num = MONTH_NAMES.get(month_name.lower())
        if not month_num:
            return match.group(0)
        try:
            date_obj = datetime(int(year), month_num, int(day), tzinfo=timezone.utc)
        except ValueError:
            return match.group(0)

        delta_days = (today - date_obj).days

        if delta_days < 0:
            return match.group(0)
        elif delta_days == 0:
            return "today"
        elif delta_days == 1:
            return "yesterday"
        elif delta_days < 7:
            return f"{delta_days} days ago"
        elif delta_days < 14:
            return "last week"
        elif delta_days < 30:
            return f"{delta_days // 7} weeks ago"
        elif delta_days < 60:
            return "last month"
        elif delta_days < 365:
            return f"{delta_days // 30} months ago"
        elif delta_days < 545:
            return "last year"
        elif delta_days < 730:
            return "almost two years ago"
        else:
            return f"{delta_days // 365} years ago"

    return DATE_PATTERN.sub(_replace, text)


def _scan_tts_readiness(sections: dict) -> dict:
    """Detect patterns that will cause Kokoro to garble or rush through
    audio, PER SECTION. Returns {label: reason}. Pure Python (regex),
    never asked of an LLM."""
    warnings = {}
    for label, text in sections.items():
        reasons = []
        if re.search(r"\*\*|__|#{1,6}\s", text):
            reasons.append("markdown artifacts (**, #, __) will be read literally")
        if re.search(r"\b[A-Z]{2,}_[A-Z0-9._]+\b", text):
            reasons.append(
                "contains a dense alphanumeric identifier (e.g. a firmware "
                "version string) that text-to-speech will garble or rush "
                "through unnaturally -- simplify to a natural spoken phrase "
                "(e.g. 'several firmware versions' instead of listing exact "
                "version codes); keep short identifiers like CVE numbers, "
                "they read fine aloud"
            )
        if reasons:
            warnings[label] = "; ".join(reasons)
    return warnings


def _judge_script(script: dict) -> dict:
    """Stage 1 -- gpt-oss-120b judges every QC dimension in one call.
    Word count and TTS-readiness are pure Python and merged in after."""
    sections = script["sections"]
    word_count = script.get("word_count", 0)

    sections_text = "\n".join(f"{label}: {content}" for label, content in sections.items())

    word_count_ok = TARGET_MIN <= word_count <= TARGET_MAX
    section_labels = list(sections.keys())

    prompt = f"""You are a strict script editor reviewing a YouTube Shorts script
before it becomes voice-over audio.

SCRIPT SECTIONS (these are the ONLY valid section labels -- do not
invent or reference any other label):
{sections_text}

Valid section labels for this script: {", ".join(section_labels)}

Check each of these:
1. HUMAN_VOICE: does any section sound like an AI press release (vague
   quality adjectives, hedging like "can generate", marketing phrases
   like "ensures maximum")? List exact flagged section labels -- ONLY
   from the valid labels list above.
2. TRANSITIONS: for S2_HOOK and S3_HOOK, does each (a) signal the
   previous story is complete and (b) open the next with tension, not
   explanation? List any that fail.
3. TWIST: for each twist-type section present in the valid labels list
   above -- does it reveal a NEW consequence, or just restate the CORE
   fact in different words? List any that just restate.
4. CTA: classify into category A (follow/subscribe), B (comment/
   engage), or C (discover/link). Is it under 10 words and imperative?

Respond in EXACTLY this format, one line per item, no extra text.
Only use labels from the valid list above -- never invent a label:
FLAGGED_SECTIONS: <comma-separated labels from the valid list, or NONE>
FLAGGED_REASONS: <one reason per flagged section, separated by |>
CTA_CATEGORY: A or B or C or INVALID
CTA_OK: YES or NO"""

    raw = ""
    try:
        resp = groq_client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1200,
        )
        raw = (resp.choices[0].message.content or "").strip()
        finish_reason = resp.choices[0].finish_reason
        if not raw:
            print(f"  [qc] JUDGE empty content, finish_reason={finish_reason}")
    except Exception as e:
        print(f"  [qc] JUDGE (gpt-oss-120b) call failed: {e}")


    if not raw:
        print("  [qc] JUDGE empty/failed on gpt-oss-120b -> "
              f"falling back to local {JUDGE_FALLBACK_MODEL}")
        raw = _judge_script_local(prompt)

    print(f"  [qc] JUDGE raw: {raw[:150] if raw else '(still empty after fallback)'}")

    if not raw:
        print("  [qc] JUDGE failed on both cloud and local -- defaulting to all-pass")
        judgment = _default_judgment_pass()
    else:
        judgment = _parse_judgment(raw, valid_labels=section_labels)

    judgment["word_count_ok"] = word_count_ok
    if word_count_ok:
        judgment["word_count_action"] = "none"
        judgment["word_count_section"] = None
    elif judgment["word_count_action"] == "none":
        judgment["word_count_action"] = "trim" if word_count > TARGET_MAX else "expand"
        longest = max(sections, key=lambda k: len(sections[k].split()))
        shortest = min(sections, key=lambda k: len(sections[k].split()))
        judgment["word_count_section"] = longest if word_count > TARGET_MAX else shortest

    tts_issues = _scan_tts_readiness(sections)
    for label, reason in tts_issues.items():
        if label in judgment["flagged_sections"]:
            judgment["flagged_sections"][label] += f"; {reason}"
        else:
            judgment["flagged_sections"][label] = reason
    if tts_issues:
        print(f"  [qc] TTS-readiness issues found in: {list(tts_issues.keys())}")

    return judgment


def _judge_script_local(prompt: str) -> str:
    """Local fallback for the JUDGE stage -- qwen2.5:7b via Ollama."""
    try:
        resp = ollama.generate(
            model=JUDGE_FALLBACK_MODEL,
            prompt=prompt,
            stream=False,
            keep_alive=0,
            options={"temperature": 0.1, "num_ctx": 4096},
        )
        return (resp.get("response") or "").strip()
    except Exception as e:
        print(f"  [qc] local JUDGE fallback also failed: {e}")
        return ""


def _parse_judgment(raw: str, valid_labels: list = None) -> dict:
    """Parse the JUDGE model's structured text response into a dict."""
    valid_labels = valid_labels or []
    try:
        lines = {}
        for line in raw.split("\n"):
            if ":" in line:
                key, _, val = line.partition(":")
                lines[key.strip().upper()] = val.strip()

        flagged_raw = lines.get("FLAGGED_SECTIONS", "NONE")
        reasons_raw = lines.get("FLAGGED_REASONS", "")
        flagged_sections = {}
        if flagged_raw.upper() != "NONE" and flagged_raw.strip():
            labels = [l.strip() for l in flagged_raw.split(",") if l.strip()]
            reasons = [r.strip() for r in reasons_raw.split("|") if r.strip()] if reasons_raw else []

            for i, label in enumerate(labels):
                if valid_labels and label not in valid_labels:
                    print(f"  [qc] ignoring hallucinated section label: {label}")
                    continue
                reason = reasons[i] if i < len(reasons) else "flagged by QC judge"
                flagged_sections[label] = reason

        cta_category = lines.get("CTA_CATEGORY", "A").strip().upper()
        if cta_category not in ("A", "B", "C"):
            cta_category = "INVALID"
        cta_ok = lines.get("CTA_OK", "YES").upper().startswith("Y")

        return {
            "word_count_ok": True,
            "word_count_action": "none",
            "word_count_section": None,
            "flagged_sections": flagged_sections,
            "cta_category": cta_category,
            "cta_ok": cta_ok,
        }
    except Exception as e:
        print(f"  [qc] judgment parse failed ({e}) -- defaulting to all-pass")
        return _default_judgment_pass()


def _default_judgment_pass() -> dict:
    """Safe fallback judgment -- approves everything as-is."""
    return {
        "word_count_ok": True,
        "word_count_action": "none",
        "word_count_section": None,
        "flagged_sections": {},
        "cta_category": "A",
        "cta_ok": True,
    }


def _rewrite_flagged(script: dict, judgment: dict) -> dict:
    """Stage 2 -- llama-3.3-70b-versatile rewrites ONLY flagged sections."""
    sections = dict(script["sections"])

    to_fix = {}

    if judgment["word_count_action"] != "none" and judgment["word_count_section"]:
        sec = judgment["word_count_section"]
        action = judgment["word_count_action"]
        to_fix[sec] = (
            f"{action} this section. Keep total script between "
            f"{TARGET_MIN} and {TARGET_MAX} words overall. Add or remove "
            f"ONE specific detail -- never pad with filler."
        )

    for sec, reason in judgment["flagged_sections"].items():
        to_fix[sec] = (
            f"Rewrite this section. Problem: {reason}. Keep all facts. "
            f"Use natural spoken English, no AI-press-release phrasing."
        )

    if not judgment["cta_ok"]:
        cat = judgment["cta_category"] if judgment["cta_category"] != "INVALID" else "A, B, or C"
        to_fix["CTA"] = (
            f"Rewrite the CTA. Must be under 10 words, imperative mood, "
            f"and fit category {cat} "
            f"(A=follow/subscribe, B=comment/engage, C=discover/link)."
        )

    if not to_fix:
        return sections

    fix_blocks = "\n\n".join(
        f'SECTION {label}:\nCurrent text: "{sections.get(label, "")}"\nInstruction: {instr}'
        for label, instr in to_fix.items()
    )

    prompt = f"""Rewrite ONLY the sections below. Do not touch any other
part of the script. Keep every fact, number, CVE ID, and name exactly
as given -- only change phrasing, length, or structure as instructed.

{fix_blocks}

For any section containing a strong directive or warning (e.g. "disable
X now", "no patch exists"), end it with the key action as its OWN short
sentence so it lands with natural vocal stress when spoken aloud.
Example: "Disable remote management on your Tenda router. Right now."

Return ONLY in this format, one section per line:
SECTION_LABEL: rewritten text"""

    raw = ""
    try:
        resp = groq_client.chat.completions.create(
            model=REWRITE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=500,
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"  [qc] REWRITE (llama-3.3-70b) call failed: {e}")

    if not raw:
        print("  [qc] REWRITE empty/failed on Groq -> "
              f"falling back to local {REWRITE_FALLBACK_MODEL}")
        raw = _rewrite_flagged_local(prompt)
        print(f"  [qc] local REWRITE raw: {raw[:150] if raw else '(empty)'}")

    if not raw:
        print("  [qc] REWRITE failed on both cloud and local -- keeping original sections")
        return sections

    rewritten = _parse_rewrite_output(raw)

    if not rewritten:
        print(f"  [qc] rewrite call succeeded but produced 0 parseable "
              f"sections -- raw output may not match 'LABEL: text' format")
        print(f"  [qc] rewrite raw (first 200 chars): {raw[:200]!r}")

    for label, new_text in rewritten.items():
        if label in sections:
            sections[label] = new_text
            print(f"  [qc] rewrote {label}")
        else:
            print(f"  [qc] rewrite produced unknown label '{label}' -- ignored")

    return sections


def _parse_rewrite_output(raw: str) -> dict:
    """Parse the REWRITE model's 'LABEL: text' formatted output.
    Tolerates a "SECTION " prefix some models add despite instructions
    not to -- strips it so the label still matches a real section key."""
    result = {}
    for line in raw.split("\n"):
        if ":" in line:
            label, _, text = line.partition(":")
            label = label.strip().upper()
            if label.startswith("SECTION "):
                label = label[len("SECTION "):].strip()
            text = text.strip().strip('"')
            if label and text:
                result[label] = text
    return result


def _rewrite_flagged_local(prompt: str) -> str:
    """Local fallback for the REWRITE stage -- gemma2:9b via Ollama."""
    try:
        resp = ollama.generate(
            model=REWRITE_FALLBACK_MODEL,
            prompt=prompt,
            stream=False,
            keep_alive=0,
            options={"temperature": 0.4, "num_ctx": 4096},
        )
        return (resp.get("response") or "").strip()
    except Exception as e:
        print(f"  [qc] local REWRITE fallback also failed: {e}")
        return ""


def _build_annotated_and_tts_text(sections: dict) -> tuple:
    """Build both annotated_text and tts_ready_text from the final
    approved sections dict."""
    annotated_parts = []
    tts_parts = []

    for label in SECTION_ORDER:
        text = sections.get(label, "").strip()
        if not text:
            continue

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

        annotated_sentences = []
        for j, sent in enumerate(sentences):
            word_count_sent = len(sent.split())
            if j > 0 and word_count_sent <= 3:
                annotated_sentences.append(f"[EMPHASIS: {sent}]")
            else:
                annotated_sentences.append(sent)

        annotated_parts.append(" ".join(annotated_sentences))
        tts_parts.append(text)

        if label in BEAT_AFTER:
            annotated_parts.append("[BEAT]")

    annotated_text = " ".join(annotated_parts)
    tts_ready_text = " ".join(tts_parts)

    return annotated_text, tts_ready_text


def script_qc_node(state: dict) -> dict:
    """LangGraph node -- orchestrates Agent 6's full QC pipeline."""
    script = state.get("script", {})

    print("=" * 70)
    print("AGENT 6: Script QC")
    print("=" * 70)

    if not script or not script.get("sections"):
        print("  [qc] no script sections found -- nothing to QC")
        state.setdefault("script", {})
        state["script"]["approved"] = False
        state["script"]["qc_notes"] = ["no script sections available"]
        return state

    qc_notes = []

    sections = {
        label: _humanize_dates(text)
        for label, text in script["sections"].items()
    }
    print(f"  [qc] date humanization applied to {len(sections)} sections")

    working_script = dict(script)
    working_script["sections"] = sections

    approved = False
    iterations = 0
    judgment = _default_judgment_pass()

    for iteration in range(1, MAX_ITERATIONS + 1):
        iterations = iteration
        print(f"\n  [qc] --- iteration {iteration} ---")

        judgment = _judge_script(working_script)
        print(f"  [qc] word_count_ok={judgment['word_count_ok']} "
              f"flagged={list(judgment['flagged_sections'].keys())} "
              f"cta_ok={judgment['cta_ok']} (category {judgment['cta_category']})")

        has_issues = (
            not judgment["word_count_ok"]
            or bool(judgment["flagged_sections"])
            or not judgment["cta_ok"]
        )

        if not has_issues:
            print(f"  [qc] no issues found -- approved at iteration {iteration}")
            approved = True
            qc_notes.append(f"iteration {iteration}: clean pass, no issues")
            break

        if not judgment["word_count_ok"]:
            qc_notes.append(
                f"iteration {iteration}: word count issue -> "
                f"{judgment['word_count_action']} {judgment['word_count_section']}"
            )
        for label, reason in judgment["flagged_sections"].items():
            qc_notes.append(f"iteration {iteration}: {label} flagged -> {reason}")
        if not judgment["cta_ok"]:
            qc_notes.append(f"iteration {iteration}: CTA rejected (category {judgment['cta_category']})")

        new_sections = _rewrite_flagged(working_script, judgment)
        working_script["sections"] = new_sections

        if iteration == MAX_ITERATIONS:
            print(f"  [qc] still has issues after {MAX_ITERATIONS} iterations "
                  f"-- approving as-is (never blocks pipeline)")
            qc_notes.append(f"accepted after {MAX_ITERATIONS} iterations with remaining issues")
            approved = True

    final_sections = working_script["sections"]
    full_text_parts = [final_sections.get(label, "") for label in SECTION_ORDER if final_sections.get(label)]
    final_full_text = " ".join(full_text_parts)
    
    final_word_count = len(final_full_text.split())

    if not (TARGET_MIN <= final_word_count <= TARGET_MAX):
        qc_notes.append(f"WARNING: final word count {final_word_count} outside "
                         f"target range {TARGET_MIN}-{TARGET_MAX} after rewrites")
        print(f"  [qc] WARNING: final word count {final_word_count} drifted outside target range")

    remaining_tts_issues = _scan_tts_readiness(final_sections)

    if remaining_tts_issues:
        qc_notes.extend([f"tts-readiness (unresolved): {label} -> {reason}"
                          for label, reason in remaining_tts_issues.items()])
        print(f"  [qc] TTS-readiness issues still present after {iterations} "
              f"iteration(s): {list(remaining_tts_issues.keys())}")

    annotated_text, tts_ready_text = _build_annotated_and_tts_text(final_sections)

    state["script"]["sections"]        = final_sections
    state["script"]["full_text"]       = final_full_text
    state["script"]["word_count"]      = final_word_count
    state["script"]["est_duration"]    = f"{round(final_word_count / 2.5)}s"
    state["script"]["annotated_text"]  = annotated_text
    state["script"]["tts_ready_text"]  = tts_ready_text
    state["script"]["approved"]        = approved
    state["script"]["qc_notes"]        = qc_notes
    state["script"]["cta_category"]    = judgment.get("cta_category", "A")
    state["script"]["iterations"]      = iterations

    print(f"\n  [qc] QC complete")
    print(f"  [qc]    approved:   {approved}")
    print(f"  [qc]    words:      {final_word_count}")
    print(f"  [qc]    duration:   ~{state['script']['est_duration']}")
    print(f"  [qc]    iterations: {iterations}")
    print(f"  [qc]    cta cat:    {state['script']['cta_category']}")

    return state