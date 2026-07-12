import os
import dotenv
import ollama
from urllib.parse import urlparse
from groq import Groq
from ddgs import DDGS
import time

dotenv.load_dotenv(".env")

# -- optional dependency: exa_py --------------------------------------------
# Exa is the primary cross-verification search engine (semantic, HN-aware).
# If not installed, DDG is used as the sole verification source.
# Install: pip install exa-py
try:
    import exa_py
    EXA_AVAILABLE = True
except ImportError:
    EXA_AVAILABLE = False
    print("[agent3] exa-py not installed -- cross-verify will use DDG only")

# -----------------------------------------------------------------------------
# CLIENTS -- instantiated once at module load, reused for all stories
# Never instantiated inside functions (avoids per-call overhead)
# -----------------------------------------------------------------------------

groq_client = Groq(api_key=os.getenv("GROQ_KEY"))

# Exa client -- lazy singleton (created on first use, reused after)
# Lazy because EXA_API_KEY might not be set during testing
_exa_client = None

def _get_exa_client():
    """Return the shared Exa client, creating it on first call."""
    global _exa_client
    if _exa_client is None and EXA_AVAILABLE:
        api_key = os.getenv("EXA_API_KEY")
        if api_key:
            _exa_client = exa_py.Exa(api_key=api_key)
        else:
            print("[agent3] EXA_API_KEY not set -- Exa disabled")
    return _exa_client

# -----------------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------------

MIN_CREDIBILITY = 0.0        # zero is the natural boundary in -1 to +1 design
                              # negative = active negative evidence -> discard
                              # positive or zero = keep (benefit of the doubt)

CREDIBILITY_FALLBACK_MODEL = "qwen2.5:7b"   # local fallback for
                                             # llm_credibility_check(), see
                                             # that function's docstring

# -----------------------------------------------------------------------------
# PIECE 1 -- SOURCE SCORE (domain credibility)
# Returns 0.0 to +0.9. Never negative -- no manual blocklist.
# HN community pre-filters bad actors before Agent 3 runs.
# -----------------------------------------------------------------------------

SOURCE_TIERS = {

    # +0.95 -- primary sources: the thing itself, not reporting about it
    "github.com":              0.95,
    "arxiv.org":               0.95,
    "openai.com":              0.95,
    "anthropic.com":           0.95,
    "deepmind.google":         0.95,
    "huggingface.co":          0.95,

    # +0.90 -- peer-reviewed science and engineering gold standard
    "nature.com":              0.90,
    "science.org":             0.90,
    "ieee.org":                0.90,
    "acm.org":                 0.90,

    # +0.85 -- established tech press, 10+ year track record
    "arstechnica.com":         0.85,
    "wired.com":               0.85,
    "techcrunch.com":          0.85,
    "technologyreview.com":    0.85,   # MIT Tech Review
    "quantamagazine.org":      0.85,
    "spectrum.ieee.org":       0.85,

    # +0.80 -- solid HN regulars, good editorial standards
    "theverge.com":            0.80,
    "venturebeat.com":         0.80,
    "zdnet.com":               0.80,
    "cnet.com":                0.80,
    "engadget.com":            0.80,
    "infoq.com":               0.80,
    "hackaday.com":            0.80,
    "lwn.net":                 0.80,

    # +0.75 -- wire services and general press
    "reuters.com":             0.75,
    "apnews.com":              0.75,
    "bbc.com":                 0.75,
    "bloomberg.com":           0.75,
    "ft.com":                  0.75,
    "wsj.com":                 0.75,
    "nytimes.com":             0.75,

    # +0.70 -- respected individual expert blogs (10+ year track record)
    "simonwillison.net":       0.70,
    "paulgraham.com":          0.70,
    "danluu.com":              0.70,
    "joelonsoftware.com":      0.70,
}

# minimum trust for a source to trigger verification/contradiction signals
VERIFY_TRUST_THRESHOLD = 0.70


def source_score(url: str) -> float:
    """Domain credibility lookup. Returns 0.0 to +0.95.
    Unknown domains return 0.0 (neutral) -- never negative.
    HN community pre-filters bad actors upstream."""
    if not url:
        return 0.0
    try:
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        return SOURCE_TIERS.get(domain, 0.0)
    except Exception:
        return 0.0


