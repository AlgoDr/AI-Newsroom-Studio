#!/usr/bin/env python3
"""
B3 — Fallback Stress Test (Agent 3 Local Path)

Forces Agent 3's credibility classification onto the local fallback
model (qwen3.5:9b via Ollama) by monkeypatching the Groq call to
always fail. Runs N cached stories through _llm_credibility_check_local
and measures:
  - Cold start latency (first call, model loading from disk)
  - Warm latency (subsequent calls, model already in memory)
  - Parse success rate (did the model return REAL/OPINION/SPAM?)
  - Classification distribution

Usage:
    python evals/ops/fallback_stress.py             # default 30 stories
    python evals/ops/fallback_stress.py --stories 10
"""

import sys
import os
import time
import statistics
import argparse

# ── env + path setup ────────────────────────────────────────
import dotenv
dotenv.load_dotenv(os.path.join("experiments", ".env"))

sys.path.insert(0, "experiments")
sys.path.insert(0, ".")

from agents.agent3 import (
    _llm_credibility_check_local,
    CREDIBILITY_FALLBACK_MODEL,
)
from evals.dataset import load_stories_cache

# ── config ──────────────────────────────────────────────────
MAX_COLD_LATENCY  = 30.0   # seconds — first call loads model into GPU
MAX_WARM_P95      = 25.0   # seconds — local fallback is slow but reliable
MIN_PARSE_RATE    = 0.80   # at least 80% must return a usable label


def build_prompt(title: str, content: str) -> str:
    """Reproduce the exact prompt Agent 3 sends to the LLM."""
    return f"""Classify what this article is about.

TITLE: {title}

ARTICLE:
{content}

Categories:
- REAL: a genuine product, technology, company, research finding, or event
        (real things can have promotional tone -- that is still REAL)
- OPINION: a personal essay, rant, or opinion piece (not reporting a thing)
- SPAM: scam, clickbait, or misinformation with no real substance

Respond with ONLY one word: REAL, OPINION, or SPAM.

Verdict:"""


def run_stress(n_stories: int) -> dict:
    """Run n_stories through the local fallback path only."""
    cache = load_stories_cache()

    # pick stories with enough content (>500 chars, matching Agent 3's guard)
    stories = [
        v for v in cache.values()
        if len(v.get("content", "")) >= 500
    ][:n_stories]

    if len(stories) < n_stories:
        print(f"  Warning: only {len(stories)} stories with ≥500 char "
              f"content, requested {n_stories}")
        n_stories = len(stories)

    latencies = []
    labels = {"REAL": 0, "OPINION": 0, "SPAM": 0, "UNPARSEABLE": 0}
    cold_latency = None

    for i, story in enumerate(stories, 1):
        title = story["title"]
        content = story["content"][:6000]  # match Agent 3's trim
        prompt = build_prompt(title, content)

        t0 = time.time()
        raw = _llm_credibility_check_local(prompt)
        elapsed = time.time() - t0

        latencies.append(elapsed)

        if i == 1:
            cold_latency = elapsed

        # detect label directly from the raw model output
        parsed_label = None
        if raw and raw.strip():
            upper = raw.strip().upper()
            for word in ["REAL", "OPINION", "SPAM"]:
                if word in upper:
                    parsed_label = word
                    break

        if parsed_label:
            labels[parsed_label] += 1
            lbl = parsed_label
        else:
            labels["UNPARSEABLE"] += 1
            lbl = "???"

        short_title = title[:50] + "..." if len(title) > 50 else title
        print(f"  [{i:2d}/{n_stories}] {elapsed:5.1f}s | "
              f"{lbl:10s} | {short_title}")

    return {
        "latencies":    latencies,
        "cold_latency": cold_latency,
        "labels":       labels,
        "total":        n_stories,
        "model":        CREDIBILITY_FALLBACK_MODEL,
    }


def summarize(results: dict) -> bool:
    """Print summary and return True if healthy."""
    lat     = results["latencies"]
    cold    = results["cold_latency"]
    labels  = results["labels"]
    total   = results["total"]
    model   = results["model"]

    warm_lat = lat[1:] if len(lat) > 1 else lat
    warm_p50 = statistics.median(warm_lat) if warm_lat else 0
    sorted_warm = sorted(warm_lat)
    warm_p95 = sorted_warm[int(len(sorted_warm) * 0.95)] if warm_lat else 0

    parse_ok = total - labels["UNPARSEABLE"]
    parse_rate = parse_ok / total if total > 0 else 0

    print()
    print("=" * 60)
    print("B3 — FALLBACK STRESS TEST SUMMARY")
    print(f"     Model: {model} (local, Ollama)")
    print("=" * 60)
    print(f"  Stories tested: {total}")
    print()

    # latency
    print("  Latency:")
    print(f"    Cold start (1st call):  {cold:5.1f}s")
    print(f"    Warm p50:               {warm_p50:5.1f}s")
    print(f"    Warm p95:               {warm_p95:5.1f}s")
    print()

    # classification distribution
    print(f"  {'Label':<14s} {'Count':>5s} {'Share':>7s}")
    print(f"  {'-'*14} {'-'*5} {'-'*7}")
    for lbl in ["REAL", "OPINION", "SPAM", "UNPARSEABLE"]:
        count = labels[lbl]
        share = count / total if total > 0 else 0
        print(f"  {lbl:<14s} {count:5d} {share:6.0%}")

    print()
    print(f"  Parse success: {parse_ok}/{total} ({parse_rate:.0%})")
    print()

    # verdicts
    healthy = True

    if cold > MAX_COLD_LATENCY:
        print(f"  ✗ FAIL: cold start {cold:.1f}s > {MAX_COLD_LATENCY:.0f}s")
        healthy = False
    else:
        print(f"  ✓ PASS: cold start {cold:.1f}s ≤ {MAX_COLD_LATENCY:.0f}s")

    if warm_p95 > MAX_WARM_P95:
        print(f"  ✗ FAIL: warm p95 {warm_p95:.1f}s > {MAX_WARM_P95:.0f}s")
        healthy = False
    else:
        print(f"  ✓ PASS: warm p95 {warm_p95:.1f}s ≤ {MAX_WARM_P95:.0f}s")

    if parse_rate < MIN_PARSE_RATE:
        print(f"  ✗ FAIL: parse rate {parse_rate:.0%} < {MIN_PARSE_RATE:.0%}")
        healthy = False
    else:
        print(f"  ✓ PASS: parse rate {parse_rate:.0%} ≥ {MIN_PARSE_RATE:.0%}")

    print()
    print("  OVERALL:", "HEALTHY" if healthy else "UNHEALTHY")
    print("=" * 60)
    return healthy


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="B3 — Fallback stress test (Agent 3 local path)")
    parser.add_argument("--stories", type=int, default=30,
                        help="Number of stories to classify (default: 30)")
    args = parser.parse_args()

    print(f"B3 — Stress-testing local fallback × {args.stories} stories")
    print(f"     Model: {CREDIBILITY_FALLBACK_MODEL} via Ollama")
    print("-" * 60)

    results = run_stress(args.stories)
    healthy = summarize(results)
    sys.exit(0 if healthy else 1)
