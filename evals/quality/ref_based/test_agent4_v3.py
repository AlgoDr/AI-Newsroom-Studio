"""Agent 4 Dedup Eval — V3: fixed prompt + multi-model support.

Usage:
  python test_agent4_v3.py                    # default: qwen3.5:9b
  python test_agent4_v3.py gemma4:12b-mlx     # test different model
  python test_agent4_v3.py granite4.2:8b
"""

import json
import sys
import re
from pathlib import Path

EVAL_DIR     = Path(__file__).resolve().parent
EVALS_ROOT   = EVAL_DIR.parent.parent
PROJECT_ROOT = EVALS_ROOT.parent

GOLDEN = EVALS_ROOT / "golden_dataset" / "agent4_dedup_v1.json"

sys.path.insert(0, str(PROJECT_ROOT / "experiments"))

from test_agent4 import (
    clusters_to_pairs, compute_merge_metrics, THRESHOLD
)


def extract_predicted_clusters(stories: dict, sid_to_idx: dict):
    bucket = {}
    for sid, story in stories.items():
        cid = story.get("_topic_cluster", -1)
        bucket.setdefault(cid, []).append(sid_to_idx[sid])
    return [sorted(members) for members in bucket.values()]


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


def v3_deduplicate(stories: dict, model: str) -> dict:
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
                    # Skip title strings — don't extract leading digits
                    # from titles like "25 Gbps Thunderbolt..."
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
            best_sid = max(cluster_sids, key=lambda s: stories[s].get("editorial_score", 0))
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


def run_eval(model: str):
    import time

    with open(GOLDEN) as f:
        golden = json.load(f)

    all_pred_pairs = set()
    all_exp_pairs  = set()
    set_results    = []
    start_time     = time.time()

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

        print(f"\n  Set {set_id} ({difficulty}) — {len(titles)} titles ...")
        result = v3_deduplicate(stories, model)

        predicted = extract_predicted_clusters(result, sid_to_idx)
        pred_pairs = clusters_to_pairs(predicted)
        exp_pairs  = clusters_to_pairs(expected)
        precision, recall, f1 = compute_merge_metrics(pred_pairs, exp_pairs)

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

    elapsed = time.time() - start_time
    micro_p, micro_r, micro_f1 = compute_merge_metrics(all_pred_pairs, all_exp_pairs)
    passed = micro_f1 >= THRESHOLD

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

    total_correct   = len(all_pred_pairs & all_exp_pairs)
    total_predicted = len(all_pred_pairs)
    total_expected  = len(all_exp_pairs)

    print(f"\n{'═' * 70}")
    print(f"  MODEL: {model}  |  PROMPT: V3  |  think=False")
    print(f"  Time: {elapsed:.1f}s  ({elapsed/len(set_results):.1f}s/set)")
    print(f"  Micro-average  (pooled across {len(set_results)} sets)")
    print(f"    Precision:  {micro_p:.3f}  ({total_correct}/{total_predicted} correct)")
    print(f"    Recall:     {micro_r:.3f}  ({total_correct}/{total_expected} found)")
    print(f"    F1:         {micro_f1:.3f}  (gate ≥ {THRESHOLD})")
    print(f"    Baseline:   0.333  (qwen3.5:9b, prompt v1)")
    print(f"    Delta:      {micro_f1 - 0.333:+.3f}")
    print(f"    Verdict:    {'PASS ✓' if passed else 'FAIL ✗'}")
    print(f"{'═' * 70}")

    return micro_f1, passed


if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen3.5:9b"
    print(f"  Running Agent 4 dedup eval with model: {model}")
    f1, ok = run_eval(model)
    sys.exit(0 if ok else 1)
