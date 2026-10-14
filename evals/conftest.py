"""D5 -- pytest hook: every quality eval (DeepEval tests) reports its
pass/fail to Langfuse as a BOOLEAN score on one "eval-run" trace.

No-op when Langfuse keys are missing or LANGFUSE_TRACING_ENABLED=false.
Never changes a test result.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_rep = None


def pytest_sessionstart(session):
    global _rep
    try:
        from evals.langfuse_scores import EvalRunReporter
        _rep = EvalRunReporter(suite="quality")
        _rep.__enter__()
    except Exception:
        _rep = None


def pytest_runtest_logreport(report):
    if _rep is None or report.when != "call":
        return
    try:
        _rep.score(f"quality/{report.nodeid.split('/')[-1]}", report.passed,
                   f"{report.outcome} in {report.duration:.1f}s")
    except Exception:
        pass


def pytest_sessionfinish(session, exitstatus):
    if _rep is not None:
        try:
            _rep.__exit__(None, None, None)
        except Exception:
            pass
