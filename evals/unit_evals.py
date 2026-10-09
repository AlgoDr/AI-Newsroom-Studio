"""Deterministic unit evals -- no LLM calls, no network.

These validate the pipeline's own agent functions against golden
checkpoint data and well-known invariants (velocity formula, content
quality gates, script QC constraints, shot-list math). If any of these
FAIL, the pipeline is misbehaving regardless of model quality.

Each eval is a zero-argument function returning (passed: bool, detail: str).
"""

from __future__ import annotations

import datetime as _dt
from datetime import datetime, timedelta, timezone

from . import config
from . import dataset


# ══════════════════════════════════════════════════════════════════
# 1. Golden checkpoint integrity
# ══════════════════════════════════════════════════════════════════

def eval_checkpoint_integrity() -> tuple[bool, str]:
    state = dataset.load_golden_checkpoint()
    required = {"stories", "script", "shot_list", "seo", "video_path"}
    missing = required - set(state.keys())
    if missing:
        return False, f"checkpoint missing keys: {sorted(missing)}"
    return True, dataset.checkpoint_summary(state)


def eval_stories_cache() -> tuple[bool, str]:
    cache = dataset.load_stories_cache()
    if len(cache) < 20:
        return False, f"only {len(cache)} cached stories (want >= 20)"
    complete = [s for s in cache.values() if s.get("content") and s.get("background")]
    return True, f"{len(cache)} stories, {len(complete)} with content+background"


def eval_selected_stories_have_editorial() -> tuple[bool, str]:
    state = dataset.load_golden_checkpoint()
    selected = dataset.selected_stories(state)
    if not selected:
        return False, "golden checkpoint has no stories with selection_rank"
    missing = [s.get("title", "?")[:40]
               for s in selected if not s.get("selection_reason")]
    if missing:
        return False, f"selected stories missing selection_reason: {missing}"
    return True, f"{len(selected)} selected stories with editorial justification"


# ══════════════════════════════════════════════════════════════════
# 2. Agent 1 -- Trend velocity formula (the project's own ranking math)
# ══════════════════════════════════════════════════════════════════

def _fake_hn_response(stories_payload):
    class _Resp:
        def __init__(self, payload):
            self._payload = payload
        def json(self):
            return self._payload
    return _Resp(stories_payload)
def eval_agent1_velocity_ranking() -> tuple[bool, str]:
    import agents.agent1 as a1

    now = datetime.now(timezone.utc).timestamp()
    # story A: high upvotes + few comments, ~3h old
    # story B: low upvotes + more comments, ~1h old
    items = {
        "1": {"id": 1, "type": "story", "title": "Story A",
              "score": 100, "descendants": 5, "time": int(now - 3 * 3600),
              "url": "https://a.example/x"},
        "2": {"id": 2, "type": "story", "title": "Story B",
              "score": 10, "descendants": 2, "time": int(now - 1 * 3600),
              "url": "https://b.example/x"},
        "3": {"id": 3, "type": "story", "title": "Story C",
              "score": 50, "descendants": 0, "time": int(now - 24 * 3600),
              "url": "https://c.example/x"},
    }
    real_get = a1.requests.get

    def fake_get(url, **kw):
        if "topstories" in url:
            return _fake_hn_response(["1", "2", "3"])
        sid = url.rstrip("/").split("/")[-1].replace(".json", "")
        return _fake_hn_response(items.get(sid, {}))
    a1.requests.get = fake_get
    try:
        stories = a1.fetch_trends(top_n=3)
    finally:
        a1.requests.get = real_get

    titles = [s["title"] for s in stories]
    if titles != ["Story A", "Story B", "Story C"]:
        return False, f"velocity sort wrong: {titles}"
    # verify the exact formula: velocity = (upvotes + comments*2) / age_hrs
    a = stories[0]
    expected = round((100 + 5 * 2) / 3.0, 1)
    if abs(a["velocity"] - expected) > 0.3:
        return False, f"velocity formula drift: {a['velocity']} vs expected ~{expected}"
    return True, f"ranked {titles} | A.velocity={a['velocity']} (~{expected})"


# ══════════════════════════════════════════════════════════════════
# 3. Agent 2 -- Content quality gate + citation cleaning
# ══════════════════════════════════════════════════════════════════

def eval_agent2_looks_like_real_content() -> tuple[bool, str]:
    from agents.agent2 import looks_like_real_content
    good = ("\n".join(
        "This article explores the technical details and industry impact "
        "of the announcement in depth, covering multiple perspectives and "
        "historical context for context readers across the ecosystem.",
        ) * 2)
    cases = [
        (None,                                        False, "None input"),
        ("short",                                     False, "too short"),
        ("  \n\t  \n  " * 60,                         False, "whitespace heavy"),
        ("Rate limit exceeded. Please try again " * 8, False, "junk marker"),
        (good,                                        True,  "real prose"),
    ]
    failed = [label for text, want, label in cases
              if looks_like_real_content(text) is not want]
    if failed:
        return False, f"failed cases: {failed}"
    return True, f"{len(cases)} cases passed"


