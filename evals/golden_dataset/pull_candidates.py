"""Pull candidate stories from stories_cache.json for golden-dataset labeling.

Stratified sampling: takes ALL stories from small important buckets
(Show HN, academic) and randomly samples from larger buckets to reach
~45 total. Output has expected_output=null for human labeling.
"""

import json
import random
import urllib.parse
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "stories_cache.json"
OUT   = Path(__file__).resolve().parent / "agent3_credibility_candidates.json"
TARGET = 45

random.seed(42)  # reproducible sampling

with open(CACHE) as f:
    stories = json.load(f)

# --- Bucket stories by rough type ---
buckets: dict[str, list] = {
    "show_hn": [], "github": [], "blog_opinion": [],
    "academic": [], "product_eng": [], "other": [],
}

for key, s in stories.items():
    content = s.get("content", "")
    if not content or len(content) < 50:
        continue
    title = s.get("title", "")
    url   = s.get("url", "")
    domain = urllib.parse.urlparse(url).netloc if url else ""

    if title.startswith("Show HN"):
        buckets["show_hn"].append(key)
    elif "github.com" in domain:
        buckets["github"].append(key)
    elif "arxiv.org" in domain or "science.org" in domain or "nature.com" in domain:
        buckets["academic"].append(key)
    elif any(w in domain for w in ["blog", "medium.com", "substack"]):
        buckets["blog_opinion"].append(key)
    elif any(w in domain for w in ["engineering", "shopify", "cloudflare", "clickhouse"]):
        buckets["product_eng"].append(key)
    else:
        buckets["other"].append(key)

print("Bucket sizes:")
for b, keys in buckets.items():
    print(f"  {b}: {len(keys)}")

# --- Stratified sampling ---
selected_keys: list[str] = []

# Take all from small, important buckets (edge cases we need)
selected_keys.extend(buckets["show_hn"])
selected_keys.extend(buckets["academic"])

# Sample from the rest to reach TARGET
remaining_need = TARGET - len(selected_keys)
remaining_pool: list[tuple[str, str]] = []
for bname in ["github", "blog_opinion", "product_eng", "other"]:
    for k in buckets[bname]:
        remaining_pool.append((bname, k))

random.shuffle(remaining_pool)
selected_keys.extend(k for _, k in remaining_pool[:remaining_need])

print(f"\nSelected: {len(selected_keys)} stories")

# --- Build candidate JSON ---
candidates = []
for key in selected_keys:
    s = stories[key]
    url = s.get("url", "")
    domain = urllib.parse.urlparse(url).netloc if url else ""
    candidates.append({
        "input": s.get("title", ""),
        "expected_output": None,   # ← YOU fill this: "REAL", "OPINION", or "SPAM"
        "additional_metadata": {
            "story_key": key,
            "url": url,
            "domain": domain,
            "content_preview": s.get("content", "")[:500],
        },
        "comments": "",  # ← YOUR notes on why you chose that label
    })

with open(OUT, "w") as f:
    json.dump(candidates, f, indent=2)

print(f"Written to {OUT}")
print(f"\nNext: open {OUT.name}, read each title + content_preview,")
print("and set expected_output to \"REAL\", \"OPINION\", or \"SPAM\".")