# -----------------------------------------------------------------------------
# PIECE 2 -- LLM CREDIBILITY CHECK (gpt-oss-120b, with local fallback)
# Returns -0.7 to +0.9. Negative only when model detects SPAM.
# 120b used here for its world knowledge (recognises real entities).
# -----------------------------------------------------------------------------

LABEL_SCORES = {
    "REAL":    +0.9,   # genuine product / tech / event / research
    "OPINION": +0.1,   # personal essay -- legitimate but not news
    "SPAM":    -0.7,   # scam / clickbait / misinformation -> negative
}


def llm_credibility_check(title: str, content: str) -> float:
    """Classify content as REAL/OPINION/SPAM using gpt-oss-120b.

    Guards (checked before calling any model -- unchanged):
      < 100 chars -> 0.0 neutral (can't judge, lean toward neutral)
      < 500 chars -> 0.0 neutral (too thin to classify reliably)

    Fallback (NEW): if gpt-oss-120b fails, returns empty, or gives an
    unparseable response, falls back to qwen2.5:7b (local, Ollama)
    before giving up. Previously this function had NO fallback at
    all -- any Groq failure silently returned 0.0 neutral, which
    during a full-run Groq outage (a recurring, confirmed issue this
    session) meant EVERY story lost its credibility signal, leaving
    Agent 4's selection driven by velocity alone.

    Confirmed via a multi-run reliability test
    (test_agent3_credibility_reliability.py): 15/15 runs across 3
    real stories -- ZFS NAS, The Economist (opinion piece), and a
    Tenda firmware CVE disclosure (a deliberate stress test for
    whether a safety filter might suppress classification of
    security-disclosure content) -- 100% consistent, 100% correct
    classification from qwen2.5:7b across all three.

    Final fallback (when BOTH models fail): 0.0 neutral -- unchanged
    from the original behavior, never discard on any failure.

    NOTE: In -1 to +1 design, 0.0 is neutral (unknown), not "bad".
    Only SPAM -> -0.7 is negative. Empty/uncertain -> 0.0.
    """
    if not content or len(content) < 100:
        print(f"  [llm_cred_check] empty content -> 0.0 neutral")
        return 0.0

    if len(content) < 500:
        print(f"  [llm_cred_check] thin content ({len(content)} chars) -> 0.0 neutral")
        return 0.0

    prompt = f"""Classify what this article is about.

TITLE: {title}

ARTICLE:
{content}

Categories:
- REAL: a genuine product, technology, company, research finding, or event
        (real things can have promotional tone -- that is still REAL)
- OPINION: a personal essay, rant, or opinion piece (not reporting a thing)
- SPAM: scam, clickbait, or misinformation with no real substance

Respond with ONLY one word: REAL, OPINION, or SPAM.

Verdict:"""

    raw = None
    try:
        resp = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=600,
        )
        raw = resp.choices[0].message.content
        print(f"  [llm_cred_check DEBUG] raw={repr(raw[:80] if raw else None)}")
    except Exception as e:
        print(f"  [llm_cred_check] Groq failed: {e}")
        raw = None

    score = _parse_credibility_label(raw, title)

    if score is None:
        print(f"  [llm_cred_check] gpt-oss-120b gave no usable label -> "
              f"falling back to local {CREDIBILITY_FALLBACK_MODEL}")
        raw_local = _llm_credibility_check_local(prompt)
        score = _parse_credibility_label(raw_local, title)

    if score is None:
        print(f"  [llm_cred_check] failed on both cloud and local -> 0.0 neutral")
        return 0.0

    return score


def _parse_credibility_label(raw, title: str):
    """Extract a REAL/OPINION/SPAM score from a raw model response.

    Returns the score (float) if a usable label is found, or None if
    the response was empty or unparseable -- the caller decides
    whether to attempt a fallback or give up with 0.0 neutral.
    """
    if not raw or not raw.strip():
        return None

    label = raw.strip().upper()
    for word in ["REAL", "OPINION", "SPAM"]:
        if word in label:
            score = LABEL_SCORES[word]
            print(f"  [llm_cred_check] {title[:40]!r} -> {word!r} -> {score}")
            return score

    print(f"  [llm_cred_check] unparseable {label[:30]!r}")
    return None


