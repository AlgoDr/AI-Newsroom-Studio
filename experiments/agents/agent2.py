import os
import dotenv
from groq import Groq
dotenv.load_dotenv(".env")




import trafilatura
import requests

# groq client
groq_client = Groq(api_key=os.getenv("GROQ_KEY"))


from agent_tools.milestone_tracker import MilestoneTracker

# ISSUE-7 tracker — logs every real gpt-oss-20b firing
# alerts at 5 and 10 hits via macOS popup + marker file
oss20b_tracker = MilestoneTracker(
    name="oss20b_bigboss",
    milestone_at=[5, 10],
    log_dir="data"
)



# when content is junk
junk_markers = [
    "rate limit", "403 forbidden", "access denied",
    "enable javascript", "captcha", "are you a robot",
    # NEW — security/block pages
    "reference number", "security check",
    "akamai", "please wait", "checking your browser",
    "cloudflare", "cf-ray", "just a moment"
]


# to check content fetch is real content and not raw HTML

def looks_like_real_content(text: str) -> bool:
    """Objective check: is this real article text, not page chrome/junk?"""
    if not text or len(text) < 200:
        return False

    # 1. reject if mostly whitespace/tabs
    stripped = text.replace("\t", "").replace("\n", "").replace(" ", "")
    if len(stripped) < 100:
        return False

    # 2. reject error/block pages
    low = text[:400].lower()

    if any(j in low for j in junk_markers):
        return False
    
    # 3. reject if no real prose (menus = short fragments, articles = long lines)
    prose_lines = [ln for ln in text.split("\n") if len(ln.strip()) > 40]
    if len(prose_lines) < 3 and len(text.strip()) < 300:
        return False


    return True








#when scrap with jina the content is often not clear and contents <nav><id> html tags we have to clear them using below function
def clean_jina(text: str) -> str:
    """
    Strip Jina's metadata header if the marker appears in the header zone.
    Safe: if the marker is missing, sits deep in the body, or the split
    leaves too little, return the original text unchanged.
    """
    if not text:
        return ""

    marker = "Markdown Content:"
    pos = text.find(marker)

    # only treat as header marker if it's near the top (first 500 chars)
    if 0 <= pos < 500:
        body = text[pos + len(marker):].strip()
        if len(body) > 100:
            return body

    return text.strip()



# Fetches the content of the article from url with 3 services:

def fetch_url_content(url: str) -> str:
    if not url or not url.startswith("http"):
        return ""

    # Attempt 1 — trafilatura (free, fast)
    try:
        downloaded = trafilatura.fetch_url(url)
        text = trafilatura.extract(downloaded)
        if text and len(text) > 200:      # recived something
            if looks_like_real_content(text):
                print(f"Trafiltura Success ✅  In Loading Content :{len(text)} characters")
                return text[:6000]
            else:
                print("Trafiltura Loaded Junk Content Discarding & Switching To Jina")
    except:
        print("Trafilatura failed to fetch the content X Swithching to Jina")
        pass

    # Attempt 2 — Jina AI reader (free, handles many blocked sites)
    try:
        jina_url = f"https://r.jina.ai/{url}"
        resp = requests.get(
            jina_url,
            headers={"User-Agent": "newsroom-studio/1.0"},
            timeout=15
        )
        if resp.status_code == 200 and len(resp.text) > 200:
            cleaned=clean_jina(resp.text)

            if looks_like_real_content(cleaned):
                print(f"Jina Success ✅  In Loading Content:{len(cleaned)} characters")
                return cleaned[:6000]
            else:
                print("Jina Loaded Junk Content Discarding & Switching To Tavily")

    except:
        print("Jina failed to fetch the content X Swithching to Tavily")
        pass

    # Attempt 3 — Tavily (paid but you already have it, most reliable)
    try:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        result = tavily.extract(urls=[url])
        if result and result.get("results"):
            content = result["results"][0].get("raw_content", "")
            if looks_like_real_content(content):
                print(f"Tavily Success ✅  In Loading Content:{len(content)} characters ")
                return content[:6000]
            else:
                print("Tavily Loaded Junk Content Discarding & Returned 0 Char as all Fetcher Failed")
    except Exception as e:
        print(f"[tavily] error: {e}")
        print("All Fetcher[Trafiltura,Jina,Tavily] Failed to load the content ")

    return ""   # all attempts failed








# for searching backstory of trend it uses this pipeline


import time
from ddgs import DDGS
import ollama



# source 1 : wikipedia
import wikipedia


def fetch_wiki_background(topic: str) -> str:
    """Wikipedia backstory — what led to this moment."""
    keyword = extract_wiki_keyword(topic)
    try:
        return wikipedia.summary(keyword , sentences=12)
    except wikipedia.exceptions.DisambiguationError as e: # if multiple topics matches the same keyword
        return ""
    except Exception:
        return ""
    


