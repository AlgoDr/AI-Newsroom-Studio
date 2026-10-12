"""LLM-judged content evals -- the "do we ship good output?" layer.

Uses the SAME judge model family the pipeline itself uses for QC
(gpt-oss-120b via Groq), scoring golden checkpoint output:

  * faithfulness -- every factual claim in the final script is grounded
    in the selected stories' content/background (catches hallucination)
  * relevance    -- SEO title + HOOK actually match the selected stories
  * cost         -- word budget guardrail (validates our cost claim)

Gated: these SKIP (not fail) when GROQ_KEY is absent, since they need
a paid/externally-authenticated API. Run with:
    ../multi-agent-env/bin/python evals/run_all.py --content
"""

from __future__ import annotations

import os

from . import config
from . import dataset

# ── judge call ─────────────────────────────────────────────────────

def _load_judge():
    from groq import Groq
    key = os.getenv("GROQ_KEY")
    if not key:
        return None, "GROQ_KEY missing from environment/.env"
    return Groq(api_key=key), None


def _ask_judge(client, system: str, user: str) -> tuple[float | None, str]:
    """Returns (score_0to1, raw_or_error). Score is parsed from the
    judge's reply, which we force into 'SCORE: x.xx' JSON-ish form."""
    try:
        resp = client.chat.completions.create(
            model=config.JUDGE_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            max_tokens=config.JUDGE_MAX_TOKENS,
        )
    except Exception as e:
        return None, f"judge call failed: {type(e).__name__}: {e}"
    text = (resp.choices[0].message.content or "").strip()
    for token in text.split():
        if token.replace(".", "", 1).isdigit():
            try:
                return min(max(float(token), 0.0), 1.0), text[:120]
            except ValueError:
                continue
    return None, f"could not parse a score from judge: {text[:120]!r}"


# ══════════════════════════════════════════════════════════════════
# Eval 1 -- Faithfulness of the published script
# ══════════════════════════════════════════════════════════════════

def content_eval_faithfulness() -> tuple[bool, str]:
    client, err = _load_judge()
    if client is None:
        return False, f"SKIPPED: {err} (rerun with --content and GROQ_KEY set)"
    state = dataset.load_golden_checkpoint()
    script = dataset.golden_script(state)
    selected = dataset.selected_stories(state)
    if not selected:
        return False, "no selected stories in golden checkpoint"

    facts = []
    for s in selected[:3]:
        facts.append(f"[Story {s['selection_rank']}: {s['title']}]\n"
                     f"  content: {s.get('content', '')[:800]}\n"
                     f"  background: {s.get('background', '')[:800]}")
    source_block = "\n\n".join(facts)
    target = (script.get("full_text") or script.get("tts_ready_text") or "")[:2500]

    score, note = _ask_judge(
        client,
        system=("You are a strict fact-checking evaluator for a news video script. "
                "Score FAITHFULNESS from 0.0 to 1.0: whether every factual claim "
                "in the script is supported by the provided source stories. "
                "Reply with ONLY the score number, e.g. 0.92."),
        user=f"SOURCE STORIES:\n{source_block}\n\n"
             f"NEWS SCRIPT TO EVALUATE:\n{target}",
    )
    if score is None:
        return False, note
    passed = score >= config.FAITHFULNESS_THRESHOLD
    verdict = "PASS" if passed else "FAIL"
    return passed, (f"faithfulness={score:.2f} "
                    f"(threshold {config.FAITHFULNESS_THRESHOLD}) [{verdict}]")


# ══════════════════════════════════════════════════════════════════
# Eval 2 -- SEO title + HOOK relevance
# ══════════════════════════════════════════════════════════════════

def content_eval_relevance() -> tuple[bool, str]:
    client, err = _load_judge()
    if client is None:
        return False, f"SKIPPED: {err} (rerun with --content and GROQ_KEY set)"
    state = dataset.load_golden_checkpoint()
    script = dataset.golden_script(state)
    selected = dataset.selected_stories(state)
    if not selected:
        return False, "no selected stories in golden checkpoint"

    # Production reality check: a YouTube news short covers MULTIPLE
    # stories but the title+HOOK is SUPPOSED to hook on the LEAD story
    # (rank 1) -- that's how real news channels drive views. Judging the
    # title against ALL stories at once is a mis-specified criterion.
    lead = selected[0]
    sections = script.get("sections", {})
    hook = sections.get("HOOK", "")[:400]
    seo_title = state.get("seo", {}).get("title", "")

    score, note = _ask_judge(
        client,
        system=("You are a content-relevance evaluator for a news shorts "
                "channel. Each short covers several news stories; the title "
                "and hook must match the LEAD (primary) story. Score from "
                "0.0 to 1.0 how relevant the SEO title and opening hook are "
                "to the lead story. Reply with ONLY the score number."),
        user=f"LEAD STORY:\n{lead['title']}\n\nSEO TITLE:\n{seo_title}\n\nHOOK:\n{hook}",
    )
    if score is None:
        return False, note
    passed = score >= config.RELEVANCE_THRESHOLD
    verdict = "PASS" if passed else "FAIL"
    return passed, (f"relevance(lead)={score:.2f} "
                    f"(threshold {config.RELEVANCE_THRESHOLD}) [{verdict}]")


