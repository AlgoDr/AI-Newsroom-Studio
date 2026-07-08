"""
agent4.py — Editorial Agent

Role: "Which 3 stories should we actually cover today?"

Responsibilities:
  1. filter_stories()       — remove Agent 3 discards (score < 0.0)
  2. score_editorially()    — compute editorial_score per story
  3. deduplicate_topics()   — phi3.5 clusters titles → keep best per topic
  4. select_top_stories()   — pick top 3 (or fewer) by editorial_score
  5. editorial_node()       — LangGraph node (orchestrates 1-4)
  6. route_after_editorial()— LangGraph conditional edge (→ Agent 5 or end)

What Agent 4 does NOT do:
  - Does not re-fetch content (Agent 2 did that)
  - Does not re-score credibility (Agent 3 did that)
  - Does not write scripts (Agent 5 will do that)
  - Does not call any cloud API (phi3.5 is local)

Keys added to story dict:
  editorial_score   float  — composite editorial rank (0.0 to 1.0)
  selected          bool   — True if chosen for scripting
  selection_rank    int    — 1, 2, 3 (or None if not selected)
  selection_reason  str    — why this story was picked (audit trail)
  _vel_norm         float  — normalised velocity (audit trail)
  _bg_norm          float  — normalised background score (audit trail)
  _topic_cluster    int    — which topic cluster phi3.5 assigned
"""

import os
import json
import subprocess
import dotenv
import ollama

dotenv.load_dotenv(".env")

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

MAX_SELECTED      = 3      # max stories to pass to Agent 5
BG_FULL_CHARS     = 800    # background chars that earns full bg_norm score
MIN_STORIES_TO_RUN = 1     # minimum selected stories to proceed to Agent 5


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 1 — filter_stories
# ─────────────────────────────────────────────────────────────────────────────

def filter_stories(stories: dict) -> dict:
    """Remove stories Agent 3 marked as discarded.

    A story is discarded when credibility_score < 0.0:
      - SPAM detected by gpt-oss-120b (llm = -0.7)
      - Credible source contradiction overrides REAL classification

    Returns a NEW dict — does not modify original stories.
    Discarded stories stay in pipeline state for audit trail.
    """
    eligible = {
        sid: story
        for sid, story in stories.items()
        if not story.get("discarded", False)
    }

    discarded_count = len(stories) - len(eligible)
    print(f"  [filter] {len(stories)} stories in → "
          f"{len(eligible)} eligible "
          f"({discarded_count} discarded by Agent 3)")

    return eligible


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 2 — score_editorially
# ─────────────────────────────────────────────────────────────────────────────

def score_editorially(stories: dict) -> dict:
    """Compute editorial_score for each eligible story.

    Three signals — weighted ADDITION (not multiplication):
      credibility_score  50%  — trust signal from Agent 3
      velocity_norm      30%  — buzz right now from Agent 1
      bg_norm            20%  — scriptability proxy from Agent 2

    ADDITION not multiplication:
      multiplication: one zero kills the whole score (too harsh)
      addition: each signal penalises independently, none vetoes
      e.g. a viral credible story with no background still ranks
           well enough for Agent 5 to script from content alone

    velocity normalised RELATIVE to this batch:
      highest velocity story = 1.0
      reflects today's news landscape, not an absolute scale

    bg_norm continuous (not boolean):
      0 chars   → 0.0  penalty but not elimination
      400 chars → 0.5  thin but workable
      800 chars → 1.0  full score (rich background)
      1200 chars→ 1.0  capped (extra chars don't help Agent 5)
    """
    if not stories:
        return stories

    # normalise velocity relative to this batch
    max_velocity = max(s.get("velocity", 0) for s in stories.values())
    if max_velocity == 0:
        max_velocity = 1   # avoid division by zero

    print(f"  [editorial] max velocity this batch: {max_velocity:.1f}")

    for sid, story in stories.items():
        cred   = story.get("credibility_score", 0.0)
        vel    = story.get("velocity", 0.0)
        bg_len = len(story.get("background", ""))

        vel_norm = min(vel / max_velocity, 1.0)
        bg_norm  = min(bg_len / BG_FULL_CHARS, 1.0)

        e_score = round(
            cred     * 0.50 +
            vel_norm * 0.30 +
            bg_norm  * 0.20,
            3
        )

        story["editorial_score"] = e_score
        story["_vel_norm"]       = round(vel_norm, 3)
        story["_bg_norm"]        = round(bg_norm, 3)

        print(f"  [editorial] {story['title'][:45]:<45} "
              f"cred={cred:+.2f} vel={vel_norm:.2f} "
              f"bg={bg_norm:.2f} → {e_score:.3f}")

    return stories


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 3 — deduplicate_topics
# ─────────────────────────────────────────────────────────────────────────────

