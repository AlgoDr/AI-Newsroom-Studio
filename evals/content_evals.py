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


CONTENT_EVALS = [
    content_eval_faithfulness,
    content_eval_relevance,
    content_eval_cost_guardrail,
]