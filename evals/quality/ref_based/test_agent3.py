"""Agent 3 Credibility Classification Eval — DeepEval implementation.

Tests llm_credibility_check() from Agent 3 (the LLM classification
function that returns REAL/OPINION/SPAM via gpt-oss-120b with
qwen2.5:7b local fallback).

Metric: per-story classification accuracy, aggregated as macro-F1.
Gate: macro-F1 ≥ 0.70

The golden dataset stores title + content + expected_label for each
story. Content must be ≥ 500 chars for the function's guard to pass
(< 500 chars → 0.0 neutral, which is not a classification).
"""

import json
import sys
from pathlib import Path
from collections import Counter

from deepeval import evaluate
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

# ── Paths ──────────────────────────────────────────────────────
EVAL_DIR     = Path(__file__).resolve().parent
EVALS_ROOT   = EVAL_DIR.parent.parent
PROJECT_ROOT = EVALS_ROOT.parent

GOLDEN = EVALS_ROOT / "golden_dataset" / "agent3_credibility_v1.json"

sys.path.insert(0, str(PROJECT_ROOT / "experiments"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / "experiments" / ".env")

import os
os.environ.setdefault("GROQ_API_KEY", os.getenv("GROQ_KEY", ""))


# ── Constants ─────────────────────────────────────────────────
LABEL_SCORES = {
    "REAL":    +0.9,
    "OPINION": +0.1,
    "SPAM":    -0.7,
}

# Reverse map: score → label (for converting agent output back)
SCORE_TO_LABEL = {v: k for k, v in LABEL_SCORES.items()}

THRESHOLD = 0.70          # gate: macro-F1 ≥ 0.70

CLASSES = ["REAL", "OPINION", "SPAM"]


# ── Helpers ────────────────────────────────────────────────────

def score_to_label(score: float) -> str:
    """Map the float score back to a classification label.

    llm_credibility_check returns:
      +0.9 → REAL
      +0.1 → OPINION
      -0.7 → SPAM
       0.0 → NEUTRAL (guard triggered or both models failed)

    We match to the closest known label score.
    """
    if score == 0.0:
        return "NEUTRAL"   # guard triggered, not a real classification

    best_label = "NEUTRAL"
    best_dist = float("inf")
    for lbl_score, lbl in SCORE_TO_LABEL.items():
        dist = abs(score - lbl_score)
        if dist < best_dist:
            best_dist = dist
            best_label = lbl
    return best_label


def compute_macro_f1(
    y_true: list[str],
    y_pred: list[str],
    classes: list[str],
) -> tuple[float, dict]:
    """Compute macro-averaged F1 across specified classes.

    Returns (macro_f1, per_class_dict) where per_class_dict maps
    each class to {precision, recall, f1, support}.

    Classes with 0 support are excluded from the macro average
    (same treatment as sklearn's macro average with zero_division=0).
    """
    per_class = {}

    for cls in classes:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == cls and p == cls)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != cls and p == cls)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == cls and p != cls)
        support = sum(1 for t in y_true if t == cls)

        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall    = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if (precision + recall) else 0.0)

        per_class[cls] = dict(
            precision=round(precision, 3),
            recall=round(recall, 3),
            f1=round(f1, 3),
            support=support,
        )

    # Macro average: exclude classes with 0 support
    f1s = [pc["f1"] for pc in per_class.values() if pc["support"] > 0]
    macro_f1 = round(sum(f1s) / len(f1s), 3) if f1s else 0.0

    return macro_f1, per_class


# ── Custom metric: per-story classification ───────────────────
class ClassificationMetric(BaseMetric):
    """Per-story metric: did the model classify correctly?

    DeepEval calls .measure() once per LLMTestCase (= one story).
    Score = 1.0 if correct, 0.0 if wrong.
    """

    def __init__(self):
        self.threshold = THRESHOLD
        self.score = 0
        self.reason = ""
        self.success = False

    @property
    def __name__(self):
        return "Credibility Classification"

    def is_successful(self) -> bool:
        return self.success

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        predicted = test_case.actual_output
        expected  = test_case.expected_output

        correct = (predicted == expected)
        self.score   = 1.0 if correct else 0.0
        self.success = correct

        if correct:
            self.reason = f"Correct: {expected}"
        else:
            self.reason = f"Expected {expected}, got {predicted}"

        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)


