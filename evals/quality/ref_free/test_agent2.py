"""
Agent 2 — Context Researcher Background Faithfulness Eval

Reference-FREE eval: Agent 2's `synthesize_background()` generates a
background paragraph from source content + snippets. There is no "correct"
background to compare against. Instead, G-Eval judges whether the
synthesized background is faithful to the provided source material.

Metric: G-Eval faithfulness — does the background only contain claims
         supported by the fetched content and snippets?
Gate: mean faithfulness ≥ 0.70

The golden dataset stores title, content, and pre-gathered snippets.
At eval time, `synthesize_background(title, content, snippets)` is called
directly (bypassing network-dependent DDG/Wikipedia), and the output is
scored by the LLM judge.

Run:
    cd /path/to/AI-Newsroom-Studio
    ../multi-agent-env/bin/python -m pytest evals/quality/ref_free/test_agent2.py -v -s
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

# Load .env BEFORE importing agent2 (Groq/Ollama clients init at import)
from dotenv import load_dotenv
load_dotenv(ROOT / "experiments" / ".env")

import os
os.environ.setdefault("GROQ_API_KEY", os.getenv("GROQ_KEY", ""))

# ── DeepEval ───────────────────────────────────────────────────────
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase
from deepeval import evaluate

# ── config ─────────────────────────────────────────────────────────
GOLDEN = ROOT / "evals" / "golden_dataset" / "agent2_context_v1.json"
THRESHOLD = 0.70

JUDGE_MODEL = "qwen/qwen3.8-27b"
JUDGE_MAX_TOKENS = 400


# ── Groq judge client ─────────────────────────────────────────────

def _load_judge():
    """Load Groq client for LLM-judged faithfulness."""
    from groq import Groq
    key = os.getenv("GROQ_KEY")
    if not key:
        return None
    return Groq(api_key=key)


FAITHFULNESS_SYSTEM = """You are an expert fact-checker evaluating whether a background summary
is faithful to its source material. A faithful summary:
1. Only makes claims that are directly supported by the source content or snippets
2. Does not introduce facts, numbers, dates, or claims not present in the sources
3. Does not exaggerate, speculate, or editorialize beyond what sources state
4. May reasonably rephrase or condense information

Score the background's faithfulness to the provided sources on a scale of 0.0 to 1.0:
- 1.0 = every claim is directly supported by the sources
- 0.8 = minor rephrasing but all core facts are grounded
- 0.5 = some claims are unsupported or loosely connected to sources
- 0.2 = significant hallucinated content or invented claims
- 0.0 = entirely fabricated or unrelated to sources

Respond with ONLY a decimal number between 0.0 and 1.0. No explanation."""

FAITHFULNESS_USER = """SOURCE CONTENT:
{content}

SNIPPETS:
{snippet_text}

BACKGROUND TO EVALUATE:
{background}