# ══════════════════════════════════════════════════════════════════
# Eval 3 -- Cost guardrail (word/token budget)
# ══════════════════════════════════════════════════════════════════

def content_eval_cost_guardrail() -> tuple[bool, str]:
    state = dataset.load_golden_checkpoint()
    script = dataset.golden_script(state)
    wc = script.get("word_count", 0)
    if wc > config.MAX_WORDS_PER_RUN:
        return False, (f"word_count={wc} exceeds guardrail "
                       f"{config.MAX_WORDS_PER_RUN}")
    return True, f"word_count={wc} within guardrail {config.MAX_WORDS_PER_RUN}"


# ══════════════════════════════════════════════════════════════════
# Phase A Quality Evals — DeepEval-based, per-agent golden datasets
# ══════════════════════════════════════════════════════════════════
#
# These wrap the DeepEval pytest tests from evals/quality/ into the
# (passed, detail) interface used by run_all.py. Each calls the
# agent's synthesis/judge function on frozen golden data and scores
# the output with an LLM judge or reference comparison.
#
# They SKIP (not fail) if deepeval or required APIs are unavailable.


def _quality_eval_wrapper(test_fn, label: str):
    """Run a DeepEval quality eval test function, catch assertion failures."""
    try:
        test_fn()
        return True, f"{label}: PASS"
    except AssertionError as e:
        return False, f"{label}: FAIL — {e}"
    except ImportError as e:
        return False, f"SKIPPED: {label} — missing dependency: {e}"
    except Exception as e:
        return False, f"{label}: CRASHED — {type(e).__name__}: {e}"


def quality_eval_agent2_faithfulness() -> tuple[bool, str]:
    """Agent 2 — background synthesis faithfulness (G-Eval, ref-free)."""
    try:
        from deepeval.metrics import BaseMetric  # noqa: F401 — check deepeval installed
    except ImportError:
        return False, "SKIPPED: deepeval not installed"
    key = os.getenv("GROQ_KEY")
    if not key:
        return False, "SKIPPED: GROQ_KEY not set (needed for judge)"

    # Import path: evals/ is a sibling of experiments/ — add project root
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from evals.quality.ref_free.test_agent2 import test_agent2_background_faithfulness
    return _quality_eval_wrapper(test_agent2_background_faithfulness,
                                 "Agent 2 background faithfulness")


def quality_eval_agent3_accuracy() -> tuple[bool, str]:
    """Agent 3 — credibility label accuracy (macro-F1, ref-based)."""
    try:
        from deepeval.metrics import BaseMetric  # noqa: F401
    except ImportError:
        return False, "SKIPPED: deepeval not installed"
    key = os.getenv("GROQ_KEY")
    if not key:
        return False, "SKIPPED: GROQ_KEY not set (needed for Agent 3)"

    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from evals.quality.ref_based.test_agent3 import test_agent3_credibility_accuracy
    return _quality_eval_wrapper(test_agent3_credibility_accuracy,
                                 "Agent 3 credibility accuracy (macro-F1)")


def quality_eval_agent4_dedup() -> tuple[bool, str]:
    """Agent 4 — dedup merge precision/recall (micro-F1, ref-based)."""
    try:
        from deepeval.metrics import BaseMetric  # noqa: F401
    except ImportError:
        return False, "SKIPPED: deepeval not installed"

    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from evals.quality.ref_based.test_agent4 import test_agent4_dedup_accuracy
    return _quality_eval_wrapper(test_agent4_dedup_accuracy,
                                 "Agent 4 dedup merge (micro-F1)")


def quality_eval_agent5_script() -> tuple[bool, str]:
    """Agent 5 — script generation composite (7 dimensions, ref-based)."""
    try:
        from deepeval.metrics import BaseMetric  # noqa: F401
    except ImportError:
        return False, "SKIPPED: deepeval not installed"
    key = os.getenv("GROQ_KEY")
    if not key:
        return False, "SKIPPED: GROQ_KEY not set (needed for Agent 5)"

    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from evals.quality.ref_based.test_agent5 import test_agent5_script_quality
    return _quality_eval_wrapper(test_agent5_script_quality,
                                 "Agent 5 script quality (composite)")


def quality_eval_agent6_judge() -> tuple[bool, str]:
    """Agent 6 — JUDGE agreement on pass/fail (micro-F1, ref-based)."""
    try:
        from deepeval.metrics import BaseMetric  # noqa: F401
    except ImportError:
        return False, "SKIPPED: deepeval not installed"
    key = os.getenv("GROQ_KEY")
    if not key:
        return False, "SKIPPED: GROQ_KEY not set (needed for Agent 6)"

    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from evals.quality.ref_based.test_agent6 import test_agent6_judge_accuracy
    return _quality_eval_wrapper(test_agent6_judge_accuracy,
                                 "Agent 6 JUDGE agreement (micro-F1)")


CONTENT_EVALS = [
    # Checkpoint-based evals (existing)
    content_eval_faithfulness,
    content_eval_relevance,
    content_eval_cost_guardrail,
    # Phase A quality evals (per-agent golden datasets)
    quality_eval_agent2_faithfulness,
    quality_eval_agent3_accuracy,
    quality_eval_agent4_dedup,
    quality_eval_agent5_script,
    quality_eval_agent6_judge,
]