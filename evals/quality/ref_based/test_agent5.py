"""
Agent 5 — Script Writer Quality Eval

Reference-FREE eval: Agent 5 is generative, so there's no "correct" output
to compare against. Instead we score the output on a quality rubric.

7 dimensions:
  Deterministic (pure Python):
    1. structure_complete  — all expected sections present
    2. word_count_range    — total words within 150-225
    3. cta_exact_match     — CTA is one of the 3 exact sentences

  LLM-judged (qwen/qwen3.8-27b via Groq):
    4. hook_specificity    — HOOK names a concrete fact, not generic
    5. twist_quality       — TWISTs add consequence beyond CORE
    6. faithfulness        — claims grounded in source stories
    7. story_alignment     — S1 uses Story 1 content, S2 uses Story 2, etc.

Gate: composite mean ≥ 0.70

Run:
    cd /path/to/AI-Newsroom-Studio
    ../multi-agent-env/bin/python -m pytest evals/quality/ref_based/test_agent5.py -v -s
"""

import json
import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field

# ── path setup ─────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent.parent   # project root
sys.path.insert(0, str(ROOT / "experiments"))

# Load .env BEFORE importing agent5 (Groq client initializes at import time)
from dotenv import load_dotenv
load_dotenv(ROOT / "experiments" / ".env")

from agents.agent5 import (
    _get_selected_stories,
    _build_prompt,
    _parse_script,
    _enforce_word_count,
    script_writer_node,
    TARGET_MIN,
    TARGET_MAX,
)

# ── DeepEval ───────────────────────────────────────────────────────
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase
from deepeval import assert_test

# ── config ─────────────────────────────────────────────────────────
GOLDEN = ROOT / "evals" / "golden_dataset" / "agent5_script_v1.json"
THRESHOLD = 0.70

VALID_CTAS = [
    "Follow for daily tech news",
    "Comment below with your thoughts",
    "Link in bio for more",
]

JUDGE_MODEL = "qwen/qwen3.8-27b"
JUDGE_MAX_TOKENS = 300

# ── Groq judge client ─────────────────────────────────────────────

def _load_judge():
    """Load Groq client for LLM-judged dimensions."""
    from groq import Groq
    import dotenv
    dotenv.load_dotenv(ROOT / "experiments" / ".env")
    key = os.getenv("GROQ_KEY")
    if not key:
        return None
    return Groq(api_key=key)


def _ask_judge(client, system: str, user: str) -> float:
    """Ask the LLM judge to score something 0-1. Returns float score."""
    try:
        resp = client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            max_tokens=JUDGE_MAX_TOKENS,
        )
        text = (resp.choices[0].message.content or "").strip()
        # Parse score from response — look for first float-like token
        for token in text.replace(",", "").split():
            cleaned = token.strip(".")
            if cleaned.replace(".", "", 1).isdigit():
                try:
                    return min(max(float(cleaned), 0.0), 1.0)
                except ValueError:
                    continue
        print(f"    [judge] could not parse score from: {text[:120]}")
        return 0.0
    except Exception as e:
        print(f"    [judge] call failed: {e}")
        return 0.0


# ══════════════════════════════════════════════════════════════════
# DETERMINISTIC CHECKS (pure Python — never LLM)
# ══════════════════════════════════════════════════════════════════

def check_structure(sections: dict, expected_sections: list) -> tuple[float, str]:
    """Check all expected sections are present. Returns (score, detail)."""
    present = [s for s in expected_sections if s in sections]
    missing = [s for s in expected_sections if s not in sections]
    score = len(present) / len(expected_sections) if expected_sections else 0.0

    if missing:
        detail = f"missing: {', '.join(missing)}"
    else:
        detail = f"all {len(expected_sections)} sections present"
    return score, detail


def check_word_count(script: dict) -> tuple[float, str]:
    """Check word count is within TARGET_MIN-TARGET_MAX. Returns (score, detail)."""
    wc = script.get("word_count", 0)
    if TARGET_MIN <= wc <= TARGET_MAX:
        return 1.0, f"{wc} words (in range {TARGET_MIN}-{TARGET_MAX})"
    else:
        return 0.0, f"{wc} words (out of range {TARGET_MIN}-{TARGET_MAX})"


