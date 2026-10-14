#!/usr/bin/env python3
"""CI entry point — runs all evals and exits non-zero on failure.

Usage:
    cd AI-Newsroom-Studio

    # Unit evals only (deterministic, no API keys needed)
    python evals/run_all.py

    # Unit + content evals (needs GROQ_KEY in experiments/.env)
    python evals/run_all.py --content

Exit code 0 = all pass (skips don't count as failures). Non-zero = at
least one real failure.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path so `from evals import ...` works
# even when invoked as `python evals/run_all.py` from the project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Also add experiments/ so agent imports work (agents live there)
_EXPERIMENTS = _PROJECT_ROOT / "experiments"
if str(_EXPERIMENTS) not in sys.path:
    sys.path.insert(0, str(_EXPERIMENTS))

# Load .env for GROQ_KEY if dotenv is available
_ENV_FILE = _EXPERIMENTS / ".env"
if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE)
    except ImportError:
        pass

# CI has no GROQ_KEY — set a dummy so agent modules with module-level
# Groq() clients can import. Unit evals test pure-Python functions
# (date formatting, content quality gates) that never call the API.
if not os.getenv("GROQ_KEY"):
    os.environ["GROQ_KEY"] = "gsk_CI_DUMMY_KEY_evals_only"


_REPORTER = None  # D5: set by main(); None = Langfuse reporting off


def _run_suite(label: str, evals: list) -> tuple[int, int, int, list[str]]:
    """Run a list of (passed, detail) eval functions.

    Returns (passed_count, skipped_count, total_count, failure_details).
    SKIPs are evals that return (False, "SKIPPED: ...") — missing deps,
    not real failures.
    """
    passed = 0
    skipped = 0
    failures: list[str] = []
    total = len(evals)

    for fn in evals:
        name = fn.__name__
        t0 = time.time()
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"CRASHED: {type(e).__name__}: {e}"
        elapsed = time.time() - t0

        is_skip = not ok and "SKIPPED" in str(detail)
        if is_skip:
            status = "SKIP"
            skipped += 1
        elif ok:
            status = "PASS"
            passed += 1
        else:
            status = "FAIL"
            failures.append(f"{name}: {detail}")

        print(f"  [{status}] {name} ({elapsed:.1f}s)")
        if _REPORTER is not None and status != "SKIP":
            _REPORTER.score(f"{label}/{name}", ok, str(detail))
        if detail:
            # Indent multi-line details
            for line in detail.split("\n"):
                print(f"         {line}")

    return passed, skipped, total, failures


def main() -> int:
    global _REPORTER
    ap = argparse.ArgumentParser(
        description="AI Newsroom Studio — eval runner"
    )
    ap.add_argument(
        "--content", action="store_true",
        help="Also run content evals (needs GROQ_KEY)"
    )
    ap.add_argument(
        "--unit-only", action="store_true",
        help="Run only unit evals (default when --content is not set)"
    )
    args = ap.parse_args()

    from evals.langfuse_scores import EvalRunReporter
    _rep = EvalRunReporter(suite="content+unit" if args.content else "unit")
    _rep.__enter__()
    _REPORTER = _rep

    all_failures: list[str] = []
    total_passed = 0
    total_skipped = 0
    total_count = 0

    # ── Unit evals (always run) ──────────────────────────────────
    print("=" * 60)
    print("UNIT EVALS (deterministic, no API)")
    print("=" * 60)

    from evals.unit_evals import UNIT_EVALS
    p, s, t, fails = _run_suite("unit", UNIT_EVALS)
    total_passed += p
    total_skipped += s
    total_count += t
    all_failures.extend(fails)
    print(f"\n  Unit: {p}/{t} passed, {s} skipped\n")

    # ── Content evals (optional) ─────────────────────────────────
    if args.content:
        print("=" * 60)
        print("CONTENT EVALS (LLM-judged, needs GROQ_KEY)")
        print("=" * 60)

        if not os.getenv("GROQ_KEY"):
            print("  WARNING: GROQ_KEY not set — content evals will SKIP\n")

        from evals.content_evals import CONTENT_EVALS
        p, s, t, fails = _run_suite("content", CONTENT_EVALS)
        total_passed += p
        total_skipped += s
        total_count += t
        all_failures.extend(fails)
        print(f"\n  Content: {p}/{t} passed, {s} skipped\n")

    # ── Summary ──────────────────────────────────────────────────
    real_ran = total_count - total_skipped
    if real_ran:
        _rep.score("eval/pass_rate", total_passed / real_ran,
                   f"{total_passed}/{real_ran} passed")
    _rep.__exit__(None, None, None)
    print("=" * 60)
    print(f"TOTAL: {total_passed}/{real_ran} passed"
          + (f" ({total_skipped} skipped)" if total_skipped else ""))
    if all_failures:
        print(f"\nFAILURES ({len(all_failures)}):")
        for f in all_failures:
            print(f"  ✗ {f}")
        print("=" * 60)
        return 1
    else:
        print("ALL PASS" + (" (skips excluded)" if total_skipped else ""))
        print("=" * 60)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