def extract_wiki_keyword(title: str) -> str:
    """AI pulls the core entity: 'CRISPR shreds cancer cells' -> 'CRISPR'."""
    prompt = f"""Extract the single most important search term from this headline.
Respond with ONLY the term (1-3 words), nothing else.

Headline: {title}

Search term:"""
    try:
        resp = ollama.generate(model="phi3.5", prompt=prompt, stream=False,
                               options={"temperature": 0.1})
        kw = resp["response"].strip().strip('"').split("\n")[0].strip()
        
        if 0 < len(kw) <= 40:
            return kw       # keyword looks valid → use it
        else:
            return title    # keyword broken → fall back to the full title
        
    except Exception:
        return title



# source 2 : duckduckgo news search

def ddg_search_background(topic: str, max_results: int = 5) -> list:
    """Search DDG news for raw background snippets. No filtering —
    relevance is judged later by the content-anchored synthesizer."""
    snippets = []
    try:
        with DDGS(timeout=10) as ddgs:
            for r in ddgs.news(topic, max_results=max_results):
                snippets.append({
                    "title":  r.get("title", ""),
                    "body":   r.get("body", ""),
                    "source": r.get("source", ""),
                    "date":   r.get("date", ""),
                })
    except Exception as e:
        print(f"[ddg] error for '{topic}': {e}")

    time.sleep(2)   # rate-limit protection — CRITICAL, don't remove
    return snippets   # raw snippets — relevance is the synthesizer's job now








# this function summarises the trend news in 7-10 sentences for backstory about the trend using local ollama
def synthesize_background(topic: str, content: str, snippets: list) -> str:
    if not snippets and not content:
        return ""

    snippet_text = "\n\n".join(
        f"[{s['source']} | {s['date']}]\n{s['title']}\n{s['body']}"
        for s in snippets
    ) if snippets else f"(no snippets available — search for background on: {topic})"

    # ── ROUTING DECISION ─────────────────────────────────────────────────
    # Route to groq/compound when snippets are scarce:
    #   compound has built-in web search → fills the gap itself
    # Route to llama3.1:8b when we already HAVE rich snippet data:
    #   8B synthesises well from existing material, no search needed
    #   AND large payloads (big content + many snippets) avoid 413
    
    has_real_snippets = len(snippets) >= 2   # at least 2 real snippets
    snippet_chars = len(snippet_text)
    use_cloud = not has_real_snippets and snippet_chars < 200
    
    print(f"  [synth] {len(snippets)} snippets, {snippet_chars} snippet chars "
          f"→ {'groq/compound (will search)' if use_cloud else 'llama3.1:8b'}")

    if use_cloud:
        result = _synthesize_grokapi_cloud(content, snippet_text)
        if result:
            return result
        print(f"  [synth] compound empty/failed → local 8B fallback")

    return _synthesize_local(content[:3500], snippet_text)



def _synthesize_grokapi_cloud(content: str, snippet_text: str) -> str:
    """Cloud synthesis for 0-snippet stories needing web search context.

    Fallback chain (small boss → big boss):
      1. groq/compound-mini  — single built-in search, 3x lighter than compound
                               designed for exactly: one search → one answer
      2. openai/gpt-oss-120b — 120B with explicit web_search tool via Responses API
                               fallback if compound-mini also fails
    """
    prompt_user = f"""Write ONE tight background paragraph (4-6 sentences, MAX 120 words).

THE ARTICLE:
{content[:1000]}

SEARCH SNIPPETS:
{snippet_text}

Rules: ONE paragraph, no headers, no invented facts.
If nothing relevant: INSUFFICIENT DATA

Background paragraph:"""

    prompt_system = (
        "You are a news researcher writing background context. "
        "Use web search ONLY to find background about the specific "
        "topic in the article. Never invent facts. Stay on-topic."
    )

    # ── OPTION A: groq/compound-mini (small boss) ─────────────────────────
    # Single built-in search per request, 3x lighter than groq/compound.
    # Designed for exactly this use case: 0-snippet story needs one search.
    try:
        resp = groq_client.chat.completions.create(
            model="groq/compound-mini",
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user",   "content": prompt_user},
            ],
            temperature=0.2,
            max_tokens=300,
        )
        raw = resp.choices[0].message.content
        print(f"  [synth] groq/compound-mini → {len(raw) if raw else 0} chars raw")
        result = _clean_synthesis(raw.strip() if raw else "")
        if result:
            return result
        print(f"  [synth] compound-mini returned empty → trying big boss")
    except Exception as e:
        print(f"  [synth] compound-mini failed ({type(e).__name__}: {e}) → trying big boss")

    # ── OPTION B: gpt-oss-120b with explicit web_search tool ──────────────
    # 120B reasoning model + browser search via Groq Responses API.
    # Already proven working in Agent 3 (credibility), now with search added.
    # Uses the Responses API (different from chat.completions).
    try:
        from openai import OpenAI
        responses_client = OpenAI(
            base_url="https://api.groq.com/api/openai/v1",
            api_key=os.getenv("GROQ_KEY")
        )
        resp = responses_client.responses.create(
            model="openai/gpt-oss-20b",
            input=f"{prompt_system}\n\n{prompt_user}",
            tools=[{"type": "web_search_preview"}],
            temperature=0.2,
        )
        raw = resp.output_text
        print(f"  [synth] gpt-oss-20b + web_search → {len(raw) if raw else 0} chars raw")
        result = _clean_synthesis(raw.strip() if raw else "")



        # ── ISSUE-7 tracker: log every real 20b firing ──────────────────
        oss20b_tracker.log_hit(
            context=content[:150],
            output=raw or "",
            success=bool(result),
        )
        # ─────────────────────────────────────────────────────────────────


        if result:
            return result
        print(f"  [synth] big boss(oss-20B) also returned empty → 8B fallback")
    except Exception as e:
        print(f"  [synth] gpt-oss-20b failed ({type(e).__name__}: {e}) → 8B fallback")



        # ── ISSUE-7 tracker: log failures too ───────────────────────────
        oss20b_tracker.log_hit(
            context=content[:150],
            output="",
            success=False,
            error=f"{type(e).__name__}: {e}",
        )
        # ─────────────────────────────────────────────────────────────────


    return ""   # both cloud options failed → caller falls through to _synthesize_local