def check_cta_exact(sections: dict) -> tuple[float, str]:
    """Check CTA matches one of the 3 exact sentences. Returns (score, detail)."""
    cta = sections.get("CTA", "").strip()
    if not cta:
        return 0.0, "no CTA section found"

    # Normalize: strip trailing punctuation and whitespace for comparison
    cta_clean = cta.rstrip(".!").strip()
    for valid in VALID_CTAS:
        if cta_clean.lower() == valid.lower():
            return 1.0, f"exact match: '{valid}'"

    return 0.0, f"CTA mismatch: '{cta[:60]}'"


# ══════════════════════════════════════════════════════════════════
# LLM-JUDGED CHECKS
# ══════════════════════════════════════════════════════════════════

def judge_hook_specificity(client, hook: str, story1_title: str, story1_content: str) -> tuple[float, str]:
    """Score 0-1: does the HOOK name a specific fact from Story 1?"""
    score = _ask_judge(
        client,
        system=(
            "You evaluate YouTube Shorts hooks for SPECIFICITY. "
            "A good hook names ONE concrete, surprising fact from the story — "
            "a number, a name, a technical detail — that makes a viewer stop scrolling. "
            "A bad hook is generic ('big news in tech', 'you won't believe this'). "
            "Score from 0.0 to 1.0. "
            "1.0 = names a specific fact from the story that creates immediate curiosity. "
            "0.5 = somewhat specific but vague or not clearly tied to the story. "
            "0.0 = completely generic, could apply to any tech video. "
            "Reply with ONLY the score number, e.g. 0.85"
        ),
        user=(
            f"STORY 1 TITLE: {story1_title}\n"
            f"STORY 1 CONTENT (first 300 chars): {story1_content[:300]}\n\n"
            f"HOOK TO EVALUATE:\n{hook}"
        ),
    )
    detail = f"hook_specificity={score:.2f}"
    return score, detail


def judge_twist_quality(client, sections: dict, stories: list) -> tuple[float, str]:
    """Score 0-1: do TWISTs add consequence/implication beyond their CORE?"""
    # Collect TWIST-CORE pairs
    pairs = []
    for i, story in enumerate(stories[:3], 1):
        twist_key = f"S{i}_TWIST" if i > 0 else "S1_TWIST"
        core_key = f"S{i}_CORE" if i > 0 else "S1_CORE"
        twist = sections.get(twist_key, "")
        core = sections.get(core_key, "")
        if twist and core:
            pairs.append(f"STORY {i} CORE: {core}\nSTORY {i} TWIST: {twist}")

    if not pairs:
        return 0.0, "no TWIST-CORE pairs found"

    pairs_text = "\n\n".join(pairs)

    score = _ask_judge(
        client,
        system=(
            "You evaluate YouTube Shorts script TWISTs. "
            "A good TWIST reveals a CONSEQUENCE or IMPLICATION not already stated in CORE. "
            "A bad TWIST restates the core fact, is vague ('this is significant'), "
            "or tells the viewer what to think instead of what to know. "
            "Score from 0.0 to 1.0 based on the average quality across all TWIST-CORE pairs. "
            "1.0 = every TWIST adds genuinely new, actionable information beyond CORE. "
            "0.5 = some TWISTs add information but are partially redundant with CORE. "
            "0.0 = TWISTs are pure restatements of CORE facts. "
            "Reply with ONLY the score number, e.g. 0.75"
        ),
        user=f"Evaluate these TWIST-CORE pairs:\n\n{pairs_text}",
    )
    detail = f"twist_quality={score:.2f} ({len(pairs)} pairs)"
    return score, detail


def judge_faithfulness(client, sections: dict, stories: list) -> tuple[float, str]:
    """Score 0-1: are factual claims grounded in source stories?"""
    # Build source block
    facts = []
    for i, story in enumerate(stories[:3], 1):
        facts.append(
            f"[Story {i}: {story['title']}]\n"
            f"  content: {story.get('content', '')[:800]}\n"
            f"  background: {story.get('background', '')[:300]}"
        )
    source_block = "\n\n".join(facts)

    # Build script text from sections (exclude CTA — it's a fixed sentence)
    script_parts = []
    for key in ["HOOK", "S1_CONTEXT", "S1_CORE", "S1_TWIST",
                 "S2_HOOK", "S2_CORE", "S2_TWIST",
                 "S3_HOOK", "S3_CORE"]:
        if key in sections:
            script_parts.append(f"{key}: {sections[key]}")
    script_text = "\n".join(script_parts)

    score = _ask_judge(
        client,
        system=(
            "You are a strict fact-checking evaluator for a tech news video script. "
            "Score FAITHFULNESS from 0.0 to 1.0: whether every factual claim in the "
            "script is supported by the provided source stories. "
            "Penalize invented facts, wrong numbers, or claims not in the sources. "
            "Do NOT penalize stylistic choices, tone, or structure — only factual accuracy. "
            "Reply with ONLY the score number, e.g. 0.92"
        ),
        user=(
            f"SOURCE STORIES:\n{source_block}\n\n"
            f"SCRIPT TO EVALUATE:\n{script_text}"
        ),
    )
    detail = f"faithfulness={score:.2f}"
    return score, detail


