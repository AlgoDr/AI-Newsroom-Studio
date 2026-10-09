"""Agent 3 Credibility Eval — DeepEval implementation."""

import json
import sys
from pathlib import Path

from deepeval import evaluate
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase
from deepeval.dataset import EvaluationDataset

# ── Paths ──────────────────────────────────────────────────────
EVAL_DIR     = Path(__file__).resolve().parent
EVALS_ROOT   = EVAL_DIR.parent.parent
PROJECT_ROOT = EVALS_ROOT.parent

GOLDEN = EVALS_ROOT / "golden_dataset" / "agent3_credibility_v1.json"
CACHE  = PROJECT_ROOT / "experiments" / "data" / "stories_cache.json"

sys.path.insert(0, str(PROJECT_ROOT / "experiments"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / "experiments" / ".env")

import os
os.environ.setdefault("GROQ_API_KEY", os.getenv("GROQ_KEY", ""))




# ── Custom metric: exact-match classification ──────────────────
class ClassificationMetric(BaseMetric):
    """Per-case metric: does predicted label match human label?

    DeepEval calls .measure() once per LLMTestCase.
    Each call compares actual_output vs expected_output.
    """

    def __init__(self):
        self.threshold = 1.0    # exact match = score is 0 or 1
        self.score = 0          # set by measure()
        self.reason = ""        # set by measure()
        self.success = False    # set by measure()

    @property
    def __name__(self):
        return "Classification Match"
    
    def is_successful(self) -> bool:
        return self.success

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        expected = (test_case.expected_output or "").strip().upper()
        actual   = (test_case.actual_output or "").strip().upper()

        if actual == expected:
            self.score = 1.0
            self.success = True
            self.reason = f"Correct: {actual}"
        else:
            self.score = 0.0
            self.success = False
            self.reason = f"Expected {expected}, got {actual}"

        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)











# ── Dataset-level metric: macro-F1 ─────────────────────────────
LABELS = ["REAL", "OPINION", "SPAM"]

def compute_macro_f1(y_true: list[str], y_pred: list[str]):
    """Confusion matrix + per-class P/R/F1 + macro-F1.

    Pure Python — no sklearn. Deterministic math stays in Python,
    not delegated to a library or an LLM.
    """
    matrix = {t: {p: 0 for p in LABELS} for t in LABELS}
    for t, p in zip(y_true, y_pred):
        if t in matrix and p in matrix[t]:
            matrix[t][p] += 1

    class_metrics = {}
    f1_scores = []

    for label in LABELS:
        tp = matrix[label][label]
        fp = sum(matrix[r][label] for r in LABELS if r != label)
        fn = sum(matrix[label][c] for c in LABELS if c != label)

        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec  = tp / (tp + fn) if (tp + fn) else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

        support = sum(matrix[label].values())
        class_metrics[label] = dict(precision=round(prec, 3),
                                     recall=round(rec, 3),
                                     f1=round(f1, 3),
                                     support=support)
        if support > 0:
            f1_scores.append(f1)

    macro_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0.0
    return matrix, class_metrics, round(macro_f1, 3)







# ── Build test cases and run ───────────────────────────────────
THRESHOLD = 0.70

def run_eval(backend: str = "groq"):
    from agents.agent3 import classify_credibility

    # Load data
    with open(GOLDEN) as f:
        golden = json.load(f)
    with open(CACHE) as f:
        cache = json.load(f)

    # ── Step 1: Run agent, build LLMTestCase objects ───────────
    test_cases = []
    skipped = []

    for i, item in enumerate(golden):
        title     = item["input"]
        expected  = item["expected_output"]
        story_key = item["additional_metadata"]["story_key"]

        story   = cache.get(story_key, {})
        content = story.get("content", "")

        if not content or len(content) < 50:
            skipped.append((i, title, "content missing or < 50 chars"))
            continue

        # Call the actual agent
        predicted = classify_credibility(title, content, backend)
        if predicted is None:
            skipped.append((i, title, "model returned None"))
            predicted = "NONE"

        # Package as DeepEval test case
        tc = LLMTestCase(
            input=title,
            actual_output=predicted,
            expected_output=expected,
            context=[content[:200]],   # first 200 chars for DeepEval report
        )
        test_cases.append(tc)

    # ── Step 2: Run DeepEval evaluate() ────────────────────────
    metric = ClassificationMetric()
    results = evaluate(test_cases=test_cases, metrics=[metric])

    # ── Step 3: Dataset-level macro-F1 ─────────────────────────
    y_true = [tc.expected_output for tc in test_cases]
    y_pred = [tc.actual_output   for tc in test_cases]

    matrix, class_metrics, macro_f1 = compute_macro_f1(y_true, y_pred)
    passed = macro_f1 >= THRESHOLD

    # ── Report ─────────────────────────────────────────────────
    present = [l for l in LABELS if class_metrics[l]["support"] > 0
               or any(matrix[r][l] for r in LABELS)]

    print(f"\n{'─' * 50}")
    print("  Confusion Matrix  (rows = actual, cols = predicted)")
    print(f"{'─' * 50}")
    header = f"{'':>10}" + "".join(f"{l:>10}" for l in present)
    print(header)
    for row_label in present:
        row = f"{row_label:>10}"
        for col_label in present:
            row += f"{matrix[row_label][col_label]:>10d}"
        print(row)

    print(f"\n{'─' * 50}")
    print(f"  {'Class':>10}  {'Prec':>7} {'Recall':>7} {'F1':>7} {'N':>5}")
    print(f"{'─' * 50}")
    for label in present:
        m = class_metrics[label]
        print(f"  {label:>10}  {m['precision']:>7.3f} {m['recall']:>7.3f} "
              f"{m['f1']:>7.3f} {m['support']:>5d}")

    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    print(f"\n{'═' * 50}")
    print(f"  Macro-F1:  {macro_f1:.3f}  (gate ≥ {THRESHOLD})")
    print(f"  Accuracy:  {correct}/{len(y_true)} = "
          f"{correct/len(y_true):.3f}  (reference only)")
    print(f"  Verdict:   {'PASS ✓' if passed else 'FAIL ✗'}")
    print(f"{'═' * 50}")

    if skipped:
        print(f"\n  Skipped ({len(skipped)}):")
        for idx, title, reason in skipped:
            print(f"    [{idx+1}] {title[:50]} — {reason}")

    return macro_f1, passed





# ── pytest (DeepEval style) ────────────────────────────────────
def test_agent3_credibility_groq():
    macro_f1, passed = run_eval("groq")
    assert passed, f"macro-F1 {macro_f1:.3f} < {THRESHOLD}"

def test_agent3_credibility_local():
    macro_f1, passed = run_eval("local")
    assert passed, f"macro-F1 {macro_f1:.3f} < {THRESHOLD}"


# ── CLI ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default="groq",
                        choices=["groq", "local", "both"])
    args = parser.parse_args()

    if args.backend == "both":
        g_f1, g_ok = run_eval("groq")
        l_f1, l_ok = run_eval("local")
        print(f"\n  Summary: groq={g_f1:.3f} {'✓' if g_ok else '✗'}"
              f" | local={l_f1:.3f} {'✓' if l_ok else '✗'}")
        sys.exit(0 if (g_ok and l_ok) else 1)
    else:
        _, ok = run_eval(args.backend)
        sys.exit(0 if ok else 1)