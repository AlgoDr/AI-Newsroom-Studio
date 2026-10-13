# this agent fetches the trends from hackernews api with the enagement with respect to velocity

import requests
import os
from datetime import datetime
from typing_extensions import TypedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
import dotenv
dotenv.load_dotenv('.env')

HEADERS = {"User-Agent": "newsroom-studio/1.0"}



# 1. Hackernews — zero auth, works immediately


def fetch_trends(top_n: int =8) -> list:
    "to fetch Tech-Trends from hackernews"


    ids = requests.get(
        "https://hacker-news.firebaseio.com/v0/topstories.json",
        headers=HEADERS,
        timeout=10,
    ).json()[:top_n + top_n // 2] # over-fetch to compensate for non-story items (jobs, polls)

    # B6 fix: fetch items concurrently (was sequential — 9 requests × ~0.7s = ~6s)
    def _fetch_item(sid):
        try:
            return requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                headers=HEADERS,
                timeout=10,
            ).json()
        except Exception:
            return None

    stories = []
    with ThreadPoolExecutor(max_workers=len(ids)) as pool:
        futures = {pool.submit(_fetch_item, sid): sid for sid in ids}
        for future in as_completed(futures):
            s = future.result()

            if not s or s.get("type") != "story":
                continue

            # by default hackernews api does not give velocity & engagement
            # we calculate it using ttl & people engaging in conversation

            upvotes  = s.get("score", 0)
            comments = s.get("descendants", 0)
            age_hrs  = max((datetime.now().timestamp() - s.get("time", 0)) / 3600, 1)
            velocity = round((upvotes + comments * 2) / age_hrs, 1)

            stories.append({
                "title":      s.get("title", ""),
                "url":        s.get("url", ""),
                "source":     "hackernews",
                "category":   "technology",
                "engagement": upvotes + comments,
                "velocity":   velocity,
            })

    stories.sort(key=lambda x: x["velocity"], reverse=True)
    return stories[:top_n]




#func_call=fetch_trends()
#print(func_call)



