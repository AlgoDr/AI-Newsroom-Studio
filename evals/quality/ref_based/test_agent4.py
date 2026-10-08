"""Agent 4 Dedup Eval — DeepEval implementation.

Tests deduplicate_topics() from Agent 4 (the only LLM-dependent function).
Model: qwen3.5:9b (local only — no cloud backend).
Metric: merge precision and recall of story-pair groupings.
Gate: micro-average F1 ≥ 0.70
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

GOLDEN = EVALS_ROOT / "golden_dataset" / "agent4_dedup_v1.json"

sys.path.insert(0, str(PROJECT_ROOT / "experiments"))


# ── Helpers ────────────────────────────────────────────────────

def clusters_to_pairs(clusters: list[list[int]]) -> set[tuple[int, int]]:
    """Convert cluster format [[1,5],[2],[3]] → set of sorted pairs.

    A cluster [1, 5, 3] → pairs {(1,3), (1,5), (3,5)}.
    Singletons produce no pairs.
    """
    pairs = set()
    for group in clusters:
        sg = sorted(group)
        for i in range(len(sg)):
            for j in range(i + 1, len(sg)):
                pairs.add((sg[i], sg[j]))
    return pairs


def extract_predicted_clusters(stories: dict, sid_to_idx: dict) -> list[list[int]]:
    """Read cluster assignments written by deduplicate_topics().

    Returns clusters as list-of-lists of 1-based indices
    (matching the golden dataset format).
    """
    bucket: dict[int, list[int]] = {}
    for sid, story in stories.items():
        cid = story.get("_topic_cluster", -1)
        bucket.setdefault(cid, []).append(sid_to_idx[sid])

    return [sorted(members) for members in bucket.values()]


def compute_merge_metrics(
    predicted_pairs: set[tuple[int, int]],
    expected_pairs: set[tuple[int, int]],
) -> tuple[float, float, float]:
    """Compute merge precision, recall, and F1.

    Edge cases (0/0):
      no predicted, no expected → P=1  R=1  (perfect — nothing to do)
      no predicted, some expected → P=1  R=0  (too conservative)
      some predicted, no expected → P=0  R=1  (over-merging)
    """
    if not predicted_pairs and not expected_pairs:
        return 1.0, 1.0, 1.0

    correct = predicted_pairs & expected_pairs

    precision = len(correct) / len(predicted_pairs) if predicted_pairs else 1.0
    recall    = len(correct) / len(expected_pairs)  if expected_pairs  else 1.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)

    return round(precision, 3), round(recall, 3), round(f1, 3)


# ── Custom metric: per-set merge quality ─────────────────────
class DedupMergeMetric(BaseMetric):
    """Per-set metric: are the model's story groupings correct?

    DeepEval calls .measure() once per LLMTestCase (= one test set).
    Score = merge F1 for that set.
    """

    def __init__(self):
        self.threshold = 0.70
        self.score = 0
        self.reason = ""
        self.success = False

    @property
    def __name__(self):
        return "Dedup Merge Quality"

    def is_successful(self) -> bool:
        return self.success

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        predicted = json.loads(test_case.actual_output)
        expected  = json.loads(test_case.expected_output)

        pred_pairs = clusters_to_pairs(predicted)
        exp_pairs  = clusters_to_pairs(expected)

        precision, recall, f1 = compute_merge_metrics(pred_pairs, exp_pairs)

        self.score   = f1
        self.success = f1 >= self.threshold

        if pred_pairs == exp_pairs:
            self.reason = f"Perfect — {len(exp_pairs)} expected pair(s) matched"
        else:
            parts = []
            fp = pred_pairs - exp_pairs
            fn = exp_pairs  - pred_pairs
            if fp:
                parts.append(f"false merges: {sorted(fp)}")
            if fn:
                parts.append(f"missed merges: {sorted(fn)}")
            self.reason = (f"P={precision:.2f} R={recall:.2f} F1={f1:.2f} | "
                           + " | ".join(parts))

        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)


# ── Build test cases and run ───────────────────────────────────
THRESHOLD = 0.70          # gate: micro-F1 ≥ 0.70


def run_eval():
    from agents.agent4 import deduplicate_topics

    with open(GOLDEN) as f:
        golden = json.load(f)

    test_cases  = []
    set_results = []

    # Global pair pools for micro-average
    all_pred_pairs: set[tuple[int, int]] = set()
    all_exp_pairs:  set[tuple[int, int]] = set()

    for test_set in golden:
        set_id     = test_set["set_id"]
        difficulty = test_set["difficulty"]
        titles     = test_set["titles"]
        expected   = test_set["expected_clusters"]

        # ── Build mock story dicts ─────────────────────────────
        # deduplicate_topics only reads title + editorial_score.
        # Descending scores so the first title in a cluster always
        # "wins" — keeps survivor deterministic for debugging.
        stories:    dict = {}
        sid_to_idx: dict[str, int] = {}

        for i, title in enumerate(titles):
            sid = f"eval_s{set_id}_{i + 1}"
            stories[sid] = {
                "title": title,
                "editorial_score": 100 - i,
            }
            sid_to_idx[sid] = i + 1          # 1-based like the golden

        # ── Call the agent ─────────────────────────────────────
        print(f"\n  Set {set_id} ({difficulty}) — {len(titles)} titles ...")
        result = deduplicate_topics(stories)

        # ── Extract predicted clusters ─────────────────────────
        predicted = extract_predicted_clusters(result, sid_to_idx)

        pred_pairs = clusters_to_pairs(predicted)
        exp_pairs  = clusters_to_pairs(expected)

        precision, recall, f1 = compute_merge_metrics(pred_pairs, exp_pairs)

        # Offset pairs into a global namespace for micro-average
        off = (set_id - 1) * 100
        all_pred_pairs |= {(a + off, b + off) for a, b in pred_pairs}
        all_exp_pairs  |= {(a + off, b + off) for a, b in exp_pairs}

        set_results.append(dict(
            set_id=set_id, difficulty=difficulty,
            predicted=sorted([sorted(g) for g in predicted]),
            expected=sorted([sorted(g) for g in expected]),
            precision=precision, recall=recall, f1=f1,
            false_merges=sorted(pred_pairs - exp_pairs),
            missed_merges=sorted(exp_pairs - pred_pairs),
        ))

        # ── DeepEval test case ─────────────────────────────────
        tc = LLMTestCase(
            input=json.dumps(titles),
            actual_output=json.dumps(
                sorted([sorted(g) for g in predicted])),
            expected_output=json.dumps(
                sorted([sorted(g) for g in expected])),
            context=[f"Set {set_id} ({difficulty}): "
                     f"{test_set.get('comment', '')}"],
        )
        test_cases.append(tc)

    # ── DeepEval evaluate() ────────────────────────────────────
    metric = DedupMergeMetric()
    evaluate(test_cases=test_cases, metrics=[metric])

    # ── Dataset-level micro-average ────────────────────────────
    micro_p, micro_r, micro_f1 = compute_merge_metrics(
        all_pred_pairs, all_exp_pairs)
    passed = micro_f1 >= THRESHOLD

    # ── Per-set report ─────────────────────────────────────────
    print(f"\n{'═' * 70}")
    print(f"  {'Set':>4} {'Diff':>8}  {'P':>6} {'R':>6} {'F1':>6}  Notes")
    print(f"{'─' * 70}")

    for sr in set_results:
        notes = ""
        if sr["false_merges"]:
            notes += f"FP:{sr['false_merges']} "
        if sr["missed_merges"]:
            notes += f"FN:{sr['missed_merges']}"
        if not sr["false_merges"] and not sr["missed_merges"]:
            notes = "✓ perfect"

        print(f"  {sr['set_id']:>4} {sr['difficulty']:>8}  "
              f"{sr['precision']:>6.3f} {sr['recall']:>6.3f} "
              f"{sr['f1']:>6.3f}  {notes}")

    # ── Summary ────────────────────────────────────────────────
    total_correct   = len(all_pred_pairs & all_exp_pairs)
    total_predicted = len(all_pred_pairs)
    total_expected  = len(all_exp_pairs)

    print(f"\n{'═' * 70}")
    print(f"  Micro-average  (pooled across {len(set_results)} sets)")
    print(f"    Precision:  {micro_p:.3f}  "
          f"({total_correct}/{total_predicted} predicted merges correct)")
    print(f"    Recall:     {micro_r:.3f}  "
          f"({total_correct}/{total_expected} expected merges found)")
    print(f"    F1:         {micro_f1:.3f}  (gate ≥ {THRESHOLD})")
    print(f"    Verdict:    {'PASS ✓' if passed else 'FAIL ✗'}")
    print(f"{'═' * 70}")

    return micro_f1, passed


# ── pytest (DeepEval style) ────────────────────────────────────
def test_agent4_dedup():
    micro_f1, passed = run_eval()
    assert passed, f"micro-F1 {micro_f1:.3f} < {THRESHOLD}"


# ── CLI ────────────────────────────────────────────────────────
if __name__ == "__main__":
    f1, ok = run_eval()
    sys.exit(0 if ok else 1)
