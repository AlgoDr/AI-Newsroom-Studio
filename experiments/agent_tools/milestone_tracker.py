"""
milestone_tracker.py

A reusable utility that:
  1. Logs every "hit" of any function you want to track, to a JSONL file
  2. Fires a macOS notification + loud print when a milestone count is reached
  3. Writes a marker file so the milestone is visible even in future sessions

HOW TO USE (generic — works for tracking ANY function call):

  from agents.milestone_tracker import MilestoneTracker

  # Create a tracker for whatever you want to count
  tracker = MilestoneTracker(
      name="oss20b_bigboss",        # used for filenames + notification title
      milestone_at=[5, 10],         # alert at 5 hits AND at 10 hits
  )

  # Inside whatever function you want to track:
  tracker.log_hit(
      context="the topic or story being processed",
      output="what the function returned",
      success=True,
  )

  # Anytime you want a status report:
  tracker.status()

TEST THIS SCRIPT RIGHT NOW (standalone test, nothing to do with agent2):
  python experiments/agents/milestone_tracker.py

  This will simulate 6 fake hits — you'll see the milestone
  notification pop at hit #5, then the status report at the end.
"""

import json
import pathlib
import subprocess
from datetime import datetime


class MilestoneTracker:
    """Counts hits of any function, alerts at milestone thresholds."""

    def __init__(self, name: str, milestone_at: list[int] = None,
                 log_dir: str = "data"):
        """
        name         : short identifier, used in filenames and notifications
                       e.g. "oss20b_bigboss", "tavily_search", "compound_mini"
        milestone_at : list of hit counts that trigger an alert
                       e.g. [5, 10] → alert at 5th and 10th hit
        log_dir      : where to write the log and marker files
        """
        self.name = name
        self.milestone_at = milestone_at or [5, 10]
        self.log_path = pathlib.Path(log_dir) / f"{name}_hits.jsonl"
        self.log_path.parent.mkdir(exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────

    def log_hit(self, context: str = "", output: str = "",
                success: bool = True, error: str = None) -> int:
        """Log one hit. Returns the total hit count after this log."""
        record = {
            "timestamp":      datetime.now().isoformat(timespec="seconds"),
            "name":           self.name,
            "context":        context[:200],
            "output_length":  len(output) if output else 0,
            "output_preview": output[:300] if output else None,
            "success":        success,
            "error":          error,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        total = self._count()
        print(f"  [tracker:{self.name}] hit #{total} logged")

        # check every milestone threshold
        for threshold in self.milestone_at:
            self._check_milestone(total, threshold)

        return total

    def status(self) -> None:
        """Print a full status report of all logged hits."""
        if not self.log_path.exists():
            print(f"  [{self.name}] 0 hits logged yet — function has not fired")
            return

        records = [json.loads(line) for line in open(self.log_path)]
        successes = sum(1 for r in records if r["success"])
        next_milestone = next(
            (m for m in sorted(self.milestone_at) if m > len(records)),
            None
        )

        print(f"\n{'='*65}")
        print(f"MILESTONE TRACKER: {self.name.upper()}")
        print(f"{'='*65}")
        print(f"Total hits:    {len(records)}")
        print(f"Successful:    {successes}")
        print(f"Failed:        {len(records) - successes}")
        if next_milestone:
            print(f"Next milestone: {next_milestone} "
                  f"({next_milestone - len(records)} hits away)")
        else:
            print(f"All milestones cleared ✅")

        print(f"\nHit log:")
        for i, r in enumerate(records, 1):
            status_icon = "✅" if r["success"] else "❌"
            print(f"  [{i}] {r['timestamp']} {status_icon}")
            if r["context"]:
                print(f"       context: {r['context'][:70]}")
            if r["success"] and r["output_preview"]:
                print(f"       output ({r['output_length']}c): "
                      f"{r['output_preview'][:100]}...")
            if r["error"]:
                print(f"       error: {r['error']}")
        print(f"{'='*65}\n")

    def reset(self) -> None:
        """Delete log and all milestone marker files. Use for testing."""
        if self.log_path.exists():
            self.log_path.unlink()
        for threshold in self.milestone_at:
            marker = self._marker_path(threshold)
            if marker.exists():
                marker.unlink()
        print(f"  [tracker:{self.name}] reset — all logs and markers deleted")

    # ─────────────────────────────────────────────────────────────────────
    # INTERNAL
    # ─────────────────────────────────────────────────────────────────────

    def _count(self) -> int:
        """Count lines in the log file = number of hits."""
        if not self.log_path.exists():
            return 0
        with open(self.log_path) as f:
            return sum(1 for _ in f)

    def _marker_path(self, threshold: int) -> pathlib.Path:
        return self.log_path.parent / f"{self.name}_milestone_{threshold}_reached.txt"

    def _check_milestone(self, total: int, threshold: int) -> None:
        """Fire the alert once, exactly when threshold is first crossed."""
        marker = self._marker_path(threshold)
        if total != threshold or marker.exists():
            return  # not there yet, OR already alerted for this threshold

        # ── 1. Loud notebook/terminal print ─────────────────────────────
        print("\n" + "🔔" * 30)
        print(f"🔔  MILESTONE HIT: [{self.name}] reached {threshold} hits!")
        print(f"🔔  Call tracker.status() to review all logged outputs.")
        print(f"🔔  Paste that output to Claude for analysis.")
        print("🔔" * 30 + "\n")

        # ── 2. macOS native notification ─────────────────────────────────
        # Works on Mac (M1/M2/M4). Silent no-op on Linux/Windows.
        # Requires: System Settings → Notifications → Terminal → Allow
        self._macos_notify(
            title=f"[{self.name}] {threshold} hits logged ✅",
            message="Call tracker.status() and share with Claude."
        )

        # ── 3. Marker file — persists across sessions ─────────────────────
        with open(marker, "w") as f:
            f.write(f"Milestone {threshold} reached at {datetime.now().isoformat()}\n")
            f.write(f"Log file: {self.log_path}\n")
            f.write(f"Run tracker.status() to review.\n")
        print(f"  [tracker:{self.name}] marker written → {marker}")

    def _macos_notify(self, title: str, message: str) -> None:
        """Fire a native macOS notification. Silent no-op on other OS."""
        try:
            script = (
                f'display notification "{message}" '
                f'with title "{title}" '
                f'sound name "Glass"'
            )
            subprocess.run(["osascript", "-e", script],
                           check=False, capture_output=True)
        except FileNotFoundError:
            pass  # osascript not available (non-Mac) — silent skip
        except Exception:
            pass  # any other error — never crash the pipeline for a notification


# ─────────────────────────────────────────────────────────────────────────────
# STANDALONE TEST — run this file directly to see it work
# python experiments/agents/milestone_tracker.py
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Testing MilestoneTracker with fake hits...\n")
    print("You should see a macOS notification pop at hit #5.\n")

    # create a test tracker (milestones at 3 and 5 for quick testing)
    tracker = MilestoneTracker(
        name="test_function",
        milestone_at=[3, 5],
        log_dir="data/test"
    )

    # clean slate for the test
    tracker.reset()

    # simulate 6 hits
    fake_hits = [
        ("story: Qwen 3.6 is the sweet spot",       "Qwen 3.6 is an open-weight model...", True,  None),
        ("story: Rocketlab acquires Iridium",         "Rocket Lab and Iridium have entered...", True,  None),
        ("story: Wallace telescope hiking",           "",                                   False, "RateLimitError: 429"),
        ("story: CUDA kernel internals",              "CUDA is a parallel computing platform...", True,  None),
        ("story: PDP-1 Lisp 1960",                   "The PDP-1, introduced by DEC in 1959...", True,  None),
        ("story: Memory safe context switching",      "Context switching stores CPU state...", True,  None),
    ]

    for context, output, success, error in fake_hits:
        tracker.log_hit(
            context=context,
            output=output,
            success=success,
            error=error
        )
        print()  # spacing between hits

    # show final status report
    tracker.status()

    # clean up test files after
    print("Cleaning up test files...")
    tracker.reset()
    import shutil
    shutil.rmtree("data/test", ignore_errors=True)
    print("Done. If you saw a macOS notification at hit #3 and #5, it works ✅")