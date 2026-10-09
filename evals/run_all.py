"""Run the AI Newsroom Studio eval suite.

Usage (from the project's experiments/ directory):
    ../multi-agent-env/bin/python evals/run_all.py             # unit evals
    ../multi-agent-env/bin/python evals/run_all.py --content   # + LLM-judged
    ../multi-agent-env/bin/python evals/run_all.py --json      # machine-readable

Exit code 0 = all evals PASS. Non-zero = at least one FAIL.
SKIPPED entries (missing keys/API keys) are warnings, not failures.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Make the project importable no matter where this script is invoked from,
# and force cwd to experiments/ so agents' dotenv.load_dotenv('.env') and
# relative data/ paths resolve exactly the way the real pipeline expects.
EXPERIMENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if EXPERIMENTS_DIR not in sys.path:
    sys.path.insert(0, EXPERIMENTS_DIR)
os.chdir(EXPERIMENTS_DIR)

import dotenv  # noqa: E402
dotenv.load_dotenv(".env")  # populate GROQ_KEY etc. before agents import

from evals import config, content_evals, dataset, unit_evals  # noqa: E402


def _run_group(name: str, funcs: list) -> list[dict]:
    results = []
    for fn in funcs:
        try:
            passed, detail = fn()
        except Exception as e:  # an eval that crashes IS a failure
            passed, detail = False, f"CRASHED: {type(e).__name__}: {e}"
        results.append({
            "name": fn.__name__,
            "passed": bool(passed),
            "detail": detail,
            "skipped": isinstance(detail, str) and detail.startswith("SKIPPED"),
        })
    return results


def _print_table(groups: list[tuple[str, list[dict]]]) -> None:
    width = max(len(r["name"]) for _, rs in groups for r in rs) + 2
    print()
    print("=" * 78)
    print("AI NEWSROOM STUDIO — EVAL SUITE")
    print("=" * 78)
    for group_name, results in groups:
        print(f"\n── {group_name} ──")
        for r in results:
            mark = "SKIP" if r["skipped"] else ("PASS" if r["passed"] else "FAIL")
            color = ""  # keep rows easy to diff; no ANSI needed for now
            print(f"  [{mark:4s}] {r['name']:<{width}} {r['detail']}")
        n_pass = sum(r["passed"] for r in results)
        n_fail = sum(not r["passed"] and not r["skipped"] for r in results)
        n_skip = sum(r["skipped"] for r in results)
        print(f"  ── {group_name}: {n_pass} pass, {n_fail} fail, {n_skip} skipped")


# ══════════════════════════════════════════════════════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="NewsStudio eval suite")
    ap.add_argument("--content", action="store_true",
                    help="also run LLM-judged content evals (needs GROQ_KEY)")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON results")
    args = ap.parse_args()

    groups = [("Unit evals (deterministic, offline)", unit_evals.UNIT_EVALS)]
    if args.content:
        groups.append(("Content evals (LLM-judged)", content_evals.CONTENT_EVALS))

    results = {f"({name})": _run_group(name, funcs)
               for name, funcs in groups}
    if not args.json:
        _print_table(list(results.items()))

    n_fail = sum(not r["passed"] and not r["skipped"]
                 for rs in results.values() for r in rs)
    n_skip = sum(r["skipped"] for rs in results.values() for r in rs)

    if args.json:
        print(json.dumps({
            "suite": "newsstudio",
            "groups": results,
            "failures": n_fail,
            "skipped": n_skip,
        }, indent=2))
        return 1 if n_fail else 0

    print("\n" + "=" * 78)
    if n_fail:
        print(f"RESULT: {n_fail} FAILING EVALS — do NOT deploy to cloud.")
        print("Fix the failures (or intentionally lower a threshold in config.py)")
        print("before the deployment step.")
    else:
        print(f"RESULT: ALL EVALS PASSED{f' ({n_skip} skipped)' if n_skip else ''} — "
              "safe to proceed toward deployment.")
    print("=" * 78)
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())