Score (0.0-1.0):"""


def _ask_judge(client, content: str, snippet_text: str, background: str) -> float:
    """Ask the LLM judge to score faithfulness. Returns float 0.0-1.0."""
    try:
        resp = client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[
                {"role": "system", "content": FAITHFULNESS_SYSTEM},
                {"role": "user", "content": FAITHFULNESS_USER.format(
                    content=content,
                    snippet_text=snippet_text,
                    background=background,
                )},
            ],
            temperature=0,
            max_tokens=JUDGE_MAX_TOKENS,
        )
        text = (resp.choices[0].message.content or "").strip()
        # Parse score — first float-like token
        for token in text.replace(",", "").split():
            cleaned = token.strip(".")
            if cleaned.replace(".", "", 1).isdigit():
                try:
                    val = float(cleaned)
                    return max(0.0, min(1.0, val))
                except ValueError:
                    continue
        print(f"  [judge] could not parse score from: {text!r}")
        return 0.0
    except Exception as e:
        print(f"  [judge] error: {e}")
        return 0.0


# ── Custom DeepEval Metric ─────────────────────────────────────────

@dataclass
class FaithfulnessMetric(BaseMetric):
    """G-Eval faithfulness: is the background grounded in the sources?"""

    threshold: float = THRESHOLD
    score: float = 0.0
    reason: str = ""
    success: bool = False

    # per-story detail
    story_scores: list = field(default_factory=list)

    @property
    def __name__(self):
        return "BackgroundFaithfulness"

    def measure(self, test_case: LLMTestCase) -> float:
        """Score a single test case.

        Convention:
          test_case.input          = title
          test_case.actual_output  = background (synthesized by Agent 2)
          test_case.context        = [content, snippet_text]
        """
        content = test_case.context[0] if test_case.context else ""
        snippet_text = test_case.context[1] if test_case.context and len(test_case.context) > 1 else ""
        background = test_case.actual_output or ""

        if not background or not background.strip():
            self.score = 0.0
            self.reason = "Empty background"
            self.success = False
            return self.score

        judge = _load_judge()
        if not judge:
            self.score = 0.0
            self.reason = "No GROQ_KEY — cannot run judge"
            self.success = False
            return self.score

        self.score = _ask_judge(judge, content, snippet_text, background)
        self.success = self.score >= self.threshold
        self.reason = f"faithfulness={self.score:.3f} (threshold={self.threshold})"
        return self.score

    async def a_measure(self, test_case: LLMTestCase) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return self.success


# ── Load golden dataset ────────────────────────────────────────────

def _load_goldens() -> list[dict]:
    with open(GOLDEN) as f:
        return json.load(f)


def _format_snippets(snippets: list[dict]) -> str:
    """Format snippets into the text form Agent 2 passes to synthesis."""
    if not snippets:
        return "(no snippets available)"
    return "\n\n".join(
        f"[{s['source']} | {s['date']}]\n{s['title']}\n{s['body']}"
        for s in snippets
    )


# ── Generate backgrounds using Agent 2 ────────────────────────────

def _run_agent2(goldens: list[dict]) -> list[dict]:
    """Run Agent 2's synthesis on each golden, return results."""
    from agents.agent2 import synthesize_background, _strip_citation_artifacts

    results = []
    for i, g in enumerate(goldens):
        test_id = g["test_id"]
        title = g["title"]
        content = g["content"]
        snippets = g["snippets"]

        print(f"\n{'='*60}")
        print(f"Test {test_id}/{len(goldens)}: {title[:50]}...")
        print(f"  Content: {len(content)} chars, Snippets: {len(snippets)}")

        try:
            # Call synthesis directly — bypasses DDG/Wikipedia network calls
            background = synthesize_background(title, content, snippets)
            background = _strip_citation_artifacts(background)
            status = f"{len(background)} chars" if background else "EMPTY"
            print(f"  Background: {status}")
        except Exception as e:
            print(f"  ERROR: {e}")
            background = ""

        results.append({
            "test_id": test_id,
            "title": title,
            "content": content,
            "snippets": snippets,
            "background": background,
            "difficulty": g.get("difficulty", "unknown"),
        })

        # Rate limiting — respect Groq/Ollama
        if i < len(goldens) - 1:
            time.sleep(1)

    return results


# ── Build DeepEval test cases ──────────────────────────────────────

def _build_test_cases(results: list[dict]) -> list[LLMTestCase]:
    """Build DeepEval test cases from Agent 2 results."""
    cases = []
    for r in results:
        snippet_text = _format_snippets(r["snippets"])
        tc = LLMTestCase(
            input=r["title"],
            actual_output=r["background"],
            context=[r["content"], snippet_text],
        )
        cases.append(tc)
    return cases


# ── pytest entry point ─────────────────────────────────────────────

def test_agent2_background_faithfulness():
    """Phase A quality eval: Agent 2 background faithfulness.

    Runs synthesize_background() on 15 frozen story inputs, then
    scores each output with G-Eval faithfulness judge.
    """
    goldens = _load_goldens()
    print(f"\nLoaded {len(goldens)} golden test cases")

    # Run Agent 2 synthesis
    results = _run_agent2(goldens)

    # Build test cases
    test_cases = _build_test_cases(results)

    # Score each
    metric = FaithfulnessMetric()
    scores = []

    print(f"\n{'='*60}")
    print("FAITHFULNESS SCORING")
    print(f"{'='*60}")

    for i, tc in enumerate(test_cases):
        score = metric.measure(tc)
        scores.append(score)
        r = results[i]
        status = "PASS" if score >= THRESHOLD else "FAIL"
        print(f"  [{status}] test_id={r['test_id']} "
              f"score={score:.3f} "
              f"({r['difficulty']}) {r['title'][:40]}...")
        time.sleep(0.5)  # rate limit judge calls

    # Aggregate
    mean_score = sum(scores) / len(scores) if scores else 0.0
    passed = sum(1 for s in scores if s >= THRESHOLD)
    failed = len(scores) - passed

    print(f"\n{'='*60}")
    print(f"RESULTS: mean={mean_score:.3f}, "
          f"passed={passed}/{len(scores)}, "
          f"threshold={THRESHOLD}")
    print(f"{'='*60}")

    # DeepEval assertion
    overall_tc = LLMTestCase(
        input="Agent 2 background faithfulness (aggregate)",
        actual_output=f"mean_faithfulness={mean_score:.3f}",
    )
    overall_metric = FaithfulnessMetric()
    overall_metric.score = mean_score
    overall_metric.success = mean_score >= THRESHOLD
    overall_metric.reason = (
        f"mean={mean_score:.3f}, {passed}/{len(scores)} above threshold, "
        f"min={min(scores):.3f}, max={max(scores):.3f}"
    )

    assert overall_metric.is_successful(), (
        f"Agent 2 faithfulness FAILED: mean={mean_score:.3f} "
        f"< threshold={THRESHOLD}"
    )


if __name__ == "__main__":
    test_agent2_background_faithfulness()
