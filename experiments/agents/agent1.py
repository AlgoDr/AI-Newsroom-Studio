# this agent fetches the trends from hackernews api with the enagement with respect to velocity

import requests
import os
from datetime import datetime
from typing_extensions import TypedDict
import dotenv
dotenv.load_dotenv('.env')

HEADERS = {"User-Agent": "newsroom-studio/1.0"}



# 1. Hackernews — zero auth, works immediately


def fetch_trends(top_n: int =8) -> list:
    "to fetch Tech-Trends from hackernews"


    ids = requests.get(
        "https://hacker-news.firebaseio.com/v0/topstories.json",
        headers=HEADERS
    ).json()[:top_n] # fetch story id's

    stories = []
    for sid in ids:
        s= requests.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", headers=HEADERS).json() # scrapping engagement details & contents for particular story

        if not s or s.get("type") != "story":
            continue


        #print(s)
        # by default hackernews api does not give velocity & engagement we calculate it using ttl & people do engaging in conversation due to hype

        upvotes  = s.get("score", 0)
        comments = s.get("descendants", 0)
        age_hrs  = max((datetime.now().timestamp() - s.get("time", 0)) / 3600, 1) # more than 1 hour old  less than 24 hrs
        velocity = round((upvotes + comments * 2) / age_hrs, 1)

        stories.append({
            "title":      s.get("title", ""),
            "url":        s.get("url", ""),
            "source":     "hackernews",
            "category":   "technology",
            "engagement": upvotes + comments,
            "velocity":   velocity,
        })

        # sort by velocity and return top n
    stories.sort(key=lambda x: x["velocity"], reverse=True)
    return stories[:top_n]




#func_call=fetch_trends()
#print(func_call)



