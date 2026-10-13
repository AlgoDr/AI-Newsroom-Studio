#!/usr/bin/env python3
"""
B5 — Chaos Checks

Simulates three failure modes by monkeypatching external services and
verifying the pipeline degrades gracefully (finishes via fallback, never
crashes).

Tests:
  1. Groq 429  — Agent 3 credibility check falls back to local qwen3.5:9b
  2. Exa down  — Agent 3 cross-verification falls back to DDG
  3. DDG timeout — Agent 3 cross-verification returns neutral (safe default)

Each test patches one service, runs one real story through the affected
function, and checks that:
  a) No exception escapes (pipeline would crash)
  b) A usable result comes back (not None/crash)
  c) The fallback path fired (detected via captured print output)

Usage:
    python evals/ops/chaos_checks.py
"""

import sys
import os
import io
import contextlib
from unittest.mock import patch, MagicMock

# ── env + path setup ────────────────────────────────────────
import dotenv
dotenv.load_dotenv(os.path.join("experiments", ".env"))

sys.path.insert(0, "experiments")
sys.path.insert(0, ".")

from evals.dataset import load_stories_cache

# ── pick a test story ───────────────────────────────────────
cache = load_stories_cache()
STORY = None
for v in cache.values():
    if len(v.get("content", "")) >= 500:
        STORY = v
        break

if STORY is None:
    print("ERROR: no story with ≥500 chars in cache")
    sys.exit(1)

TITLE   = STORY["title"]
CONTENT = STORY["content"][:6000]
URL     = STORY["url"]

results = []


def record(name: str, passed: bool, detail: str):
    """Record a test result."""
    mark = "✓" if passed else "✗"
    results.append((name, passed, detail))
    print(f"  {mark} {name}: {detail}")


# ═════════════════════════════════════════════════════════════
# TEST 1 — Groq 429 → local fallback
# ═════════════════════════════════════════════════════════════
print()
print("TEST 1: Groq 429 → local fallback (Agent 3 credibility)")
print("-" * 60)

try:
    from agents import agent3

    # make Groq raise a rate-limit-like exception
    fake_groq = MagicMock()
    fake_groq.chat.completions.create.side_effect = Exception(
        "Error code: 429 - Rate limit exceeded"
    )

    buf = io.StringIO()
    with patch.object(agent3, "groq_client", fake_groq):
        with contextlib.redirect_stdout(buf):
            score = agent3.llm_credibility_check(TITLE, CONTENT)

    captured = buf.getvalue()

    # check 1a: didn't crash
    # check 1b: returned a float (not None)
    if isinstance(score, (int, float)):
        record("groq_429_no_crash", True, f"returned score={score}")
    else:
        record("groq_429_no_crash", False, f"unexpected type: {type(score)}")

    # check 1c: fallback fired
    if "falling back to local" in captured or "local fallback" in captured.lower():
        record("groq_429_fallback_fired", True, "local fallback triggered")
    else:
        record("groq_429_fallback_fired", False,
               f"no fallback signal in output: {captured[:200]}")

except Exception as e:
    record("groq_429_no_crash", False, f"EXCEPTION: {e}")
    record("groq_429_fallback_fired", False, "skipped (test crashed)")


# ═════════════════════════════════════════════════════════════
# TEST 2 — Exa down → DDG fallback
# ═════════════════════════════════════════════════════════════
print()
print("TEST 2: Exa down → DDG fallback (Agent 3 cross-verify)")
print("-" * 60)

try:
    # make Exa raise a connection error
    fake_exa = MagicMock()
    fake_exa.search.side_effect = ConnectionError("Exa is down")

    buf = io.StringIO()
    with patch.object(agent3, "_get_exa_client", return_value=fake_exa):
        with contextlib.redirect_stdout(buf):
            verified, contradicted, source = agent3.cross_verify(
                TITLE, URL, CONTENT
            )

    captured = buf.getvalue()

    # check 2a: didn't crash, returned a tuple
    record("exa_down_no_crash", True,
           f"verified={verified}, contradicted={contradicted}, "
           f"source={source!r}")

    # check 2c: Exa failure message appeared
    if "Exa failed" in captured:
        record("exa_down_fallback_fired", True,
               "Exa failure detected, DDG fallback path taken")
    else:
        record("exa_down_fallback_fired", False,
               f"no Exa failure signal: {captured[:200]}")

except Exception as e:
    record("exa_down_no_crash", False, f"EXCEPTION: {e}")
    record("exa_down_fallback_fired", False, "skipped (test crashed)")


# ═════════════════════════════════════════════════════════════
# TEST 3 — DDG timeout → neutral (both sources down)
# ═════════════════════════════════════════════════════════════
print()
print("TEST 3: DDG timeout + Exa down → neutral (Agent 3 cross-verify)")
print("-" * 60)

try:
    # kill both Exa and DDG
    fake_exa = MagicMock()
    fake_exa.search.side_effect = ConnectionError("Exa is down")

    # Patch DDG at the DDGS class level so _fetch_ddg_results' own
    # try/except catches it (matching real timeout behavior)
    from unittest.mock import patch as _patch
    from duckduckgo_search import DDGS as _OrigDDGS

    class _FakeDDGS:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def news(self, *a, **kw):
            raise TimeoutError("DDG timed out")

    buf = io.StringIO()
    with patch.object(agent3, "_get_exa_client", return_value=fake_exa):
        with _patch("agents.agent3.DDGS", _FakeDDGS):
            with contextlib.redirect_stdout(buf):
                verified, contradicted, source = agent3.cross_verify(
                    TITLE, URL, CONTENT
                )

    # check 3a: didn't crash
    # check 3b: returned neutral (False, False, "")
    if not verified and not contradicted:
        record("both_down_neutral", True,
               f"safe neutral: verified={verified}, "
               f"contradicted={contradicted}")
    else:
        record("both_down_neutral", False,
               f"unexpected: verified={verified}, "
               f"contradicted={contradicted}")

    record("both_down_no_crash", True, "pipeline survives total outage")

except Exception as e:
    record("both_down_neutral", False, f"EXCEPTION: {e}")
    record("both_down_no_crash", False, "skipped (test crashed)")


# ═════════════════════════════════════════════════════════════
# SUMMARY
# ═════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("B5 — CHAOS CHECKS SUMMARY")
print("=" * 60)

passed = sum(1 for _, p, _ in results if p)
total  = len(results)

for name, p, detail in results:
    mark = "✓ PASS" if p else "✗ FAIL"
    print(f"  {mark}: {name}")

print()
print(f"  {passed}/{total} checks passed")
print()
healthy = passed == total
print("  OVERALL:", "HEALTHY" if healthy else "UNHEALTHY")
print("=" * 60)
sys.exit(0 if healthy else 1)