def judge_story_alignment(client, sections: dict, stories: list) -> tuple[float, str]:
    """Score 0-1: does S1 use Story 1 content, S2 use Story 2, etc.?"""
    checks = []
    for i, story in enumerate(stories[:3], 1):
        story_sections = []
        if i == 1:
            for key in ["HOOK", "S1_CONTEXT", "S1_CORE", "S1_TWIST"]:
                if key in sections:
                    story_sections.append(f"{key}: {sections[key]}")
        else:
            for key in [f"S{i}_HOOK", f"S{i}_CORE", f"S{i}_TWIST"]:
                if key in sections:
                    story_sections.append(f"{key}: {sections[key]}")

        if story_sections:
            checks.append(
                f"STORY {i} TITLE: {story['title']}\n"
                f"STORY {i} CONTENT (first 200 chars): {story.get('content', '')[:200]}\n"
                f"SCRIPT SECTIONS FOR STORY {i}:\n" + "\n".join(story_sections)
            )

    if not checks:
        return 0.0, "no sections to check alignment"

    checks_text = "\n\n---\n\n".join(checks)

    score = _ask_judge(
        client,
        system=(
            "You evaluate whether a multi-story news script keeps its stories aligned: "
            "Story 1's facts appear in S1 sections (HOOK, S1_CONTEXT, S1_CORE, S1_TWIST), "
            "Story 2's facts in S2 sections (S2_HOOK, S2_CORE, S2_TWIST), "
            "Story 3's facts in S3 sections (S3_HOOK, S3_CORE). "
            "Score from 0.0 to 1.0. "
            "1.0 = each story's facts appear only in their correct sections, no cross-contamination. "
            "0.5 = mostly correct but some facts from one story leak into another's sections. "
            "0.0 = stories are badly mixed up — wrong facts in wrong sections. "
            "Reply with ONLY the score number, e.g. 0.90"
        ),
        user=f"Check story-section alignment:\n\n{checks_text}",
    )
    detail = f"story_alignment={score:.2f}"
    return score, detail


# ══════════════════════════════════════════════════════════════════
# MAIN EVAL
# ══════════════════════════════════════════════════════════════════

@dataclass
class EvalResult:
    test_id: str
    description: str
    difficulty: str
    # deterministic
    structure_score: float = 0.0
    structure_detail: str = ""
    word_count_score: float = 0.0
    word_count_detail: str = ""
    cta_score: float = 0.0
    cta_detail: str = ""
    # LLM-judged
    hook_score: float = 0.0
    hook_detail: str = ""
    twist_score: float = 0.0
    twist_detail: str = ""
    faith_score: float = 0.0
    faith_detail: str = ""
    align_score: float = 0.0
    align_detail: str = ""
    # composite
    composite: float = 0.0
    # metadata
    model_used: str = ""
    word_count: int = 0
    generation_error: str = ""

    def compute_composite(self):
        scores = [
            self.structure_score, self.word_count_score, self.cta_score,
            self.hook_score, self.twist_score, self.faith_score, self.align_score,
        ]
        self.composite = sum(scores) / len(scores) if scores else 0.0


