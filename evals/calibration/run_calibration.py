"""Judge Calibration — Phase A Task A3

Runs the Agent 6 JUDGE on the 10 calibration scripts and fills in
judge_verdict + judge_flagged_sections. After Deep manually scores
the same scripts (human_verdict + human_flagged_sections), this
script computes agreement metrics.

Usage:
  # Step 1: Run the judge on all calibration scripts
  cd AI-Newsroom-Studio
  ../multi-agent-env/bin/python evals/calibration/run_calibration.py --judge

  # Step 2: Deep manually fills human_verdict / human_flagged_sections
  #         in judge_calibration_v1.json

  # Step 3: Compute agreement
  ../multi-agent-env/bin/python evals/calibration/run_calibration.py --agreement
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "experiments"))

from dotenv import load_dotenv
load_dotenv(ROOT / "experiments" / ".env")

CALIBRATION_FILE = Path(__file__).parent / "judge_calibration_v1.json"


def _load_calibration():
    with open(CALIBRATION_FILE) as f:
        return json.load(f)


def _save_calibration(data):
    with open(CALIBRATION_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Step 1: Run the judge ────────────────────────────────────────

def run_judge():
    """Import Agent 6's judge and score each calibration script."""
    from agents.agent6 import judge_script

    data = _load_calibration()
    print(f"Running judge on {len(data)} calibration scripts...\n")

    for entry in data:
        sid = entry["script_id"]
        sections = entry["sections"]

        print(f"Script {sid}:")
        try:
            result = judge_script(sections)
            verdict = result.get("verdict", "unknown")
            flagged = result.get("flagged_sections", [])
            entry["judge_verdict"] = verdict
            entry["judge_flagged_sections"] = flagged
            print(f"  verdict={verdict}, flagged={flagged}")
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            entry["judge_verdict"] = "error"
            entry["judge_flagged_sections"] = []

        time.sleep(1)  # rate limit

    _save_calibration(data)
    print(f"\nJudge scores saved to {CALIBRATION_FILE}")
    print("Next: manually fill in human_verdict and human_flagged_sections,")
    print("then run with --agreement")


# ── Step 2: Compute agreement ────────────────────────────────────

def compute_agreement():
    """Compute human-judge agreement metrics."""
    data = _load_calibration()

    # Check that human scores are filled in
    missing = [e["script_id"] for e in data
               if e.get("human_verdict") is None]
    if missing:
        print(f"ERROR: human_verdict not filled for scripts: {missing}")
        print("Please fill in human_verdict ('pass' or 'fail') and")
        print("human_flagged_sections (list of section names) in:")
        print(f"  {CALIBRATION_FILE}")
        return 1

    # Verdict agreement
    agree_verdict = 0
    disagree = []
    for e in data:
        hv = e["human_verdict"].lower()
        jv = (e.get("judge_verdict") or "").lower()
        if hv == jv:
            agree_verdict += 1
            e["agreement"] = "agree"
        else:
            disagree.append(e["script_id"])
            e["agreement"] = "disagree"

    # Flagged section agreement (Jaccard similarity per script)
    jaccard_scores = []
    for e in data:
        human_set = set(e.get("human_flagged_sections") or [])
        judge_set = set(e.get("judge_flagged_sections") or [])
        if not human_set and not judge_set:
            jaccard = 1.0  # both agree nothing is flagged
        elif not human_set or not judge_set:
            jaccard = 0.0  # one sees issues, other doesn't
        else:
            jaccard = len(human_set & judge_set) / len(human_set | judge_set)
        jaccard_scores.append(jaccard)

    _save_calibration(data)

    # Report
    print("=" * 60)
    print("JUDGE CALIBRATION RESULTS")
    print("=" * 60)
    print(f"\nVerdict agreement: {agree_verdict}/{len(data)} "
          f"({agree_verdict/len(data)*100:.0f}%)")
    if disagree:
        print(f"  Disagreements on scripts: {disagree}")

    mean_jaccard = sum(jaccard_scores) / len(jaccard_scores)
    print(f"\nFlagged-section Jaccard similarity: {mean_jaccard:.3f}")
    print(f"  (1.0 = perfect match, 0.0 = no overlap)")

    print(f"\nPer-script breakdown:")
    for e, j in zip(data, jaccard_scores):
        sid = e["script_id"]
        hv = e["human_verdict"]
        jv = e.get("judge_verdict", "?")
        ag = e["agreement"]
        hf = e.get("human_flagged_sections", [])
        jf = e.get("judge_flagged_sections", [])
        print(f"  #{sid:2d}: human={hv:4s} judge={jv:4s} [{ag:8s}] "
              f"jaccard={j:.2f} h_flag={hf} j_flag={jf}")

    print(f"\n{'=' * 60}")
    if agree_verdict >= 8:
        print("CALIBRATION: GOOD (≥80% verdict agreement)")
    elif agree_verdict >= 6:
        print("CALIBRATION: ACCEPTABLE (≥60% verdict agreement)")
    else:
        print("CALIBRATION: POOR (<60% — review judge prompts)")
    print("=" * 60)

    return 0


def main():
    ap = argparse.ArgumentParser(description="Judge calibration tool")
    ap.add_argument("--judge", action="store_true",
                    help="Run the LLM judge on calibration scripts")
    ap.add_argument("--agreement", action="store_true",
                    help="Compute human-judge agreement metrics")
    args = ap.parse_args()

    if args.judge:
        run_judge()
    elif args.agreement:
        return compute_agreement()
    else:
        print("Usage: run_calibration.py --judge | --agreement")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
