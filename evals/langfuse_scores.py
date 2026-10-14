"""D5 -- send eval results to Langfuse as scores.

Every eval run becomes one trace named "eval-run" in session
"eval-<timestamp>" (or in the pipeline session you pass in), and each
eval result is a score on that trace. Filter Langfuse by that session /
by score name to see an eval run next to the pipeline traces it judged.

Safe by design: if Langfuse is disabled or keys are missing, every call
is a silent no-op. Reporting can never fail an eval.

Usage:
    from evals.langfuse_scores import EvalRunReporter
    with EvalRunReporter(suite="unit") as rep:
        rep.score("eval_x", True, "detail")          # BOOLEAN
        rep.score("agent2/faithfulness", 0.82, "n=5") # NUMERIC

Attach to a pipeline run instead of a standalone eval session:
    EVAL_SESSION_ID=20261015_000939 python evals/run_all.py
"""

from __future__ import annotations

import os
from datetime import datetime


class EvalRunReporter:
    def __init__(self, suite: str = "eval"):
        self.suite = suite
        self.session_id = os.getenv("EVAL_SESSION_ID") or \
            "eval-" + datetime.now().strftime("%Y%m%d_%H%M%S")
        self._client = None
        self._cm = None
        self._pcm = None
        self.trace_id = None

    def __enter__(self):
        try:
            if os.getenv("LANGFUSE_TRACING_ENABLED", "true").lower() == "false":
                return self
            if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
                return self
            from langfuse import get_client, propagate_attributes
            self._client = get_client()
            self._pcm = propagate_attributes(session_id=self.session_id)
            self._pcm.__enter__()
            self._cm = self._client.start_as_current_observation(
                name=f"eval-run:{self.suite}", as_type="span")
            self._cm.__enter__()
            self.trace_id = self._client.get_current_trace_id()
            print(f"  [langfuse] eval scores -> session {self.session_id}")
        except Exception as e:
            print(f"  [langfuse] score reporting disabled: {type(e).__name__}")
            self._client = None
        return self

    def score(self, name: str, value, comment: str = "") -> None:
        """value: bool -> BOOLEAN score, int/float -> NUMERIC."""
        if self._client is None or self.trace_id is None:
            return
        try:
            if isinstance(value, bool):
                value, dtype = (1.0 if value else 0.0), "BOOLEAN"
            else:
                value, dtype = float(value), "NUMERIC"
            self._client.create_score(
                name=name, value=value, data_type=dtype,
                trace_id=self.trace_id, comment=(comment or "")[:500] or None,
            )
        except Exception as e:
            print(f"  [langfuse] score {name!r} skipped: {type(e).__name__}")

    def __exit__(self, *exc):
        try:
            if self._cm is not None:
                self._cm.__exit__(*exc)
            if self._pcm is not None:
                self._pcm.__exit__(*exc)
            if self._client is not None:
                self._client.flush()
        except Exception as e:
            print(f"  [langfuse] flush skipped: {type(e).__name__}")
        return False
