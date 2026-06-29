import os
import dotenv
from urllib.parse import urlparse
from groq import Groq

dotenv.load_dotenv(".env")

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

MIN_CREDIBILITY = 0.4        # below this → mark story as discarded (audit trail)
DEFAULT_SOURCE_SCORE = 0.5   # unknown domain → neutral

# ─────────────────────────────────────────────
# PIECE 1 — SOURCE SCORE (domain credibility)
# Tuned for HackerNews traffic: primary sources dominate HN,
# wire services are rare but trusted when they appear.
# ─────────────────────────────────────────────

SOURCE_TIERS = {
    # 0.9 — primary sources (code + papers dominate HN)
    "github.com":          0.9,
    "arxiv.org":           0.9,

    # 0.85 — peer-reviewed science (rare on HN but gold standard)
    "nature.com":          0.85,
    "science.org":         0.85,

    # 0.8 — established tech press (solid HN regulars)
    "arstechnica.com":     0.8,
    "theverge.com":        0.8,
    "wired.com":           0.8,
    "quantamagazine.org":  0.8,

    # 0.75 — wire services (rare on HN but trustworthy)
    "reuters.com":         0.75,
    "apnews.com":          0.75,
    "bbc.com":             0.75,
}


def source_score(url: str) -> float:
    """Domain credibility, tuned for HN traffic.
    Primary sources (code/papers) score highest.
    Unknown blogs/company sites get neutral 0.5."""
    if not url:
        return DEFAULT_SOURCE_SCORE
    try:
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        return SOURCE_TIERS.get(domain, DEFAULT_SOURCE_SCORE)
    except Exception:
        return DEFAULT_SOURCE_SCORE


# ─────────────────────────────────────────────
# PIECE 2 — LLM CREDIBILITY CHECK (Groq gpt-oss-120b)
# Uses a 120B model with broad world knowledge to judge
# if the SUBJECT is real — not just if the writing is journalistic.
# This fixes the 3B model's failure to recognise real entities like
# Haystack, Bunny DNS, Krea 2 as genuine products/companies.
# ─────────────────────────────────────────────

groq_client = Groq(api_key=os.getenv("GROQ_KEY"))

# label → score mapping
LABEL_SCORES = {
    "REAL":     0.9,   # genuine product / tech / company / event / research
    "OPINION":  0.5,   # personal essay or opinion piece — legitimate but not news
    "SPAM":     0.2,   # scam / clickbait / misinformation
}



def llm_credibility_check(title: str, content: str) -> float:
    if not content or len(content) < 100:
        print(f"  [cred] empty content → 0.3")
        return 0.3

    if len(content) < 500:
        print(f"  [cred] thin content ({len(content)} chars) → 0.5 neutral")
        return 0.5

    prompt = f"""Classify what this article is about.

TITLE: {title}

ARTICLE:
{content}

Categories:
- REAL: a genuine product, technology, company, research finding, or event
        (real things can have promotional tone — that is still REAL)
- OPINION: a personal essay, rant, or opinion piece (not reporting a thing)
- SPAM: scam, clickbait, or misinformation with no real substance

Respond with ONLY one word: REAL, OPINION, or SPAM.

Verdict:"""

    try:
        resp = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=100,    # room for any preamble before the verdict word
        )
        raw = resp.choices[0].message.content
        print(f"  [cred DEBUG] raw={repr(raw[:80])}")   # ← add this temporarily
        if not raw or not raw.strip():
            print(f"  [cred] empty response → 0.5 neutral")
            return 0.5

        label = raw.strip().upper()
        for word in ["REAL", "OPINION", "SPAM"]:
            if word in label:
                score = LABEL_SCORES[word]
                print(f"  [cred] {title[:40]} → {word!r} → {score}  (via {resp.model})")
                return score

        print(f"  [cred] {title[:40]} → unparseable {label!r} → 0.5")
        return 0.5

    except Exception as e:
        print(f"  [cred] Groq failed for '{title[:30]}': {e} → 0.5 neutral")
        return 0.5

# ─────────────────────────────────────────────
# PIECE 3 — COMBINED CREDIBILITY + DISCARD MARKING
# src (25%) is a small bonus for known-trustworthy domains.
# llm (75%) does the heavy lifting via 120B world knowledge.
# Marks story["discarded"] but does NOT delete — audit trail.
# ─────────────────────────────────────────────

def check_credibility(story: dict) -> dict:
    """Full credibility pipeline for one story:
      1. source_score  — domain trust (25% weight)
      2. llm check     — 120B judges if subject is REAL/OPINION/SPAM (75%)
      3. combined score → mark discarded if below MIN_CREDIBILITY
    Returns the story dict enriched with credibility_score + discarded keys."""
    src = source_score(story.get("url", ""))
    llm = llm_credibility_check(story.get("title", ""), story.get("content", ""))

    score = round(src * 0.25 + llm * 0.75, 2)

    story["credibility_score"] = score
    story["discarded"] = score < MIN_CREDIBILITY
    return story