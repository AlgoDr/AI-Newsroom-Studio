"""Agent 6 JUDGE Eval — DeepEval implementation.

Tests _judge_script() from Agent 6 (the LLM judge + Python checks).
The function handles its own cloud→local fallback internally:
  cloud: gpt-oss-120b  →  local: qwen3.5:9b
Metric: section-level flag agreement (precision/recall/F1).
Gate: micro-average F1 ≥ 0.60
"""

import json
import sys
from pathlib import Path

from deepeval import evaluate
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

# ── Paths ──────────────────────────────────────────────────────
EVAL_DIR     = Path(__file__).resolve().parent
EVALS_ROOT   = EVAL_DIR.parent.parent
PROJECT_ROOT = EVALS_ROOT.parent

GOLDEN = EVALS_ROOT / "golden_dataset" / "agent6_judge_v1.json"

sys.path.insert(0, str(PROJECT_ROOT / "experiments"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / "experiments" / ".env")

import os
os.environ.setdefault("GROQ_API_KEY", os.getenv("GROQ_KEY", ""))


# ── Constants ─────────────────────────────────────────────────
SECTION_ORDER = [
    "HOOK", "S1_CONTEXT", "S1_CORE", "S1_TWIST",
    "S2_HOOK", "S2_CORE", "S2_TWIST",
    "S3_HOOK", "S3_CORE", "CTA",
]

THRESHOLD = 0.60          # gate: section-level micro-F1 ≥ 0.60


# ── Helpers ────────────────────────────────────────────────────

def compute_flag_metrics(
    predicted_flags: set[str],
    expected_flags: set[str],
) -> tuple[float, float, float]:
    """Compute precision, recall, F1 for section-level flags.

    Edge cases:
      no predicted, no expected → P=1  R=1  (perfect — nothing to flag)
      no predicted, some expected → P=1  R=0  (too lenient)
      some predicted, no expected → P=0  R=1  (over-flagging)
    """
    if not predicted_flags and not expected_flags:
        return 1.0, 1.0, 1.0

    tp = predicted_flags & expected_flags
    fp = predicted_flags - expected_flags
    fn = expected_flags - predicted_flags

    precision = len(tp) / (len(tp) + len(fp)) if (len(tp) + len(fp)) else 1.0
    recall    = len(tp) / (len(tp) + len(fn)) if (len(tp) + len(fn)) else 1.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)

    return round(precision, 3), round(recall, 3), round(f1, 3)


# ── Custom metric: per-script flag agreement ──────────────────
class JudgeFlagMetric(BaseMetric):
    """Per-script metric: does the judge flag the right sections?

    DeepEval calls .measure() once per LLMTestCase (= one test script).
    Score = section-level flag F1 for that script.
    """

    def __init__(self):
        self.threshold = THRESHOLD
        self.score = 0
        self.reason = ""
        self.success = False

    @property
    def __name__(self):
        return "Judge Flag Agreement"

    def is_successful(self) -> bool:
        return self.success

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        predicted = set(json.loads(test_case.actual_output))
        expected  = set(json.loads(test_case.expected_output))

        precision, recall, f1 = compute_flag_metrics(predicted, expected)

        self.score   = f1
        self.success = f1 >= self.threshold

        if predicted == expected:
            if expected:
                self.reason = f"Perfect — flagged {sorted(expected)}"
            else:
                self.reason = "Perfect — correctly passed (no flags)"
        else:
            parts = []
            fp = predicted - expected
            fn = expected - predicted
            if fp:
                parts.append(f"false flags: {sorted(fp)}")
            if fn:
                parts.append(f"missed flags: {sorted(fn)}")
            self.reason = (f"P={precision:.2f} R={recall:.2f} F1={f1:.2f} | "
                          + " | ".join(parts))

        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)


# ── Build test cases and run ───────────────────────────────────

