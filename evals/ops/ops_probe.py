#!/usr/bin/env python3
"""
B1 — Agent 1 Probe Script

Calls fetch_trends() N times against the live HN API and records:
  - wall-clock latency per call
  - story count per call (expect 8)
  - empty-URL count per call (expect 0)

Prints a summary table with p50/p95 latency, min/max story count,
and empty-URL rate. Exit 0 if healthy, exit 1 if any probe fails.

Usage:
    python evals/ops/ops_probe.py            # default 20 runs
    python evals/ops/ops_probe.py --runs 5   # quick smoke test
"""

import sys
import time
import statistics
import argparse

# ── path setup ──────────────────────────────────────────────
sys.path.insert(0, "experiments")
from agents.agent1 import fetch_trends

# ── config ──────────────────────────────────────────────────
EXPECTED_STORIES = 8
MAX_P95_LATENCY  = 15.0   # seconds — fail if p95 exceeds this
MAX_EMPTY_URL_RATE = 0.10  # fail if >10% of stories lack a URL


def run_probe(n_runs: int) -> dict:
    """Run fetch_trends() n_runs times, collect metrics."""
    latencies    = []
    story_counts = []
    empty_urls   = 0
    total_stories = 0
    failures     = 0
    failure_details = []

    for i in range(1, n_runs + 1):
        t0 = time.time()
        try:
            stories = fetch_trends(top_n=EXPECTED_STORIES)
            elapsed = time.time() - t0

            n_stories = len(stories)
            n_empty   = sum(1 for s in stories if not s.get("url"))

            latencies.append(elapsed)
            story_counts.append(n_stories)
            empty_urls += n_empty
            total_stories += n_stories

            status = "OK"
            if n_stories < EXPECTED_STORIES:
                status = f"LOW ({n_stories})"

            print(f"  [{i:2d}/{n_runs}] {elapsed:5.1f}s | "
                  f"{n_stories} stories | "
                  f"{n_empty} empty URLs | {status}")

        except Exception as e:
            elapsed = time.time() - t0
            failures += 1
            failure_details.append(f"run {i}: {e}")
            print(f"  [{i:2d}/{n_runs}] {elapsed:5.1f}s | FAILED: {e}")

    return {
        "latencies":      latencies,
        "story_counts":   story_counts,
        "empty_urls":     empty_urls,
        "total_stories":  total_stories,
        "failures":       failures,
        "failure_details": failure_details,
        "n_runs":         n_runs,
    }


def summarize(results: dict) -> bool:
    """Print summary table, return True if healthy."""
    latencies     = results["latencies"]
    story_counts  = results["story_counts"]
    empty_urls    = results["empty_urls"]
    total_stories = results["total_stories"]
    failures      = results["failures"]
    n_runs        = results["n_runs"]
    successful    = n_runs - failures

    print()
    print("=" * 60)
    print("B1 — AGENT 1 PROBE SUMMARY")
    print("=" * 60)

    if not latencies:
        print("  ALL RUNS FAILED — no data to summarize")
        return False

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95)]
    p_min = min(latencies)
    p_max = max(latencies)

    min_stories = min(story_counts)
    max_stories = max(story_counts)
    avg_stories = statistics.mean(story_counts)

    empty_rate = empty_urls / total_stories if total_stories > 0 else 0

    print(f"  Runs:          {successful}/{n_runs} succeeded "
          f"({failures} failures)")
    print()
    print(f"  Latency (s):   p50={p50:.1f}  p95={p95:.1f}  "
          f"min={p_min:.1f}  max={p_max:.1f}")
    print(f"  Stories/call:  min={min_stories}  max={max_stories}  "
          f"avg={avg_stories:.1f}  (expect {EXPECTED_STORIES})")
    print(f"  Empty URLs:    {empty_urls}/{total_stories} "
          f"({empty_rate:.1%})")
    print()

    # ── verdicts ────────────────────────────────────────────
    healthy = True

    if p95 > MAX_P95_LATENCY:
        print(f"  ✗ FAIL: p95 latency {p95:.1f}s > {MAX_P95_LATENCY}s")
        healthy = False
    else:
        print(f"  ✓ PASS: p95 latency {p95:.1f}s ≤ {MAX_P95_LATENCY}s")

    if min_stories < EXPECTED_STORIES:
        print(f"  ✗ FAIL: got {min_stories} stories on at least one run "
              f"(expect {EXPECTED_STORIES})")
        healthy = False
    else:
        print(f"  ✓ PASS: always returned {EXPECTED_STORIES} stories")

    if empty_rate > MAX_EMPTY_URL_RATE:
        print(f"  ✗ FAIL: empty-URL rate {empty_rate:.1%} > "
              f"{MAX_EMPTY_URL_RATE:.0%}")
        healthy = False
    else:
        print(f"  ✓ PASS: empty-URL rate {empty_rate:.1%} ≤ "
              f"{MAX_EMPTY_URL_RATE:.0%}")

    if failures > 0:
        print(f"  ✗ FAIL: {failures} run(s) threw an exception")
        for d in results["failure_details"]:
            print(f"         {d}")
        healthy = False
    else:
        print(f"  ✓ PASS: 0 exceptions")

    print()
    print("  OVERALL:", "HEALTHY" if healthy else "UNHEALTHY")
    print("=" * 60)
    return healthy


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="B1 — Agent 1 probe")
    parser.add_argument("--runs", type=int, default=20,
                        help="Number of probe runs (default: 20)")
    args = parser.parse_args()

    print(f"B1 — Probing Agent 1 (fetch_trends) × {args.runs} runs")
    print("-" * 60)

    results = run_probe(args.runs)
    healthy = summarize(results)
    sys.exit(0 if healthy else 1)