def run_eval() -> tuple[float, list[EvalResult]]:
    """Run the full Agent 5 eval. Returns (overall_composite, results)."""

    # Load golden dataset
    with open(GOLDEN, "r") as f:
        test_cases = json.load(f)

    # Load judge
    judge_client = _load_judge()
    if judge_client is None:
        print("  [eval] WARNING: GROQ_KEY not set — LLM-judged dimensions will score 0.0")

    results = []

    for tc in test_cases:
        test_id = tc["test_id"]
        desc = tc["description"]
        diff = tc["difficulty"]
        expected = tc["expected"]

        print(f"\n{'='*70}")
        print(f"TEST {test_id}: {desc}")
        print(f"{'='*70}")

        # ── Build state and run Agent 5 ────────────────────────────
        state = {"stories": tc["stories"]}

        t0 = time.time()
        try:
            state = script_writer_node(state)
        except Exception as e:
            print(f"  [eval] script_writer_node CRASHED: {e}")
            r = EvalResult(test_id=test_id, description=desc, difficulty=diff,
                           generation_error=str(e))
            results.append(r)
            continue
        elapsed = time.time() - t0

        script = state.get("script", {})
        sections = script.get("sections", {})
        error = script.get("error", "")

        if error:
            print(f"  [eval] Agent 5 returned error: {error}")
            r = EvalResult(test_id=test_id, description=desc, difficulty=diff,
                           generation_error=error)
            results.append(r)
            continue

        # Detect which model was used (heuristic: if fallback was triggered,
        # agent5 prints "falling back to local")
        # For now just record word count
        wc = script.get("word_count", 0)
        print(f"  [eval] generation complete in {elapsed:.1f}s, {wc} words, "
              f"{len(sections)} sections")

        # ── Extract stories list (sorted by rank) ──────────────────
        stories = sorted(
            [s for s in tc["stories"].values() if s.get("selected")],
            key=lambda s: s.get("selection_rank", 99)
        )

        # ── Deterministic checks ───────────────────────────────────
        struct_score, struct_detail = check_structure(sections, expected["expected_sections"])
        wc_score, wc_detail = check_word_count(script)
        cta_score, cta_detail = check_cta_exact(sections)

        print(f"  [det] structure: {struct_score:.3f} — {struct_detail}")
        print(f"  [det] word_count: {wc_score:.3f} — {wc_detail}")
        print(f"  [det] cta_exact: {cta_score:.3f} — {cta_detail}")

        # ── LLM-judged checks ──────────────────────────────────────
        hook_score, hook_detail = 0.0, "skipped (no judge)"
        twist_score, twist_detail = 0.0, "skipped (no judge)"
        faith_score, faith_detail = 0.0, "skipped (no judge)"
        align_score, align_detail = 0.0, "skipped (no judge)"

        if judge_client:
            hook_text = sections.get("HOOK", "")
            if hook_text and stories:
                hook_score, hook_detail = judge_hook_specificity(
                    judge_client, hook_text,
                    stories[0]["title"], stories[0].get("content", "")
                )
                # Rate limit spacing
                time.sleep(1)

            if stories:
                twist_score, twist_detail = judge_twist_quality(
                    judge_client, sections, stories
                )
                time.sleep(1)

                faith_score, faith_detail = judge_faithfulness(
                    judge_client, sections, stories
                )
                time.sleep(1)

                align_score, align_detail = judge_story_alignment(
                    judge_client, sections, stories
                )
                time.sleep(1)

        print(f"  [llm] hook: {hook_score:.3f} — {hook_detail}")
        print(f"  [llm] twist: {twist_score:.3f} — {twist_detail}")
        print(f"  [llm] faith: {faith_score:.3f} — {faith_detail}")
        print(f"  [llm] align: {align_score:.3f} — {align_detail}")

        r = EvalResult(
            test_id=test_id, description=desc, difficulty=diff,
            structure_score=struct_score, structure_detail=struct_detail,
            word_count_score=wc_score, word_count_detail=wc_detail,
            cta_score=cta_score, cta_detail=cta_detail,
            hook_score=hook_score, hook_detail=hook_detail,
            twist_score=twist_score, twist_detail=twist_detail,
            faith_score=faith_score, faith_detail=faith_detail,
            align_score=align_score, align_detail=align_detail,
            word_count=wc,
        )
        r.compute_composite()
        print(f"  [eval] composite: {r.composite:.3f}")
        results.append(r)

    # ── Overall ────────────────────────────────────────────────────
    valid = [r for r in results if not r.generation_error]
    overall = sum(r.composite for r in valid) / len(valid) if valid else 0.0

    print(f"\n{'='*70}")
    print(f"OVERALL RESULTS")
    print(f"{'='*70}")
    print()

    # Per-test summary
    print(f"{'ID':<5} {'Diff':<8} {'Struct':>6} {'WC':>6} {'CTA':>6} "
          f"{'Hook':>6} {'Twist':>6} {'Faith':>6} {'Align':>6} {'Comp':>6}")
    print("-" * 70)
    for r in results:
        if r.generation_error:
            print(f"{r.test_id:<5} {r.difficulty:<8} {'ERROR':>6} — {r.generation_error[:40]}")
        else:
            print(f"{r.test_id:<5} {r.difficulty:<8} {r.structure_score:>6.3f} "
                  f"{r.word_count_score:>6.3f} {r.cta_score:>6.3f} "
                  f"{r.hook_score:>6.3f} {r.twist_score:>6.3f} "
                  f"{r.faith_score:>6.3f} {r.align_score:>6.3f} "
                  f"{r.composite:>6.3f}")

    # Dimension averages
    if valid:
        print()
        print("Dimension averages:")
        dims = {
            "structure": [r.structure_score for r in valid],
            "word_count": [r.word_count_score for r in valid],
            "cta_exact": [r.cta_score for r in valid],
            "hook_spec": [r.hook_score for r in valid],
            "twist_qual": [r.twist_score for r in valid],
            "faithfulness": [r.faith_score for r in valid],
            "alignment": [r.align_score for r in valid],
        }
        for name, scores in dims.items():
            avg = sum(scores) / len(scores)
            print(f"  {name:<14} {avg:.3f}")

    print()
    verdict = "PASS" if overall >= THRESHOLD else "FAIL"
    print(f"Composite: {overall:.3f} (gate >= {THRESHOLD}) [{verdict}]")
    print(f"Tests: {len(valid)} succeeded, {len(results) - len(valid)} errored")

    return overall, results