def _llm_credibility_check_local(prompt: str) -> str:
    """Local fallback for credibility classification -- qwen2.5:7b via
    Ollama, Metal-accelerated. Used only when gpt-oss-120b fails,
    returns empty, or gives an unparseable response.

    Confirmed via multi-run reliability test: 15/15 runs across 3 real
    stories (ZFS NAS, The Economist, Tenda firmware CVE), 100%
    consistent, 100% correct -- including the security-disclosure
    edge case.
    """
    try:
        resp = ollama.generate(
            model=CREDIBILITY_FALLBACK_MODEL,
            prompt=prompt,
            stream=False,
            keep_alive=0,
            options={"temperature": 0.1, "num_ctx": 4096},
        )
        return (resp.get("response") or "").strip()
    except Exception as e:
        print(f"  [llm_cred_check] local fallback also failed: {e}")
        return ""


# -----------------------------------------------------------------------------
# PIECE 3 -- CROSS VERIFICATION (Exa -> DDG -> neutral)
# Returns (verified, contradicted, source_domain)
# Only credible sources (trust >= 0.70) can trigger verification signals.
# Uses compound-mini for contradiction check (separate quota pool).
# -----------------------------------------------------------------------------

def _fetch_exa_results(title: str) -> list:
    """Fetch news results from Exa. Returns list of {url, text} dicts.
    Uses exa.search() -- search_and_contents() is deprecated in current exa-py.
    Returns empty list on any failure -- caller falls to DDG.
    """
    exa = _get_exa_client()
    if exa is None:
        return []
    try:
        results = exa.search(
            title,
            type="neural",
            num_results=5,
            contents={
                "text": {"max_characters": 400}
            },
        )
        return [{"url": r.url, "text": r.text or ""}
                for r in results.results]
    except Exception as e:
        print(f"  [verify] Exa failed ({type(e).__name__}: {e}) -> DDG")
        return []


def _fetch_ddg_results(title: str) -> list:
    """Fetch news results from DDG. Returns list of {url, text} dicts.
    Returns empty list on any failure -- caller returns neutral."""
    try:
        with DDGS(timeout=10) as ddgs:
            results = list(ddgs.news(title[:100], max_results=5))
        time.sleep(3)
        return [{"url": r.get("url", ""), "text": r.get("body", "")}
                for r in results]
    except Exception as e:
        print(f"  [verify] DDG failed ({type(e).__name__})")
        return []


def _check_contradiction(story_content: str,
                          result_snippet: str) -> bool:
    """Ask compound-mini if the result contradicts the story.
    Uses compound-mini (not 120b or 20b) -- separate quota pool,
    simple binary task well within compound-mini's capability.
    Safe default: False (assume consistent on any failure).
    """
    prompt = f"""Does SOURCE B contradict SOURCE A on a specific fact?

SOURCE A:
{story_content[:1000]}

SOURCE B:
{result_snippet[:1000]}

Reply with ONE word only: CONTRADICTS or CONSISTENT or UNRELATED"""

    time.sleep(2)
    try:
        resp = groq_client.chat.completions.create(
            model="groq/compound-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.1,
        )
        answer = resp.choices[0].message.content.strip().upper()
        print(f"  [verify] contradiction check -> {repr(answer)}")
        return "CONTRADICTS" in answer
    except Exception as e:
        print(f"  [verify] contradiction check failed ({e}) -> assume consistent")
        return False   # safe default -- never penalize on failure


