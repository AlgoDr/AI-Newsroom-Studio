#!/usr/bin/env python3
"""
B2 — Agent 2 Tool-Access Replay

Replays fetch_url_content() on N cached URLs from stories_cache.json
and records which tier served each one (trafilatura / jina / tavily / none).

Prints a breakdown table with tier share, latency per tier, and the
empty-content rate. Exit 0 if healthy, exit 1 if empty rate is too high.

Usage:
    python evals/ops/tool_access_replay.py             # default 40 URLs
    python evals/ops/tool_access_replay.py --urls 10   # quick test
"""

import sys
import time
import statistics
import argparse

# ── path setup ──────────────────────────────────────────────
# Agent 2 loads .env at module level from CWD — point dotenv at
# the actual file before importing so the Groq client initialises.
import os
import dotenv
dotenv.load_dotenv(os.path.join("experiments", ".env"))

sys.path.insert(0, "experiments")
from agents.agent2 import fetch_url_content

# add evals to path for dataset loader
sys.path.insert(0, ".")
from evals.dataset import load_stories_cache

# ── config ──────────────────────────────────────────────────
MAX_EMPTY_RATE = 0.25  # fail if >25% of URLs return empty content



def run_replay(n_urls: int) -> dict:
    """Replay fetch_url_content on n_urls cached URLs."""
    cache = load_stories_cache()

    # pick URLs that actually exist
    urls = [s["url"] for s in cache.values() if s.get("url", "").startswith("http")]
    if len(urls) < n_urls:
        print(f"  Warning: only {len(urls)} URLs available, "
              f"requested {n_urls}")
        n_urls = len(urls)
    urls = urls[:n_urls]

    # per-tier tracking
    tier_results = {
        "trafilatura": {"count": 0, "latencies": []},
        "jina":        {"count": 0, "latencies": []},
        "tavily":      {"count": 0, "latencies": []},
        "none":        {"count": 0, "latencies": []},
    }
    failures = 0
    total = 0

    for i, url in enumerate(urls, 1):
        total += 1
        t0 = time.time()

        try:
            content, tier = fetch_url_content(url, return_tier=True)
            elapsed = time.time() - t0

            content_len = len(content) if content else 0
            tier_results[tier]["count"] += 1
            tier_results[tier]["latencies"].append(elapsed)

            if content_len == 0:
                failures += 1

            short_url = url[:60] + "..." if len(url) > 60 else url
            print(f"  [{i:2d}/{n_urls}] {elapsed:5.1f}s | "
                  f"{tier:12s} | {content_len:5d} chars | {short_url}")

        except Exception as e:
            elapsed = time.time() - t0
            tier_results["none"]["count"] += 1
            tier_results["none"]["latencies"].append(elapsed)
            failures += 1
            print(f"  [{i:2d}/{n_urls}] {elapsed:5.1f}s | "
                  f"{'EXCEPTION':12s} | {e}")

    return {
        "tier_results": tier_results,
        "failures":     failures,
        "total":        total,
    }


def summarize(results: dict) -> bool:
    """Print summary table, return True if healthy."""
    tiers    = results["tier_results"]
    failures = results["failures"]
    total    = results["total"]
    empty_rate = failures / total if total > 0 else 0

    print()
    print("=" * 60)
    print("B2 — AGENT 2 TOOL-ACCESS REPLAY SUMMARY")
    print("=" * 60)
    print(f"  URLs tested: {total}")
    print()

    # tier breakdown
    print(f"  {'Tier':<14s} {'Count':>5s} {'Share':>7s} "
          f"{'p50(s)':>7s} {'p95(s)':>7s}")
    print(f"  {'-'*14} {'-'*5} {'-'*7} {'-'*7} {'-'*7}")

    for tier_name in ["trafilatura", "jina", "tavily", "none"]:
        t = tiers[tier_name]
        count = t["count"]
        share = count / total if total > 0 else 0
        if t["latencies"]:
            p50 = statistics.median(t["latencies"])
            sorted_lat = sorted(t["latencies"])
            p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
            print(f"  {tier_name:<14s} {count:5d} {share:6.0%} "
                  f"{p50:7.1f} {p95:7.1f}")
        else:
            print(f"  {tier_name:<14s} {count:5d} {share:6.0%} "
                  f"{'—':>7s} {'—':>7s}")

    print()
    print(f"  Empty content: {failures}/{total} ({empty_rate:.1%})")
    print()

    # verdict
    healthy = True
    if empty_rate > MAX_EMPTY_RATE:
        print(f"  ✗ FAIL: empty rate {empty_rate:.1%} > "
              f"{MAX_EMPTY_RATE:.0%}")
        healthy = False
    else:
        print(f"  ✓ PASS: empty rate {empty_rate:.1%} ≤ "
              f"{MAX_EMPTY_RATE:.0%}")

    # check if tier 1 handles majority
    t1_share = tiers["trafilatura"]["count"] / total if total > 0 else 0
    if t1_share >= 0.50:
        print(f"  ✓ INFO: trafilatura serves {t1_share:.0%} of URLs "
              f"(primary tier healthy)")
    else:
        print(f"  ⚠ WARN: trafilatura serves only {t1_share:.0%} of URLs "
              f"(fallback tiers doing heavy lifting)")

    print()
    print("  OVERALL:", "HEALTHY" if healthy else "UNHEALTHY")
    print("=" * 60)
    return healthy


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="B2 — Agent 2 tool-access replay")
    parser.add_argument("--urls", type=int, default=40,
                        help="Number of URLs to replay (default: 40)")
    args = parser.parse_args()

    print(f"B2 — Replaying fetch_url_content × {args.urls} URLs")
    print("-" * 60)

    results = run_replay(args.urls)
    healthy = summarize(results)
    sys.exit(0 if healthy else 1)