def _synthesize_local(content: str, snippet_text: str) -> str:
    """llama3.1:8b local — no payload limit, handles large articles."""
    try:
        prompt = f"""Write ONE tight background paragraph (4-6 sentences, MAX 120 words).

THE ARTICLE:
{content}

SEARCH SNIPPETS:
{snippet_text}

Rules:
- ONE paragraph only, no headers
- Only facts from the article or snippets
- Do NOT invent specifics, numbers, model names
- If no snippets relate: INSUFFICIENT DATA

Background:"""

        resp = ollama.generate(
            model="llama3.1:8b",
            prompt=prompt,
            stream=False,
            options={"temperature": 0.2, "num_ctx": 8192},
            keep_alive=0 # ← release model from memory(memory overhead but neccesary but in mac it is faster 2-3 sec) after each call
                    # forces fresh load next call — no context bleed
        )
        result = resp["response"].strip()
        print(f"  [synth] llama3.1:8b → {len(result)} chars")
        return _clean_synthesis(result)
    except Exception as e:
        print(f"  [synth] local 8B failed ({e}) → empty")
        return ""


def _clean_synthesis(result: str) -> str:
    """Shared post-processing for both Groq and local synthesis output.
    Strips INSUFFICIENT DATA, enforces minimum length."""
    if not result:
        return ""

    # model sometimes writes text BEFORE saying INSUFFICIENT DATA — trim it
    upper = result.upper()
    if upper.startswith("INSUFFICIENT DATA"):
        return ""
    if "INSUFFICIENT DATA" in upper:
        idx = upper.find("INSUFFICIENT DATA")
        result = result[:idx].strip()

    print(f"Result After Background Syntezing is : {result}")
    return result if len(result) > 100 else ""



# to run both function a wrapper function is been used
def fetch_trend_background(topic: str, content: str) -> str:
    """Full pipeline: gather snippets (DDG + Wikipedia) →
    one content-anchored ollama synthesis."""

    print(f"  [background] gathering snippets for: {topic}")

    snippets = []

    # source 1 — DDG news (raw, no filter)
    ddg= ddg_search_background(topic)
    print(f"  [bg] DDG returned {len(ddg)} snippets")
    snippets+=ddg

    # source 2 — Wikipedia (via AI-extracted keyword)
    wiki = fetch_wiki_background(topic)
    if wiki:
        print(f"  [bg] Wikipedia search returns: {len(wiki)} chars")
        snippets.append({
            "source": "Wikipedia", "date": "",
            "title": topic, "body": wiki
        })
    else:
        print(f"  [bg] Wikipedia search returns: empty (skipped)")

    print(f"  [background] {len(snippets)} snippets, synthesizing (content-anchored)...")
    result=synthesize_background(topic, content, snippets)
    
    status = f"{len(result)} chars" if result else "EMPTY-No Data"
    print(f"  [bg] background: {status}")
    return result



# DONE: [1] fetch_wiki_background — use extract_wiki_keyword, drop options[0]
# DONE: [2] ddg_search_background — delete matches() filter, return raw snippets
# DONE: [3] synthesize_background — anchor on content, change signature
# DONE: [4] fetch_trend_background — wire DDG + Wikipedia into one list

# DONE: [5] content fetch returns page chrome not article (Steam = language menu)
#           → add looks_like_real_content() gate, reject junk, try next tier
# DONE: [6] phi3.5 garbles specifics (invented "4.86GHz / June 12th")
#           → add anti-invention prompt rule + test qwen2.5:3b vs phi3.5