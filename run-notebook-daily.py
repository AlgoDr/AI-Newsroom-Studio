"""
run_notebook_daily.py -- the ONE small file launchd calls at 8am IST.

Does NOT reimplement any agent logic -- unlike the earlier
pipeline_graph.py approach, this runs your ACTUAL workflow.ipynb
directly via papermill (a standard, purpose-built tool for executing
notebooks unattended -- not something hand-rolled). Your notebook's
own already-proven cells are the real pipeline; this file only adds
two things around it:

  1. A hard 8:00-8:05 AM IST deadline, checked BEFORE papermill is
     even invoked -- if outside the window, the notebook never runs
     at all today.
  2. A log renamed after the run to include the real video title,
     extracted from Agent 9's own captured print output.

Requires: pip install papermill
"""

import os
import re
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

DEADLINE_HOUR = 8
DEADLINE_MINUTE = 0
GRACE_MINUTES = 5  # small tolerance for launchd's own normal firing
                    # jitter -- NOT meant to absorb a late wake


def _within_deadline_window(now_ist: datetime) -> bool:
    """True only if `now_ist` falls within [8:00:00, 8:05:00] IST.
    Explicit IST via zoneinfo (stdlib, no new dependency) rather than
    trusting the system's configured local timezone actually IS IST --
    correct regardless of how the Mac itself is set."""
    deadline = now_ist.replace(hour=DEADLINE_HOUR, minute=DEADLINE_MINUTE,
                                second=0, microsecond=0)
    elapsed_minutes = (now_ist - deadline).total_seconds() / 60
    return 0 <= elapsed_minutes <= GRACE_MINUTES


def _extract_title(captured_output: str) -> str | None:
    """Matches Agent 9's own real, confirmed print line from your
    actual notebook cell:
        print(f"Title ({len(seo['title'])} chars): {seo['title']}")
    which prints as e.g. 'Title (99 chars): Almost 200 Silicon...'
    Returns None if that line never appeared -- e.g. the run ended
    early via the 0-stories path, or failed before reaching Agent 9."""
    match = re.search(r'^Title \(\d+ chars\): (.+)$', captured_output, re.MULTILINE)
    return match.group(1).strip() if match else None


def _slugify(text: str, max_length: int = 60) -> str:
    """Same style already used elsewhere in this project for output/
    run-folder naming. If output_organization.py already exposes a
    slugify function, prefer importing that one instead of this
    standalone copy."""
    slug = text.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug[:max_length].rstrip('-') or "untitled"


