"""Agent 4 Dedup — granite4.2:8b N=5 Reliability Test.

Runs the Agent 4 dedup eval (Prompt V3 + granite4.2:8b) five times
on the same golden dataset to confirm the F1=0.800 result is stable,
not a lucky run.

Pass criteria: ≥4 of 5 runs pass the F1≥0.70 gate.

Usage:
  cd NewsStudio
  python evals/quality/ref_based/test_agent4_granite_n5.py
"""

import json
import re
import sys
import time
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────
EVAL_DIR     = Path(__file__).resolve().parent
EVALS_ROOT   = EVAL_DIR.parent.parent
PROJECT_ROOT = EVALS_ROOT.parent

GOLDEN = EVALS_ROOT / "golden_dataset" / "agent4_dedup_v1.json"

# ── Constants ──────────────────────────────────────────────────
MODEL = "granite4.2:8b"
N_RUNS = 5
THRESHOLD = 0.70
STABILITY_GATE = 4   # ≥4 of 5 must pass


# ── Prompt V3 ──────────────────────────────────────────────────
PROMPT_V3 = """Group these numbered titles by SAME specific event or product.

Rules:
- SAME group: same product launch, same CVE, same court ruling, same company announcement
- SAME group: "ProductX 3" and "ProductX 3 Pro variant" = same product family
- SAME group: two RFCs about the same standard (e.g. TLS 1.2 deprecation) = same effort
- DIFFERENT: two stories that share a tech domain (both AI, both C++, both security) but are about different specific things
- When in doubt → SEPARATE groups

Titles:
{titles}

Return ONLY a JSON array of arrays of integers (1-indexed).
Every number from 1 to {n} must appear exactly once.
Example for 6 titles where 2 and 5 cover the same event:
[[1],[2,5],[3],[4],[6]]

JSON:"""


# ── Helpers (inlined — no cross-file imports) ──────────────────

def clusters_to_pairs(clusters: list[list[int]]) -> set[tuple[int, int]]:
    """Convert cluster lists to sorted pairs for comparison.
    [[1,2,5],[3],[4]] → {(1,2), (1,5), (2,5)}
    """
    pairs = set()
    for group in clusters:
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = sorted((group[i], group[j]))
                pairs.add((a, b))
    return pairs


def compute_merge_metrics(
    predicted_pairs: set[tuple[int, int]],
    expected_pairs: set[tuple[int, int]],
) -> tuple[float, float, float]:
    """Precision, recall, F1 for merge pairs."""
    if not predicted_pairs and not expected_pairs:
        return 1.0, 1.0, 1.0

    tp = predicted_pairs & expected_pairs
    fp = predicted_pairs - expected_pairs
    fn = expected_pairs - predicted_pairs

    precision = len(tp) / (len(tp) + len(fp)) if (len(tp) + len(fp)) else 1.0
    recall    = len(tp) / (len(tp) + len(fn)) if (len(tp) + len(fn)) else 1.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)

    return round(precision, 3), round(recall, 3), round(f1, 3)


def extract_predicted_clusters(stories: dict, sid_to_idx: dict):
    """Extract cluster groupings from story dicts."""
    bucket = {}
    for sid, story in stories.items():
        cid = story.get("_topic_cluster", -1)
        bucket.setdefault(cid, []).append(sid_to_idx[sid])
    return [sorted(members) for members in bucket.values()]