# ── Build test cases and run ───────────────────────────────────

def run_eval():
    from agents.agent3 import llm_credibility_check

    with open(GOLDEN) as f:
        golden = json.load(f)

    test_cases = []
    y_true = []
    y_pred = []
    story_results = []

    for item in golden:
        story_id  = item["story_id"]
        title     = item["title"]
        content   = item["content"]
        expected  = item["expected_label"]

        print(f"\n  Story {story_id}: {title[:50]}...")

        # Call the actual classification function
        score = llm_credibility_check(title, content)
        predicted = score_to_label(score)

        correct = (predicted == expected)
        y_true.append(expected)
        y_pred.append(predicted)

        story_results.append(dict(
            story_id=story_id,
            title=title[:50],
            expected=expected,
            predicted=predicted,
            score=score,
            correct=correct,
        ))

        # DeepEval test case
        tc = LLMTestCase(
            input=title,
            actual_output=predicted,
            expected_output=expected,
        )
        test_cases.append(tc)

    # ── DeepEval evaluate() ────────────────────────────────────
    metric = ClassificationMetric()
    evaluate(test_cases=test_cases, metrics=[metric])

    # ── Macro-F1 ──────────────────────────────────────────────
    macro_f1, per_class = compute_macro_f1(y_true, y_pred, CLASSES)
    accuracy = sum(1 for r in story_results if r["correct"]) / len(story_results)
    passed = macro_f1 >= THRESHOLD

    # ── Per-story report ──────────────────────────────────────
    print(f"\n{'═' * 75}")
    print(f"  {'#':>3} {'Title':>50}  {'Exp':>8} {'Pred':>8}  {'Score':>6}")
    print(f"{'─' * 75}")

    for sr in story_results:
        mark = "✓" if sr["correct"] else "✗"
        print(f"  {sr['story_id']:>3} {sr['title']:>50}  "
              f"{sr['expected']:>8} {sr['predicted']:>8}  "
              f"{sr['score']:>6.2f} {mark}")

    # ── Confusion matrix ──────────────────────────────────────
    print(f"\n{'═' * 75}")
    print(f"  Confusion Matrix:")
    print(f"  {'':>12} {'REAL':>8} {'OPINION':>8} {'SPAM':>8}")

    for true_cls in CLASSES:
        row = []
        for pred_cls in CLASSES:
            count = sum(1 for t, p in zip(y_true, y_pred)
                       if t == true_cls and p == pred_cls)
            row.append(count)
        print(f"  {true_cls:>12} {row[0]:>8} {row[1]:>8} {row[2]:>8}")

    # ── Per-class metrics ─────────────────────────────────────
    print(f"\n  Per-Class Metrics:")
    print(f"  {'Class':>12} {'P':>8} {'R':>8} {'F1':>8} {'Support':>8}")
    for cls in CLASSES:
        pc = per_class[cls]
        print(f"  {cls:>12} {pc['precision']:>8.3f} {pc['recall']:>8.3f} "
              f"{pc['f1']:>8.3f} {pc['support']:>8}")

    # ── Summary ────────────────────────────────────────────────
    print(f"\n{'═' * 75}")
    print(f"  Macro-F1:   {macro_f1:.3f}  (gate ≥ {THRESHOLD})")
    print(f"  Accuracy:   {sum(1 for r in story_results if r['correct'])}"
          f"/{len(story_results)} ({accuracy:.1%})")
    print(f"  Verdict:    {'PASS ✓' if passed else 'FAIL ✗'}")
    print(f"{'═' * 75}")

    # ── Failures ──────────────────────────────────────────────
    failures = [r for r in story_results if not r["correct"]]
    if failures:
        print(f"\n  Failures ({len(failures)}):")
        for f in failures:
            print(f"    {f['title']} — expected {f['expected']}, "
                  f"got {f['predicted']} (score={f['score']:.2f})")

    return macro_f1, passed


# ── pytest (DeepEval style) ────────────────────────────────────
def test_agent3_credibility():
    macro_f1, passed = run_eval()
    assert passed, f"macro-F1 {macro_f1:.3f} < {THRESHOLD}"


# ── CLI ────────────────────────────────────────────────────────
if __name__ == "__main__":
    f1, ok = run_eval()
    sys.exit(0 if ok else 1)