def cross_verify(title: str,
                 story_url: str,
                 content: str) -> tuple[bool, bool, str]:
    """Search for the story in a second credible source.

    Tier 1: Exa semantic search (HN-aware, finds story variants)
    Tier 2: DDG keyword fallback (already in pipeline, free)
    Tier 3: neutral if both fail

    Only sources with trust >= VERIFY_TRUST_THRESHOLD (0.70) can trigger
    verification or contradiction signals. Unknown sources are ignored.

    Returns: (verified: bool, contradicted: bool, source_domain: str)
      verified=True,  contradicted=False -> confirmed by credible source
      verified=False, contradicted=True  -> contradicted by credible source
      verified=False, contradicted=False -> not found or neutral
    """
    story_domain = urlparse(story_url).netloc.replace("www.", "")

    # try Exa first, fall back to DDG
    results = _fetch_exa_results(title)
    if not results:
        results = _fetch_ddg_results(title)

    for result in results:
        result_domain = urlparse(
            result["url"]
        ).netloc.replace("www.", "")

        if result_domain == story_domain:
            continue   # skip the original source itself

        trust = SOURCE_TIERS.get(result_domain, 0.0)

        if trust < VERIFY_TRUST_THRESHOLD:
            continue   # not credible enough to act on

        # credible source found -- does it agree or contradict?
        contradicts = _check_contradiction(
            story_content=content,
            result_snippet=result["text"],
        )

        if contradicts:
            print(f"  contradict claim [verify] contradicted by {result_domain} "
                  f"(trust={trust})")
            return False, True, result_domain

        else:
            print(f"  contradict claim[verify] confirmed by {result_domain} "
                  f"(trust={trust})")
            return True, False, result_domain

    print(f"  [verify] neutral -- no credible source found or both tiers failed")
    return False, False, "NONE"


# -----------------------------------------------------------------------------
# PIECE 4 -- COMBINED SCORING WITH DYNAMIC REWEIGHTING
# -1.0 to +1.0 range. Zero is the natural discard boundary.
# Weights shift when cross-verify finds confirmation or contradiction.
# -----------------------------------------------------------------------------

def check_credibility(story: dict) -> dict:
    """Full credibility pipeline for one story.

    Three signals:
      source_score     (20%) -- domain trust
      llm_credibility  (60%) -- REAL/OPINION/SPAM via gpt-oss-120b
      cross_verify     (20%) -- second-source confirmation via Exa/DDG

    Dynamic reweighting:
      contradiction detected -> llm 60%->30%, verify 20%->50%
        (credible contradiction is strong signal, should override LLM)
      confirmation detected  -> llm 60%->50%, verify 20%->30%
        (confirmation boosts verify slightly)
      neutral                -> normal weights unchanged

    Score range: -0.70 to +0.95 in practice.
    Threshold: score < 0.0 -> discarded (never deleted, audit trail preserved).
    """
    src  = source_score(story.get("url", ""))

    llm  = llm_credibility_check(
               story.get("title", ""),
               story.get("content", "")
           )

    verified, contradicted, verified_by = cross_verify(
               story.get("title", ""),
               story.get("url", ""),
               story.get("content", "")
           )

    # -- dynamic reweighting -----------------------------------------
    if contradicted:
        # credible source contradicts -> amplify verify, reduce llm
        w_src, w_llm, w_verify = 0.20, 0.30, 0.50
        verify_score = -0.6
        regime = "contradiction"
    elif verified:
        # credible source confirms -> slight verify boost
        w_src, w_llm, w_verify = 0.20, 0.50, 0.30
        verify_score = +0.8
        regime = "confirmation"
    else:
        # neutral -> standard weights
        w_src, w_llm, w_verify = 0.20, 0.60, 0.20
        verify_score = 0.0
        regime = "neutral"

    score = round(
        src          * w_src   +
        llm          * w_llm   +
        verify_score * w_verify,
        2
    )

    print(f"  [cred] regime={regime} | "
          f"src={src:.2f}x{w_src} + "
          f"llm={llm:.2f}x{w_llm} + "
          f"verify={verify_score:.2f}x{w_verify} = {score:.2f}")

    story["credibility_score"] = score
    story["verified_by"]       = verified_by
    story["contradicted"]      = contradicted
    story["discarded"]         = score < MIN_CREDIBILITY
    story["_cred_regime"]      = regime   # audit trail: which weights fired
    story["_weights_used"]     = f"{w_src}/{w_llm}/{w_verify}"  # src/llm/verify
    return story