def run_eval():
    from agents.agent6 import _judge_script

    with open(GOLDEN) as f:
        golden = json.load(f)

    test_cases     = []
    script_results = []

    # Global pools for micro-average
    all_pred_flags: set[tuple[int, str]] = set()   # (script_id, section)
    all_exp_flags:  set[tuple[int, str]] = set()

    # Secondary tracking
    verdict_correct = 0
    cta_cat_correct = 0
    cta_ok_correct  = 0
    total = 0

    for item in golden:
        sid        = item["script_id"]
        difficulty = item["difficulty"]
        sections   = item["sections"]
        word_count = item["word_count"]
        exp_flags  = set(item["expected_flagged"])
        exp_verdict = item["expected_verdict"]
        exp_cta_cat = item.get("expected_cta_category", "A")
        exp_cta_ok  = item.get("expected_cta_ok", True)

        # Build script dict as _judge_script expects
        script = {
            "sections": sections,
            "word_count": word_count,
        }

        print(f"\n  Script {sid} ({difficulty}) — {word_count}w, "
              f"expect {'PASS' if exp_verdict == 'pass' else 'FAIL'} ...")

        # Call the actual judge
        judgment = _judge_script(script)

        # Extract predicted flags
        pred_flags = set(judgment.get("flagged_sections", {}).keys())

        # Binary verdict: needs_rewrite if any issue found
        pred_needs_rewrite = (
            bool(judgment.get("flagged_sections"))
            or not judgment.get("word_count_ok", True)
            or not judgment.get("cta_ok", True)
        )
        pred_verdict = "fail" if pred_needs_rewrite else "pass"

        # CTA
        pred_cta_cat = judgment.get("cta_category", "A")
        pred_cta_ok  = judgment.get("cta_ok", True)

        # Per-script flag metrics
        precision, recall, f1 = compute_flag_metrics(pred_flags, exp_flags)

        # Accumulate for micro-average (namespace by script_id)
        for sec in pred_flags:
            all_pred_flags.add((sid, sec))
        for sec in exp_flags:
            all_exp_flags.add((sid, sec))

        # Track secondary metrics
        total += 1
        if pred_verdict == exp_verdict:
            verdict_correct += 1
        if pred_cta_cat == exp_cta_cat:
            cta_cat_correct += 1
        if pred_cta_ok == exp_cta_ok:
            cta_ok_correct += 1

        script_results.append(dict(
            script_id=sid, difficulty=difficulty,
            predicted_flags=sorted(pred_flags),
            expected_flags=sorted(exp_flags),
            pred_verdict=pred_verdict, exp_verdict=exp_verdict,
            pred_cta_cat=pred_cta_cat, exp_cta_cat=exp_cta_cat,
            pred_cta_ok=pred_cta_ok, exp_cta_ok=exp_cta_ok,
            word_count_ok=judgment.get("word_count_ok", True),
            precision=precision, recall=recall, f1=f1,
            false_flags=sorted(pred_flags - exp_flags),
            missed_flags=sorted(exp_flags - pred_flags),
        ))

        # DeepEval test case
        tc = LLMTestCase(
            input=json.dumps({"script_id": sid, "word_count": word_count}),
            actual_output=json.dumps(sorted(pred_flags)),
            expected_output=json.dumps(sorted(exp_flags)),
            context=[f"Script {sid} ({difficulty}): {item.get('comment', '')}"],
        )
        test_cases.append(tc)

    # ── DeepEval evaluate() ────────────────────────────────────
    metric = JudgeFlagMetric()
    evaluate(test_cases=test_cases, metrics=[metric])

    # ── Micro-average for section-level flags ──────────────────
    if not all_pred_flags and not all_exp_flags:
        micro_p, micro_r, micro_f1 = 1.0, 1.0, 1.0
    else:
        tp = all_pred_flags & all_exp_flags
        fp = all_pred_flags - all_exp_flags
        fn = all_exp_flags - all_pred_flags

        micro_p = len(tp) / (len(tp) + len(fp)) if (len(tp) + len(fp)) else 1.0
        micro_r = len(tp) / (len(tp) + len(fn)) if (len(tp) + len(fn)) else 1.0
        micro_f1 = (2 * micro_p * micro_r / (micro_p + micro_r)
                    if (micro_p + micro_r) else 0.0)

    micro_p  = round(micro_p, 3)
    micro_r  = round(micro_r, 3)
    micro_f1 = round(micro_f1, 3)
    passed = micro_f1 >= THRESHOLD

    # ── Per-script report ──────────────────────────────────────
    print(f"\n{'═' * 80}")
    print(f"  {'#':>3} {'Diff':>7}  {'P':>6} {'R':>6} {'F1':>6}  "
          f"{'Verd':>5} {'CTA':>4}  Notes")
    print(f"{'─' * 80}")

    for sr in script_results:
        verdict_mark = "✓" if sr["pred_verdict"] == sr["exp_verdict"] else "✗"
        cta_mark = "✓" if sr["pred_cta_cat"] == sr["exp_cta_cat"] else "✗"

        notes = ""
        if sr["false_flags"]:
            notes += f"FP:{sr['false_flags']} "
        if sr["missed_flags"]:
            notes += f"FN:{sr['missed_flags']}"
        if not sr["false_flags"] and not sr["missed_flags"]:
            notes = "✓ perfect"

        print(f"  {sr['script_id']:>3} {sr['difficulty']:>7}  "
              f"{sr['precision']:>6.3f} {sr['recall']:>6.3f} "
              f"{sr['f1']:>6.3f}  "
              f"{verdict_mark:>5} {cta_mark:>4}  {notes}")

    # ── Summary ────────────────────────────────────────────────
    tp_count = len(all_pred_flags & all_exp_flags) if all_pred_flags or all_exp_flags else 0
    total_pred = len(all_pred_flags)
    total_exp  = len(all_exp_flags)

    print(f"\n{'═' * 80}")
    print(f"  Section-level flag agreement (pooled across {len(script_results)} scripts)")
    print(f"    Precision:  {micro_p:.3f}  "
          f"({tp_count}/{total_pred} predicted flags correct)")
    print(f"    Recall:     {micro_r:.3f}  "
          f"({tp_count}/{total_exp} expected flags found)")
    print(f"    F1:         {micro_f1:.3f}  (gate ≥ {THRESHOLD})")
    print(f"    Verdict:    {'PASS ✓' if passed else 'FAIL ✗'}")
    print(f"\n  Secondary metrics:")
    print(f"    Binary verdict accuracy:  "
          f"{verdict_correct}/{total} = {verdict_correct/total:.3f}")
    print(f"    CTA category accuracy:    "
          f"{cta_cat_correct}/{total} = {cta_cat_correct/total:.3f}")
    print(f"    CTA ok accuracy:          "
          f"{cta_ok_correct}/{total} = {cta_ok_correct/total:.3f}")
    print(f"{'═' * 80}")

    return micro_f1, passed


# ── pytest (DeepEval style) ────────────────────────────────────
def test_agent6_judge():
    micro_f1, passed = run_eval()
    assert passed, f"micro-F1 {micro_f1:.3f} < {THRESHOLD}"


# ── CLI ────────────────────────────────────────────────────────
if __name__ == "__main__":
    f1, ok = run_eval()
    sys.exit(0 if ok else 1)