def main():
    project_root = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(project_root, "logs")
    executed_notebooks_dir = os.path.join(log_dir, "executed_notebooks")
    os.makedirs(executed_notebooks_dir, exist_ok=True)

    # --force bypasses the deadline check -- for manual testing ONLY.
    # The real launchd-triggered scheduled run (via the plist, no
    # extra arguments) never passes this, so the actual automated
    # 8am run always enforces the hard deadline exactly as designed.
    # Use this to test the REAL pipeline execution right now, without
    # waiting until tomorrow's 8am IST.
    force_run = "--force" in sys.argv

    now_ist = datetime.now(IST)
    timestamp = now_ist.strftime("%Y%m%d_%H%M%S")

    # --- HARD DEADLINE CHECK -- before papermill is even invoked ---
    if not force_run and not _within_deadline_window(now_ist):
        skip_log_path = os.path.join(log_dir, f"{timestamp}_SKIPPED-outside-deadline.log")
        with open(skip_log_path, "w", encoding="utf-8") as f:
            f.write("Run SKIPPED -- outside the hard 8:00 AM IST deadline window.\n")
            f.write(f"Script actually started at: {now_ist.isoformat()} (IST)\n")
            f.write(f"Required window: {DEADLINE_HOUR:02d}:{DEADLINE_MINUTE:02d}:00 "
                    f"to {DEADLINE_HOUR:02d}:{DEADLINE_MINUTE + GRACE_MINUTES:02d}:00 IST\n")
            f.write("Most likely cause: the Mac's lid was closed (or the machine was\n")
            f.write("off) at 8am and only became active later. Per the hard-deadline\n")
            f.write("design, today's run does NOT execute late -- it tries again\n")
            f.write("tomorrow at 8am IST.\n")
            f.write("\n(To test the real pipeline right now regardless of time, run:\n")
            f.write(" python3 run-notebook-daily.py --force)\n")
        print(f"[run_notebook_daily] SKIPPED -- outside deadline window. See {skip_log_path}")
        return

    if force_run:
        print(f"[run_notebook_daily] --force passed -- bypassing deadline check for manual testing")

    # --- within the window -- run the REAL notebook via papermill ---
    # NOTE: this script lives in the project root, but workflow.ipynb
    # lives in experiments/ -- confirmed via `ls`, not assumed. Every
    # agent's relative paths (data/checkpoints/..., data/audio/...)
    # resolve correctly ONLY when the notebook actually executes with
    # experiments/ as its working directory (confirmed: git status
    # showed the real cache file living at experiments/data/
    # stories_cache.json, matching how every manual test this whole
    # project has run). --cwd forces papermill to match that, rather
    # than defaulting to wherever this script happens to sit.
    experiments_dir = os.path.join(project_root, "experiments")
    input_notebook = os.path.join(experiments_dir, "workflow.ipynb")
    output_notebook = os.path.join(executed_notebooks_dir, f"{timestamp}.ipynb")

    print(f"[run_notebook_daily] within deadline window ({now_ist.isoformat()} IST) -- "
          f"running {input_notebook}")

    # Real bug found via 5 consecutive real failed automated runs (see
    # KNOWN_ISSUES ISSUE-29): launchd does NOT inherit the interactive
    # shell's PATH the way a manually-run terminal command does, so a
    # bare "papermill" string here silently resolved to nothing under
    # launchd, despite working perfectly when tested manually with
    # --force from an activated shell. Fix: compute papermill's real
    # absolute path from the SAME venv as the currently-running
    # interpreter (sys.executable), which pip installed it into --
    # never relies on PATH resolution at all.
    papermill_bin = os.path.join(os.path.dirname(sys.executable), "papermill")
    if not os.path.isfile(papermill_bin):
        print(f"[run_notebook_daily] FATAL: papermill not found at "
              f"{papermill_bin} -- is it installed in this venv? "
              f"Run: pip install papermill")
        return

    result = subprocess.run(
        [papermill_bin, input_notebook, output_notebook,
         "--cwd", experiments_dir,
         "--log-output"],  # streams each cell's stdout into papermill's own stdout as it runs
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    captured_output = result.stdout + "\n" + result.stderr

    log_path_temp = os.path.join(log_dir, f"{timestamp}.log")
    with open(log_path_temp, "w", encoding="utf-8") as f:
        f.write(f"PIPELINE RUN STARTED: {now_ist.isoformat()} IST\n")
        f.write(f"papermill exit code: {result.returncode}\n")
        f.write(f"executed notebook saved to: {output_notebook}\n")
        f.write("=" * 70 + "\n")
        f.write(captured_output)
        f.write("\n" + "=" * 70 + "\n")
        f.write(f"PIPELINE RUN {'COMPLETED' if result.returncode == 0 else 'FAILED'}: "
                f"{datetime.now(IST).isoformat()} IST\n")

    # rename with the real video title now that the run has finished
    title = _extract_title(captured_output)
    if title:
        final_log_path = os.path.join(log_dir, f"{timestamp}_{_slugify(title)}.log")
    else:
        final_log_path = os.path.join(log_dir, f"{timestamp}_no-title.log")
    os.rename(log_path_temp, final_log_path)

    print(f"[run_notebook_daily] papermill exit code: {result.returncode}")
    print(f"[run_notebook_daily] full log saved to: {final_log_path}")
    print(f"[run_notebook_daily] executed notebook saved to: {output_notebook}")

    if result.returncode != 0:
        print("[run_notebook_daily] run FAILED -- see the log above for the real error")


if __name__ == "__main__":
    main()