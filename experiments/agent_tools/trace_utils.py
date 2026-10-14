from datetime import datetime

from dotenv import load_dotenv
from langfuse import get_client, propagate_attributes

load_dotenv()  # must run before get_client() so keys in .env are visible
langfuse = get_client()


def log_generation(model, input_tokens, output_tokens):
    try:
        langfuse.update_current_generation(
            model=model,
            usage_details={"input": input_tokens or 0, "output": output_tokens or 0})
    except Exception as e:
        print(f"  [trace] usage logging skipped: {e}")


_session_cm = None  # keep a reference: if it is garbage-collected the session context closes


def add_metadata(**kw):   # facts: tier, counts, retries
    try: langfuse.update_current_span(metadata=kw)
    except Exception as e: print(f"  [trace] metadata skipped: {e}")


_SEV = {"DEFAULT": 0, "WARNING": 1, "ERROR": 2}
_marks = {}   # observation id -> (worst level, [messages])


def mark_issue(message, level="WARNING"):
    try:
        oid = langfuse.get_current_observation_id()
        worst, msgs = _marks.get(oid, ("DEFAULT", []))
        msgs = msgs + [message]
        if _SEV.get(level, 1) > _SEV[worst]:
            worst = level
        _marks[oid] = (worst, msgs)
        langfuse.update_current_span(level=worst, status_message=" | ".join(msgs))
    except Exception as e:
        print(f"  [trace] issue mark skipped: {e}")


def start_session():
    """Call once at the start of a pipeline run (first notebook cell).

    Stamps one session id on every trace created afterwards, so all the
    per-agent traces of a run group together in Langfuse's Sessions view.
    Returns the session id. Never raises.
    """
    global _session_cm
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        if _session_cm is not None:  # cell re-run: close the previous session first
            try:
                _session_cm.__exit__(None, None, None)
            except Exception:
                pass
        _session_cm = propagate_attributes(session_id=run_id)
        _session_cm.__enter__()
    except Exception as e:
        print(f"  [trace] session grouping skipped: {e}")
    return run_id