def deduplicate_topics(stories: dict) -> dict:
    """Cluster stories by topic using phi3.5 — one call, no context bleed.

    Problem: 3 stories all about "AI model releases" → bad diversity
    Solution: group by topic, keep only the highest editorial_score
              from each topic cluster

    Why phi3.5 (not 8B, not 120b):
      - Classification task, not generation → small model sufficient
      - One single call (all titles in one prompt) → NO context bleed
      - Already in pipeline (Agent 2 wiki keyword extraction)
      - ~3x faster than 8B for this task

    Why ONE call (not pairwise):
      - Pairwise: 8×8/2 = 28 calls → slow, wasteful
      - One call: send all 8 titles → phi3.5 clusters them → done
      - Context bleed only happens with sequential calls, not one call

    Returns stories with _topic_cluster field added.
    Stories that are duplicates within a cluster are marked:
      story["_is_duplicate"] = True (kept in state, excluded from selection)
    """
    if len(stories) <= 1:
        for story in stories.values():
            story["_topic_cluster"] = 0
            story["_is_duplicate"]  = False
        return stories

    titles = [(sid, story["title"]) for sid, story in stories.items()]
    numbered_titles = "\n".join(
        f"{i+1}. {title}" for i, (_, title) in enumerate(titles)
    )

    prompt = f"""You are a news editor grouping stories by topic for a YouTube channel.

        Two stories belong in the SAME group ONLY if they are about the 
        EXACT SAME news event, product release, or specific controversy.
        
        DIFFERENT topics — do NOT group these together:
          - A story about building home storage ≠ a story about text-to-speech software
          - A story about media accuracy ≠ a story about old computer science lectures
          - A security vulnerability story ≠ a government policy story
          - Two stories in the "tech" category does NOT make them the same topic
        
        SAME topic — only group if literally the same news:
          - Two stories both covering the same product launch = same group
          - Two stories both about the same CVE = same group
          - Two stories both about the same court ruling = same group
        
        When in doubt → put stories in SEPARATE groups.
        Prefer more groups over fewer groups.
        
        Titles:
        {numbered_titles}
        
        Return ONLY a JSON array of arrays of integers.
        Every number 1 to {len(titles)} must appear exactly once.
        Default assumption: each story is its own group unless obviously the same news.
        
        JSON:"""

    try:
        resp = ollama.generate(
        model="qwen2.5:7b",
        prompt=prompt,
        stream=False,
        options={"temperature": 0.1, "num_ctx": 4096, "keep_alive": 0},)

        raw = resp["response"].strip()
        print(f"  [deduplicate] qwen2.5:7b raw output: {raw[:120]}")

        # ── LAYER 1: clean malformed JSON before parsing ──────────────
        # phi3.5 sometimes adds trailing commas → invalid JSON
        # e.g. [["1",], ["2",]] → [["1"], ["2"]]
        import re
        raw_clean = re.sub(r',\s*]', ']', raw)
        raw_clean = re.sub(r',\s*}', '}', raw_clean)
        # ─────────────────────────────────────────────────────────────

        # ── strip all whitespace so "[ [1,3]" becomes "[[1,3]" ──────────
        # phi3.5 sometimes returns [ [1,3], [2,5] ] with spaces
        # find("[[") fails on "[ [" — compacting fixes this
        raw_compact = raw_clean.replace(" ", "").replace("\n", "").replace("\t", "")
        # ─────────────────────────────────────────────────────────────

        # parse JSON — find the array in the compacted response
        start = raw_compact.find("[[")
        end   = raw_compact.rfind("]]") + 2
        if start == -1 or end == 1:
            raise ValueError("no JSON array found in response")

        clusters = json.loads(raw_compact[start:end])

        # ── LAYER 2: extract integers — handles text mixed with numbers ─
        # phi3.5 sometimes returns ["1", "title text"] instead of [1]
        clean_clusters = []
        for group in clusters:
            nums = []
            for item in group:
                if isinstance(item, int):
                    nums.append(item)
                else:
                    m = re.match(r'\d+', str(item).strip())
                    if m:
                        nums.append(int(m.group()))
            if nums:
                clean_clusters.append(nums)
        clusters = clean_clusters
        # ─────────────────────────────────────────────────────────────

        print(f"  [deduplicate] {len(clusters)} topic clusters found")

        # assign cluster IDs and mark duplicates
        sid_list = [sid for sid, _ in titles]

        for cluster_idx, group in enumerate(clusters):
            # get all stories in this cluster
            cluster_sids = []
            for num in group:
                idx = int(num) - 1
                if 0 <= idx < len(sid_list):
                    cluster_sids.append(sid_list[idx])

            if not cluster_sids:
                continue

            # find the best story in this cluster by editorial_score
            best_sid = max(
                cluster_sids,
                key=lambda s: stories[s].get("editorial_score", 0)
            )

            for sid in cluster_sids:
                stories[sid]["_topic_cluster"] = cluster_idx
                stories[sid]["_is_duplicate"]  = (sid != best_sid)
                if stories[sid]["_is_duplicate"]:
                    print(f"  [deduplicate] duplicate → {stories[sid]['title'][:50]}")
                else:
                    print(f"  [deduplicate] cluster {cluster_idx} best → "
                          f"{stories[sid]['title'][:50]}")

    except Exception as e:
        print(f"  [deduplicate] qwen2.5:7b failed ({type(e).__name__}: {e}) "
              f"→ no deduplication, all stories eligible")
        # safe fallback: treat every story as its own cluster
        for i, (sid, story) in enumerate(stories.items()):
            story["_topic_cluster"] = i
            story["_is_duplicate"]  = False

    return stories


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 4 — select_top_stories
# ─────────────────────────────────────────────────────────────────────────────