# ══════════════════════════════════════════════════════════════════
# DeepEval metric wrapper
# ══════════════════════════════════════════════════════════════════

class ScriptQualityMetric(BaseMetric):
    """Composite script quality metric for Agent 5."""

    def __init__(self, *, threshold=THRESHOLD, score=None, reason=None,
                 success=None, _results=None, _already_ran=False, **_kw):
        # Accept keyword args so DeepEval's copy_metrics() can clone state.
        # copy_metrics() calls type(metric)(**vars(metric)) — without these
        # params the copy starts blank and re-runs the entire eval.
        self.threshold = threshold
        self.score = score
        self.reason = reason
        self.success = success
        self._results = _results if _results is not None else []
        self._already_ran = _already_ran

    @property
    def __name__(self):
        return "ScriptQualityMetric"

    def measure(self, test_case: LLMTestCase) -> float:
        # Guard: assert_test calls a_measure internally, which would
        # re-run the entire eval. Only run once — return cached result.
        if self._already_ran:
            return self.score

        overall, results = run_eval()
        self._results = results
        self.score = overall
        self.success = overall >= self.threshold
        self.reason = (
            f"composite={overall:.3f} (gate>={self.threshold}) — "
            f"{sum(1 for r in results if not r.generation_error)}/{len(results)} tests OK"
        )
        self._already_ran = True
        return self.score

    async def a_measure(self, test_case: LLMTestCase) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.success


# ══════════════════════════════════════════════════════════════════
# pytest entry point
# ══════════════════════════════════════════════════════════════════

def test_agent5_script():
    """Agent 5 Script Writer — reference-free quality eval.

    Runs script_writer_node on 5 test input sets, scoring each output
    on 7 dimensions (3 deterministic + 4 LLM-judged).

    Gate: composite mean >= 0.70
    """
    metric = ScriptQualityMetric()
    dummy = LLMTestCase(input="agent5 eval", actual_output="see details")

    # Pre-run to populate scores, then assert_test uses cached result
    metric.measure(dummy)

    print(f"\n{'='*70}")
    print(f"DEEPEVAL: score={metric.score:.3f}, "
          f"threshold={metric.threshold}, "
          f"success={metric.success}")
    print(f"REASON: {metric.reason}")
    print(f"{'='*70}")

    # assert_test triggers DeepEval's results table; the guard in
    # measure() prevents a second full eval run
    assert_test(dummy, [metric])

    assert metric.is_successful(), (
        f"Agent 5 script quality below gate: "
        f"{metric.score:.3f} < {metric.threshold} — {metric.reason}"
    )
