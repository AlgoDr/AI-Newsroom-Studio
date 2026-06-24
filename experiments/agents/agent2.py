import os
import dotenv

dotenv.load_dotenv(".env")



import trafilatura
import requests



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
    junk_markers = ["rate limit", "403 forbidden", "access denied",
                    "enable javascript", "captcha", "are you a robot"]
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
        import os
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
    """Ollama filters snippets against the ARTICLE CONTENT (ground truth)
    and writes one background briefing — filter + synthesis in one call."""
    if not snippets:
        return ""

    snippet_text = "\n\n".join(
        f"[{s['source']} | {s['date']}]\n{s['title']}\n{s['body']}"
        for s in snippets
    )

    prompt = f"""You are a news researcher writing a SHORT background brief.

THE ARTICLE (ground truth — the real story):
{content[:3500]}

SEARCH SNIPPETS (some may be unrelated — ignore those):
{snippet_text}

Write ONE tight paragraph (4-6 sentences, MAX 120 words) of background context
for THE ARTICLE.

Rules:
- ONE paragraph only. Do NOT repeat the same fact in different words.
- Each sentence must add NEW information.
- Use ONLY snippets about the SAME topic as THE ARTICLE; ignore off-topic ones.
- Treat all dates/facts as real. No disclaimers about dates or your knowledge.
- No labels, headers, or bullet points — just the paragraph.
- If NO snippets relate, respond with ONLY: INSUFFICIENT DATA
- Do NOT invent specific numbers, dates, or specs. Only state facts that appear in THE ARTICLE or the snippets. If unsure, stay general.

Background:"""

    try:
        resp = ollama.generate(
            model="qwen2.5:3b",
            prompt=prompt,
            stream=False,
            options={"temperature": 0.2}
        )
        result = resp['response'].strip()

        print(f"Result After Background Syntezing is : {result}")

        if result.upper().startswith("INSUFFICIENT DATA"):
            return ""

        if "INSUFFICIENT DATA" in result.upper():
            idx = result.upper().find("INSUFFICIENT DATA")
            result = result[:idx].strip()

        return result if len(result) > 100 else ""

    except Exception as e:
        print(f"[ollama] synthesis failed: {e}")
        return ""



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