def select_top_stories(stories: dict) -> dict:
    """Select top stories by editorial_score with topic diversity enforced.

    Selection pool:
      - eligible (not discarded by Agent 3)
      - not a duplicate within its topic cluster

    Selection order:
      - sorted by editorial_score descending
      - take up to MAX_SELECTED (3)

    If fewer than MAX_SELECTED stories available:
      - take what we have (real newsrooms don't wait for a quota)
      - ≥1 story → proceed to Agent 5
      - 0 stories → trigger end route + macOS notification

    Adds to each story:
      selected         True / False
      selection_rank   1, 2, 3 (or None)
      selection_reason why this story was picked (audit trail)
    """
    # initialise fields for all stories
    for story in stories.values():
        story["selected"]        = False
        story["selection_rank"]  = None
        story["selection_reason"] = None

    # selection pool: not duplicate within cluster
    pool = {
        sid: story
        for sid, story in stories.items()
        if not story.get("_is_duplicate", False)
    }

    # sort by editorial_score descending
    ranked = sorted(
        pool.items(),
        key=lambda x: x[1].get("editorial_score", 0),
        reverse=True
    )

    print(f"  [select] {len(pool)} unique-topic stories → "
          f"selecting top {min(MAX_SELECTED, len(pool))}")

    selected_count = 0
    for sid, story in ranked:
        if selected_count >= MAX_SELECTED:
            break

        selected_count += 1
        story["selected"]       = True
        story["selection_rank"] = selected_count
        story["selection_reason"] = (
            f"rank {selected_count}: "
            f"editorial={story.get('editorial_score', 0):.3f} "
            f"(cred={story.get('credibility_score', 0):+.2f} "
            f"vel={story.get('_vel_norm', 0):.2f} "
            f"bg={story.get('_bg_norm', 0):.2f})"
        )

        flag = "✅" if story.get("credibility_score", 0) > 0.5 else "⚠️"
        print(f"  [select] #{selected_count} {flag} "
              f"score={story['editorial_score']:.3f} | "
              f"{story['title'][:55]}")

    if selected_count == 0:
        print("  [select] ❌ NO stories selected — pipeline will exit")
        _notify_no_stories()
    else:
        print(f"  [select] {selected_count} stories selected → "
              f"passing to Agent 5 (Script Writer)")

    return stories


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — macOS notification when pipeline has nothing to publish
# ─────────────────────────────────────────────────────────────────────────────