def v3_deduplicate(stories: dict, model: str) -> dict:
    """Run Prompt V3 dedup via Ollama."""
    import ollama

    titles = [(sid, story["title"]) for sid, story in stories.items()]
    numbered_titles = "\n".join(
        f"{i+1}. {title}" for i, (_, title) in enumerate(titles)
    )

    prompt = PROMPT_V3.format(titles=numbered_titles, n=len(titles))

    try:
        resp = ollama.generate(
            model=model,
            prompt=prompt,
            stream=False,
            think=False,
            keep_alive=0,
            options={"temperature": 0.1, "num_ctx": 4096},
        )

        raw = resp["response"].strip()
        print(f"  [{model}] raw: {raw[:150]}")

        # Clean JSON
        raw_clean = re.sub(r',\s*]', ']', raw)
        raw_clean = re.sub(r',\s*}', '}', raw_clean)
        raw_compact = raw_clean.replace(" ", "").replace("\n", "").replace("\t", "")

        # Handle missing outer brackets: [1],[2],[3] → [[1],[2],[3]]
        if "[[" not in raw_compact and re.match(r'\[\d', raw_compact):
            raw_compact = "[" + raw_compact + "]"
            print(f"  [{model}] wrapped missing outer brackets")

        start = raw_compact.find("[[")
        end   = raw_compact.rfind("]]") + 2
        if start == -1 or end == 1:
            raise ValueError(f"no JSON array found in: {raw_compact[:80]}")

        clusters = json.loads(raw_compact[start:end])

        # Extract integers — handle mixed string/int
        clean_clusters = []
        for group in clusters:
            nums = []
            for item in group:
                if isinstance(item, int):
                    nums.append(item)
                elif isinstance(item, str):
                    m = re.match(r'^\d+$', item.strip())
                    if m:
                        nums.append(int(m.group()))
            if nums:
                clean_clusters.append(nums)
        clusters = clean_clusters

        print(f"  [{model}] {len(clusters)} clusters found")

        # Assign clusters
        sid_list = [sid for sid, _ in titles]
        assigned = set()

        for cluster_idx, group in enumerate(clusters):
            cluster_sids = []
            for num in group:
                idx = int(num) - 1
                if 0 <= idx < len(sid_list):
                    cluster_sids.append(sid_list[idx])
                    assigned.add(sid_list[idx])
            if not cluster_sids:
                continue
            best_sid = max(cluster_sids,
                          key=lambda s: stories[s].get("editorial_score", 0))
            for sid in cluster_sids:
                stories[sid]["_topic_cluster"] = cluster_idx
                stories[sid]["_is_duplicate"]  = (sid != best_sid)
                if stories[sid]["_is_duplicate"]:
                    print(f"  [{model}] dup → {stories[sid]['title'][:50]}")

        # Safety: any unassigned story gets its own cluster
        next_cid = len(clusters)
        for sid, story in stories.items():
            if sid not in assigned:
                story["_topic_cluster"] = next_cid
                story["_is_duplicate"]  = False
                next_cid += 1

    except Exception as e:
        print(f"  [{model}] FAILED ({type(e).__name__}: {e})")
        for i, (sid, story) in enumerate(stories.items()):
            story["_topic_cluster"] = i
            story["_is_duplicate"]  = False

    return stories


# ── Single run ─────────────────────────────────────────────────

def single_run(run_idx: int) -> dict:
    """Run the eval once, return per-set and aggregate results."""
    with open(GOLDEN) as f:
        golden = json.load(f)

    all_pred_pairs = set()
    all_exp_pairs  = set()
    set_results    = []
    start = time.time()

    for test_set in golden:
        set_id     = test_set["set_id"]
        difficulty = test_set["difficulty"]
        titles     = test_set["titles"]
        expected   = test_set["expected_clusters"]

        stories    = {}
        sid_to_idx = {}
        for i, title in enumerate(titles):
            sid = f"eval_s{set_id}_{i + 1}"
            stories[sid] = {"title": title, "editorial_score": 100 - i}
            sid_to_idx[sid] = i + 1

        result = v3_deduplicate(stories, MODEL)

        predicted  = extract_predicted_clusters(result, sid_to_idx)
        pred_pairs = clusters_to_pairs(predicted)
        exp_pairs  = clusters_to_pairs(expected)
        precision, recall, f1 = compute_merge_metrics(pred_pairs, exp_pairs)

        off = (set_id - 1) * 100
        all_pred_pairs |= {(a + off, b + off) for a, b in pred_pairs}
        all_exp_pairs  |= {(a + off, b + off) for a, b in exp_pairs}

        set_results.append(dict(
            set_id=set_id, difficulty=difficulty,
            precision=precision, recall=recall, f1=f1,
            false_merges=sorted(pred_pairs - exp_pairs),
            missed_merges=sorted(exp_pairs - pred_pairs),
        ))

    elapsed = time.time() - start
    micro_p, micro_r, micro_f1 = compute_merge_metrics(
        all_pred_pairs, all_exp_pairs
    )
    passed = micro_f1 >= THRESHOLD

    return dict(
        run=run_idx + 1,
        micro_p=round(micro_p, 3),
        micro_r=round(micro_r, 3),
        micro_f1=round(micro_f1, 3),
        passed=passed,
        elapsed=round(elapsed, 1),
        sets=set_results,
    )