def eval_agent2_strip_citation_artifacts() -> tuple[bool, str]:
    from agents.agent2 import _strip_citation_artifacts
    dirty = "OpenAI announced a new model【2†L10-L12】 with support for tool calls【3†L5-L7】."
    clean = _strip_citation_artifacts(dirty)
    if "【" in clean or "†" in clean:
        return False, f"citation markers not stripped: {clean!r}"
    return True, f"stripped to: {clean!r}"


# ══════════════════════════════════════════════════════════════════
# 4. Agent 6 -- Date humanization (pure regex, no LLM) + QC constraints
# ══════════════════════════════════════════════════════════════════

def eval_agent6_humanize_dates() -> tuple[bool, str]:
    from agents.agent6 import _humanize_dates
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3))
    date_str = three_days_ago.strftime("%B %d, %Y").replace(" 0", " ")
    out = _humanize_dates(f"Announced on {date_str}, the update ships today.")
    if out.count("days ago") == 0:
        return False, f"expected relative phrasing, got: {out!r}"
    if three_days_ago.strftime("%B") in out:
        return False, f"absolute month name still present: {out!r}"
    return True, f"'{date_str}' -> '{out[:60]}...'"


def eval_agent6_qc_script_compliance() -> tuple[bool, str]:
    state = dataset.load_golden_checkpoint()
    script = dataset.golden_script(state)
    wc = script.get("word_count", 0)
    if not (config.TARGET_MIN_WORDS <= wc <= config.TARGET_MAX_WORDS):
        return False, (f"word_count={wc} outside "
                       f"[{config.TARGET_MIN_WORDS}, {config.TARGET_MAX_WORDS}]")
    sections = script.get("sections", {})
    if not isinstance(sections, dict):
        return False, f"sections not a dict: {type(sections).__name__}"
    have = list(sections.keys())
    if have != config.SECTION_ORDER:
        return False, f"section order mismatch:\n  want {config.SECTION_ORDER}\n  got  {have}"
    if not script.get("approved"):
        return False, "script not flagged 'approved' by QC"
    return True, f"word_count={wc}, {len(sections)} sections, approved"


# ══════════════════════════════════════════════════════════════════
# 5. Agent 7 -- Shot list math must be internally consistent
# ══════════════════════════════════════════════════════════════════

def eval_agent7_shot_list_integrity() -> tuple[bool, str]:
    from agents.agent7 import build_shot_list
    state = dataset.load_golden_checkpoint()
    try:
        shots = build_shot_list(state, ollama_generate_fn=None)
    except Exception as e:
        return False, f"build_shot_list raised: {type(e).__name__}: {e}"
    if len(shots) != len(config.SECTION_ORDER):
        return False, f"expected {len(config.SECTION_ORDER)} shots, got {len(shots)}"
    got = [s["section"] for s in shots]
    if got != config.SECTION_ORDER:
        return False, f"shot order mismatch: {got}"
    # start/end shares must be monotonically non-decreasing and end at 1.0
    end_share = [s["end_share"] for s in shots]
    if end_share != sorted(end_share):
        return False, f"end_share not monotonic: {end_share}"
    if abs(end_share[-1] - 1.0) > 0.01:
        return False, f"last end_share={end_share[-1]} != 1.0"
    return True, f"{len(shots)} shots, sums to {end_share[-1]:.2f}"


# ══════════════════════════════════════════════════════════════════
# 6. Agent 9 -- SEO tags fallback must NEVER be empty
# ══════════════════════════════════════════════════════════════════

def eval_agent9_tags_fallback() -> tuple[bool, str]:
    from agents.agent9 import _extract_tags_for_story
    story = dataset.selected_stories(dataset.load_golden_checkpoint())[0]
    tags, used_fallback = _extract_tags_for_story(story, ollama_generate_fn=None)
    if not tags:
        return False, "fallback returned empty tag list"
    if len(tags) > 5:
        return False, f"fallback returned {len(tags)} tags (cap is 5)"
    if not used_fallback:
        return False, "expected used_fallback=True with no model wired"
    return True, f"fallback tags ({used_fallback}): {tags[:3]}..."


def eval_seo_completeness() -> tuple[bool, str]:
    state = dataset.load_golden_checkpoint()
    seo = state.get("seo", {})
    missing = [k for k in ("title", "description", "tags", "category_id")
               if not seo.get(k)]
    if missing:
        return False, f"seo missing: {missing}"
    return True, f"seo title({len(seo['title'])}): {seo['title'][:40]}..."


# ══════════════════════════════════════════════════════════════════
# Registry (order matters -- integrity first, then components)
# ══════════════════════════════════════════════════════════════════

UNIT_EVALS = [
    eval_checkpoint_integrity,
    eval_stories_cache,
    eval_selected_stories_have_editorial,
    eval_agent1_velocity_ranking,
    eval_agent2_looks_like_real_content,
    eval_agent2_strip_citation_artifacts,
    eval_agent6_humanize_dates,
    eval_agent6_qc_script_compliance,
    eval_agent7_shot_list_integrity,
    eval_agent9_tags_fallback,
    eval_seo_completeness,
]