def _notify_no_stories() -> None:
    """Fire a macOS notification when no stories pass editorial selection.
    Silent no-op on non-Mac systems.
    """
    try:
        subprocess.run([
            "osascript", "-e",
            'display notification "No credible stories today — '
            'pipeline stopped before scripting" '
            'with title "AI Newsroom: 0 Stories Selected" '
            'sound name "Basso"'
        ], check=False, capture_output=True)
    except FileNotFoundError:
        pass   # not on macOS — silent skip


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 5 — editorial_node (LangGraph node)
# ─────────────────────────────────────────────────────────────────────────────

def editorial_node(state: dict) -> dict:
    """LangGraph node — orchestrates the full Agent 4 pipeline.

    Calls functions 1-4 in sequence:
      filter → score → deduplicate → select

    Returns updated state with all Agent 4 fields added to stories.
    """
    stories = state["stories"]

    print("=" * 70)
    print("AGENT 4: Editorial")
    print("=" * 70)

    # Step 1: filter discarded stories
    eligible = filter_stories(stories)
    print()

    # Step 2: compute editorial scores
    eligible = score_editorially(eligible)
    print()

    # Step 3: deduplicate by topic (phi3.5, one call)
    eligible = deduplicate_topics(eligible)
    print()

    # Step 4: select top stories
    eligible = select_top_stories(eligible)

    # merge eligible (enriched) back into full stories dict
    # so discarded stories still appear in audit trail
    for sid, story in eligible.items():
        stories[sid] = story

    return {"stories": stories}


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION 6 — route_after_editorial (LangGraph conditional edge)
# ─────────────────────────────────────────────────────────────────────────────

def route_after_editorial(state: dict) -> str:
    """LangGraph conditional edge — first routing decision in the pipeline.

    Previous agents (1, 2, 3) were all LINEAR — no branching.
    This is the first CONDITIONAL edge in the graph.

    Routes:
      ≥ 1 selected story → "script_writer" (Agent 5)
      0 selected stories → "end" (pipeline exits, user notified)

    Real newsroom logic: even 1 great story is worth covering.
    A fixed quota of 3 is wrong — quality over quantity.
    """
    selected = [
        story for story in state["stories"].values()
        if story.get("selected", False)
    ]

    print(f"\n  [route] {len(selected)} stories selected")

    if len(selected) >= MIN_STORIES_TO_RUN:
        print(f"  [route] → script_writer (Agent 5)")
        return "script_writer"
    else:
        print(f"  [route] → end (no stories to script today)")
        return "end"