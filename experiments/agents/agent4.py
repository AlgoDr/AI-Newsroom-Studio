"""
agent4.py — Editorial Agent

Role: "Which 3 stories should we actually cover today?"

Responsibilities:
  1. filter_stories()       — remove Agent 3 discards (score < 0.0)
  2. score_editorially()    — compute editorial_score per story
  3. deduplicate_topics()   — granite4.2:8b clusters titles → keep best per topic
  4. select_top_stories()   — pick top 3 (or fewer) by editorial_score
  5. editorial_node()       — LangGraph node (orchestrates 1-4)
  6. route_after_editorial()— LangGraph conditional edge (→ Agent 5 or end)

What Agent 4 does NOT do:
  - Does not re-fetch content (Agent 2 did that)
  - Does not re-score credibility (Agent 3 did that)
  - Does not write scripts (Agent 5 will do that)
  - Does not call any cloud API (granite4.2:8b is local)

Model selection — granite4.2:8b + Prompt V3:
  Tested 3 local models (qwen3.5:9b, gemma4:12b-mlx, granite4.2:8b)
  across 3 prompt versions on 10-set golden dataset (80 titles, 5 pairs).
  granite4.2:8b + V3 was the only combination to PASS the F1≥0.70 gate.
  N=5 reliability test confirmed: 5/5 PASS, F1 avg=0.818, min=0.800.
  See evals/results/agent4_baseline.md for full experiment history.

Keys added to story dict:
  editorial_score   float  — composite editorial rank (0.0 to 1.0)
  selected          bool   — True if chosen for scripting
  selection_rank    int    — 1, 2, 3 (or None if not selected)
  selection_reason  str    — why this story was picked (audit trail)
  _vel_norm         float  — normalised velocity (audit trail)
  _bg_norm          float  — normalised background score (audit trail)
  _topic_cluster    int    — which topic cluster granite4.2:8b assigned
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
    """Cluster stories by topic using granite4.2:8b — one call, Prompt V3.

    Problem: 3 stories all about "AI model releases" → bad diversity
    Solution: group by topic, keep only the highest editorial_score
              from each topic cluster

    Model: granite4.2:8b (local, Ollama)
      - Selected via multi-model eval on 10-set golden dataset
      - Only model to PASS F1≥0.70 gate (F1=0.800, 8/10 sets perfect)
      - N=5 reliability test: 5/5 PASS, avg F1=0.818, deterministic
      - Fastest of 3 tested models (~7.6s/set)
      - See evals/results/agent4_baseline.md

    Prompt V3 (integer few-shot):
      - Fixed V2 format bug (string examples → model returned strings)
      - Integer-only example [[1],[2,5],[3],[4],[6]]
      - "When in doubt → SEPARATE groups" bias

    Why ONE call (not pairwise):
      - Pairwise: 8×8/2 = 28 calls → slow, wasteful
      - One call: send all 8 titles → model clusters them → done

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

    # ── Prompt V3: integer few-shot, product-family rules ─────────
    prompt = f"""Group these numbered titles by SAME specific event or product.

Rules:
- SAME group: same product launch, same CVE, same court ruling, same company announcement
- SAME group: "ProductX 3" and "ProductX 3 Pro variant" = same product family
- SAME group: two RFCs about the same standard (e.g. TLS 1.2 deprecation) = same effort
- DIFFERENT: two stories that share a tech domain (both AI, both C++, both security) but are about different specific things
- When in doubt → SEPARATE groups

Titles:
{numbered_titles}

Return ONLY a JSON array of arrays of integers (1-indexed).
Every number from 1 to {len(titles)} must appear exactly once.
Example for 6 titles where 2 and 5 cover the same event:
[[1],[2,5],[3],[4],[6]]

JSON:"""

    try:
        resp = ollama.generate(
            model="granite4.2:8b",
            prompt=prompt,
            stream=False,
            think=False,
            keep_alive=0,
            options={"temperature": 0.1, "num_ctx": 4096},
        )

        raw = resp["response"].strip()
        print(f"  [deduplicate] granite4.2:8b raw: {raw[:120]}")

        # ── Clean malformed JSON ─────────────────────────────────────
        import re
        raw_clean = re.sub(r',\s*]', ']', raw)
        raw_clean = re.sub(r',\s*}', '}', raw_clean)
        raw_compact = raw_clean.replace(" ", "").replace("\n", "").replace("\t", "")

        # ── Handle missing outer brackets: [1],[2],[3] → [[1],[2],[3]]
        if "[[" not in raw_compact and re.match(r'\[\d', raw_compact):
            raw_compact = "[" + raw_compact + "]"
            print(f"  [deduplicate] wrapped missing outer brackets")

        # ── Parse JSON array ─────────────────────────────────────────
        start = raw_compact.find("[[")
        end   = raw_compact.rfind("]]") + 2
        if start == -1 or end == 1:
            raise ValueError(f"no JSON array found in: {raw_compact[:80]}")

        clusters = json.loads(raw_compact[start:end])

        # ── Extract integers only (strict: pure digits only) ─────────
        # V3 fix: r'^\d+$' not r'\d+' — prevents extracting leading
        # digits from titles like "25 Gbps Thunderbolt..."
        clean_clusters = []
        for group in clusters:
            nums = []
            for item in group:
                if isinstance(item, int):
                    nums.append(item)
                elif isinstance(item, str):
                    m = re.match(r'^\d+$', item.strip())
                    if m:
                        nums.append(int(m.group()))
            if nums:
                clean_clusters.append(nums)
        clusters = clean_clusters

        print(f"  [deduplicate] {len(clusters)} topic clusters found")

        # ── Assign cluster IDs and mark duplicates ───────────────────
        sid_list = [sid for sid, _ in titles]
        assigned = set()

        for cluster_idx, group in enumerate(clusters):
            cluster_sids = []
            for num in group:
                idx = int(num) - 1
                if 0 <= idx < len(sid_list):
                    cluster_sids.append(sid_list[idx])
                    assigned.add(sid_list[idx])

            if not cluster_sids:
                continue

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

        # ── Safety: unassigned stories get their own cluster ─────────
        # Prevents mega-cluster bug if model omits some numbers
        next_cid = len(clusters)
        for sid, story in stories.items():
            if sid not in assigned:
                story["_topic_cluster"] = next_cid
                story["_is_duplicate"]  = False
                next_cid += 1

    except Exception as e:
        print(f"  [deduplicate] granite4.2:8b failed ({type(e).__name__}: {e}) "
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