# ── Main ───────────────────────────────────────────────────────

def main():
    print(f"{'═' * 70}")
    print(f"  Agent 4 Dedup — granite4.2:8b N={N_RUNS} Reliability Test")
    print(f"  Model: {MODEL}  |  Prompt: V3  |  Gate: F1 ≥ {THRESHOLD}")
    print(f"  Stability: ≥{STABILITY_GATE}/{N_RUNS} runs must PASS")
    print(f"{'═' * 70}")

    all_runs = []

    for i in range(N_RUNS):
        print(f"\n{'─' * 70}")
        print(f"  RUN {i + 1}/{N_RUNS}")
        print(f"{'─' * 70}")

        result = single_run(i)
        all_runs.append(result)

        mark = "✓ PASS" if result["passed"] else "✗ FAIL"
        print(f"\n  → Run {i + 1}: F1={result['micro_f1']:.3f} "
              f"P={result['micro_p']:.3f} R={result['micro_r']:.3f} "
              f"({result['elapsed']:.1f}s) {mark}")

    # ── Summary ─────────────────────────────────────────────────
    f1_scores = [r["micro_f1"] for r in all_runs]
    pass_count = sum(1 for r in all_runs if r["passed"])
    stable = pass_count >= STABILITY_GATE

    print(f"\n{'═' * 70}")
    print(f"  RELIABILITY SUMMARY — {MODEL} + Prompt V3")
    print(f"{'─' * 70}")
    print(f"  {'Run':>4}  {'F1':>6}  {'P':>6}  {'R':>6}  {'Time':>6}  Verdict")
    print(f"{'─' * 70}")
    for r in all_runs:
        mark = "✓" if r["passed"] else "✗"
        print(f"  {r['run']:>4}  {r['micro_f1']:>6.3f}  "
              f"{r['micro_p']:>6.3f}  {r['micro_r']:>6.3f}  "
              f"{r['elapsed']:>5.1f}s  {mark}")

    avg_f1 = sum(f1_scores) / len(f1_scores)
    min_f1 = min(f1_scores)
    max_f1 = max(f1_scores)

    print(f"\n  F1: avg={avg_f1:.3f}  min={min_f1:.3f}  max={max_f1:.3f}")
    print(f"  Pass rate: {pass_count}/{N_RUNS}")
    print(f"  Stability: {'STABLE ✓' if stable else 'UNSTABLE ✗'} "
          f"(need ≥{STABILITY_GATE}/{N_RUNS})")

    # ── Per-set stability ───────────────────────────────────────
    print(f"\n{'─' * 70}")
    print(f"  Per-set stability (F1 across {N_RUNS} runs):")
    print(f"{'─' * 70}")

    n_sets = len(all_runs[0]["sets"])
    for s_idx in range(n_sets):
        set_f1s = [r["sets"][s_idx]["f1"] for r in all_runs]
        set_id = all_runs[0]["sets"][s_idx]["set_id"]
        diff   = all_runs[0]["sets"][s_idx]["difficulty"]
        perfect = sum(1 for f in set_f1s if f == 1.0)
        zero   = sum(1 for f in set_f1s if f == 0.0)

        status = ""
        if perfect == N_RUNS:
            status = "✓ always perfect"
        elif zero == N_RUNS:
            status = "✗ always fails"
        else:
            status = f"flaky ({perfect}× perfect, {zero}× zero)"

        f1_str = " ".join(f"{f:.1f}" for f in set_f1s)
        print(f"  Set {set_id:>2} ({diff:>6}): [{f1_str}]  {status}")

    print(f"\n{'═' * 70}")

    # ── Decision ────────────────────────────────────────────────
    if stable:
        print(f"\n  ✅ DECISION: granite4.2:8b + V3 is RELIABLE.")
        print(f"     Safe to apply to production agent4.py.")
    else:
        print(f"\n  ❌ DECISION: granite4.2:8b + V3 is NOT RELIABLE.")
        print(f"     Do NOT apply to production. Investigate flaky sets.")

    print(f"{'═' * 70}\n")

    return stable


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
