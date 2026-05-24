# agents/browser.py
#
# AGENT 0.5 — BROWSER / WEB RESEARCH ENRICHMENT
# ══════════════════════════════════════════════
# Runs BEFORE the Analyzer when input looks like a topic/question.
# Searches the web, fetches relevant pages, extracts structured facts,
# and returns enriched text = (original input) + (web-gathered facts).
#
# The Analyzer then processes this richer corpus instead of just the
# short topic text — producing far more specific, data-rich slide plans.
#
# Flow:
#   1. Detect if input is a topic (< BROWSER_TOPIC_MAX_CHARS, not structured data)
#   2. LLM generates 4-6 focused search queries
#   3. DuckDuckGo search → top results (no API key required)
#   4. Fetch each URL (requests + BeautifulSoup; Playwright fallback for JS pages)
#   5. LLM extracts facts/stats/entities from each page
#   6. Format and append web facts to original input
#
# Enable:  Set BROWSER_ENABLED=true in your .env
# Control: BROWSER_MAX_PAGES, BROWSER_MAX_CHARS_PER_PAGE in .env or config.py

import json, re, sys, time
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.llm import call_json
import config


# ══════════════════════════════════════════════════════════════════
#  STRUCTURED-DATA PATTERNS — skip browser enrichment for these
# ══════════════════════════════════════════════════════════════════

_DATA_PATTERNS = [
    re.compile(r'^\s*[\[\{]', re.MULTILINE),                   # JSON/array
    re.compile(r'^\w+,\w+,\w+', re.MULTILINE),                 # CSV-like
    re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'),       # ISO timestamps (logs)
    re.compile(r'(ERROR|WARN|INFO|DEBUG|CRITICAL)\s*[\|:]'),    # log lines
    re.compile(r'^\s*\|\s*\w+\s*\|', re.MULTILINE),            # markdown tables
    re.compile(r'level=\w+\s+msg='),                            # structured log
    re.compile(r'cpu[_\s]usage|memory[_\s]usage', re.I),        # metrics
]


def _is_topic_input(raw: str) -> bool:
    """
    Returns True when the input looks like a topic/question that would
    benefit from web research rather than structured data that already
    contains the content to present.
    """
    stripped = raw.strip()
    if len(stripped) > getattr(config, 'BROWSER_TOPIC_MAX_CHARS', 3000):
        return False
    # Check for structured data signals
    for pattern in _DATA_PATTERNS:
        if pattern.search(stripped[:2000]):
            return False
    # Must contain at least 3 words and look like prose / a question
    words = stripped.split()
    if len(words) < 3:
        return False
    return True


# ══════════════════════════════════════════════════════════════════
#  PROMPTS
# ══════════════════════════════════════════════════════════════════

_QUERY_PROMPT = """You are a research librarian generating web search queries.

TOPIC / REQUEST:
{topic}

Generate 4–6 focused search queries to find:
  1. Current statistics and hard numbers about this topic
  2. Recent developments (2023–2025)
  3. Expert analysis, authoritative guides, or academic summaries
  4. Key entities, companies, tools, or frameworks involved
  5. Common challenges, risks, or best practices (where relevant)

Rules:
  - Each query is specific and short (3–8 words)
  - Vary the angle — don't just rephrase the same query
  - Include year terms (2024 or 2025) in at least one query for recency
  - For exam/certification topics: include syllabus, pass rate, study resources

Return ONLY JSON:
{{
  "queries": ["query 1", "query 2", "query 3", "query 4", "query 5"],
  "topic_summary": "One sentence capturing exactly what this topic is about"
}}"""


_EXTRACT_PROMPT = """You are a research analyst extracting structured knowledge from a web page.

RESEARCH TOPIC: {topic}
SOURCE URL: {url}

PAGE CONTENT:
{content}

Extract ONLY information relevant to the topic. Be specific — real numbers, real names, real dates.

Return ONLY JSON:
{{
  "facts": [
    "Specific fact with numbers/names — e.g.: CFA Level 1 pass rate dropped to 37% in 2023"
  ],
  "statistics": [
    {{"metric": "metric name", "value": "exact value", "context": "what this means / why it matters"}}
  ],
  "entities": ["Named people, companies, tools, standards, frameworks mentioned"],
  "timeline_events": [
    {{"date": "year or date", "event": "what happened"}}
  ],
  "key_insights": [
    "Insight sentence — explain the WHY, not just the WHAT"
  ],
  "source_quality": "high"
}}

Rules:
  - Return empty arrays if content is irrelevant to the topic
  - source_quality: high (authoritative/official) | medium (blog/secondary) | low (forum/opinion)
  - facts must be specific — no generic statements like "XYZ is important"
  - If page has no useful content (ads, error, login wall), return all empty arrays"""


# ══════════════════════════════════════════════════════════════════
#  SEARCH — DuckDuckGo (no API key required)
# ══════════════════════════════════════════════════════════════════

def _ddg_search(queries: list[str], max_results: int = 8) -> list[dict]:
    """
    Search using DuckDuckGo. Returns list of {title, url, snippet}.
    Falls back to empty list if duckduckgo_search not installed.
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        print("  [Browser] duckduckgo-search not installed — run: pip install duckduckgo-search")
        return []

    seen_urls: set[str] = set()
    results: list[dict] = []

    # Blacklist — low-quality or paywalled domains
    _SKIP_DOMAINS = {
        'reddit.com', 'quora.com', 'pinterest.com', 'facebook.com',
        'twitter.com', 'x.com', 'instagram.com', 'youtube.com',
        'amazon.com', 'ebay.com',
    }

    with DDGS() as ddgs:
        for query in queries:
            try:
                for r in ddgs.text(query, max_results=4):
                    url = r.get('href') or r.get('url', '')
                    if not url or url in seen_urls:
                        continue
                    domain = re.sub(r'^www\.', '', url.split('/')[2].lower() if '//' in url else '')
                    if any(bad in domain for bad in _SKIP_DOMAINS):
                        continue
                    seen_urls.add(url)
                    results.append({
                        'title':   r.get('title', ''),
                        'url':     url,
                        'snippet': r.get('body', '')[:400],
                    })
                    if len(results) >= max_results:
                        break
                time.sleep(0.4)  # polite delay between queries
            except Exception as e:
                print(f"  [Browser] Search query failed ({query[:40]}): {e}")
                continue
            if len(results) >= max_results:
                break

    return results


# ══════════════════════════════════════════════════════════════════
#  FETCH + PARSE
# ══════════════════════════════════════════════════════════════════

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

# Tags that never contain useful prose text
_STRIP_TAGS = {
    'script', 'style', 'noscript', 'iframe', 'nav', 'header', 'footer',
    'aside', 'form', 'button', 'input', 'select', 'textarea',
    'advertisement', 'figure',
}

# CSS classes / IDs that are usually navigation / ads
_STRIP_CLASS_PATTERNS = re.compile(
    r'nav|menu|sidebar|footer|header|cookie|banner|ad-|popup|modal|subscribe',
    re.IGNORECASE,
)


def _fetch_url(url: str, max_chars: int = 8000, timeout: int = 10) -> Optional[str]:
    """
    Fetch a URL and return clean plain text.
    Returns None on error or if content appears empty / login-walled.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("  [Browser] requests/beautifulsoup4 not installed — "
              "run: pip install requests beautifulsoup4 lxml")
        return None

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get('Content-Type', '')
        if 'text/html' not in content_type and 'text/plain' not in content_type:
            return None
    except Exception as e:
        print(f"  [Browser] Fetch failed ({url[:60]}): {type(e).__name__}")
        return None

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.content, 'lxml')
    except Exception:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.content, 'html.parser')
        except Exception as e:
            print(f"  [Browser] Parse failed ({url[:60]}): {e}")
            return None

    # Remove noisy tags
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    # Remove noisy elements by class/id pattern
    for tag in soup.find_all(True):
        cls = ' '.join(tag.get('class', []))
        tid = tag.get('id', '')
        if _STRIP_CLASS_PATTERNS.search(cls) or _STRIP_CLASS_PATTERNS.search(tid):
            tag.decompose()

    # Extract text from content-bearing tags
    content_tags = soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'li', 'td', 'th', 'article', 'section', 'main'])
    lines = []
    for tag in content_tags:
        txt = tag.get_text(separator=' ', strip=True)
        if len(txt) > 30:  # skip very short snippets (labels, UI text)
            lines.append(txt)

    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    if len(text) < 100:
        return None  # likely a login wall or empty page

    return text[:max_chars]


# ══════════════════════════════════════════════════════════════════
#  PER-PAGE FACT EXTRACTION
# ══════════════════════════════════════════════════════════════════

def _extract_facts(page_text: str, topic: str, url: str) -> Optional[dict]:
    """LLM extracts structured facts from one page."""
    max_page = getattr(config, 'BROWSER_MAX_CHARS_PER_PAGE', 8000)
    try:
        result = call_json(
            _EXTRACT_PROMPT.format(
                topic   = topic[:300],
                url     = url,
                content = page_text[:max_page],
            ),
            key        = "analyzer",   # reuse analyzer model / key
            max_tokens = 2000,
        )
        return result
    except Exception as e:
        print(f"  [Browser] Extraction LLM failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
#  RESULT FORMATTER
# ══════════════════════════════════════════════════════════════════

def _format_web_research(topic_summary: str, extractions: list[dict], search_results: list[dict]) -> str:
    """
    Format the collected web research into a structured text block
    that the Analyzer can treat as supplementary source material.
    """
    sections = [
        f"=== WEB RESEARCH SUPPLEMENT ===",
        f"Topic: {topic_summary}",
        f"Sources searched: {len(search_results)} | Pages analysed: {len(extractions)}",
        "",
    ]

    # Aggregate all facts, stats, entities, insights across pages
    all_facts:    list[str]  = []
    all_stats:    list[dict] = []
    all_entities: list[str]  = []
    all_insights: list[str]  = []
    all_timeline: list[dict] = []

    for ext in extractions:
        if not ext:
            continue
        quality = ext.get('source_quality', 'low')
        if quality == 'low':
            continue  # skip forum / opinion sources
        all_facts.extend(ext.get('facts', []))
        all_stats.extend(ext.get('statistics', []))
        all_entities.extend(ext.get('entities', []))
        all_insights.extend(ext.get('key_insights', []))
        all_timeline.extend(ext.get('timeline_events', []))

    # Deduplicate entities
    seen_e: set[str] = set()
    unique_entities = []
    for e in all_entities:
        key = e.lower().strip()
        if key and key not in seen_e:
            seen_e.add(key)
            unique_entities.append(e)

    if all_facts:
        sections.append("--- KEY FACTS ---")
        for f in all_facts[:30]:
            sections.append(f"• {f}")
        sections.append("")

    if all_stats:
        sections.append("--- STATISTICS & METRICS ---")
        for s in all_stats[:20]:
            metric  = s.get('metric', '')
            value   = s.get('value', '')
            context = s.get('context', '')
            if metric and value:
                sections.append(f"• {metric}: {value}{' — ' + context if context else ''}")
        sections.append("")

    if unique_entities:
        sections.append("--- KEY ENTITIES ---")
        sections.append(", ".join(unique_entities[:30]))
        sections.append("")

    if all_timeline:
        sections.append("--- TIMELINE ---")
        for ev in sorted(all_timeline, key=lambda x: str(x.get('date', '')))[:15]:
            sections.append(f"• {ev.get('date', '?')}: {ev.get('event', '')}")
        sections.append("")

    if all_insights:
        sections.append("--- KEY INSIGHTS ---")
        for ins in all_insights[:15]:
            sections.append(f"• {ins}")
        sections.append("")

    # Snippet references
    sections.append("--- SOURCE SNIPPETS ---")
    for sr in search_results[:6]:
        if sr.get('snippet'):
            sections.append(f"[{sr['title'][:60]}] {sr['snippet'][:200]}")
    sections.append("")
    sections.append("=== END WEB RESEARCH ===")

    return "\n".join(sections)


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def run(raw_data: str) -> str:
    """
    Enrich raw_data with web research if it looks like a topic/question.

    Returns:
        Augmented string = original input + web research block.
        If skipped (structured data input / disabled / errors), returns
        original raw_data unchanged.
    """
    if not getattr(config, 'BROWSER_ENABLED', False):
        return raw_data

    if not _is_topic_input(raw_data):
        print("  [Browser] Input looks like structured data — skipping web enrichment")
        return raw_data

    topic = raw_data.strip()
    print(f"  [Browser] Topic input detected ({len(topic)} chars) — starting web research...")

    # ── Step 1: Generate search queries ───────────────────────────
    print("  [Browser] Generating search queries...")
    try:
        query_result = call_json(
            _QUERY_PROMPT.format(topic=topic[:800]),
            key        = "analyzer",
            max_tokens = 600,
        )
        queries       = query_result.get('queries', [])[:6]
        topic_summary = query_result.get('topic_summary', topic[:120])
    except Exception as e:
        print(f"  [Browser] Query generation failed: {e} — aborting enrichment")
        return raw_data

    if not queries:
        print("  [Browser] No queries generated — aborting enrichment")
        return raw_data

    print(f"  [Browser] Generated {len(queries)} queries:")
    for q in queries:
        print(f"    - {q}")

    # ── Step 2: Search ─────────────────────────────────────────────
    max_pages = getattr(config, 'BROWSER_MAX_PAGES', 5)
    print(f"  [Browser] Searching (max {max_pages} pages)...")
    search_results = _ddg_search(queries, max_results=max_pages + 3)

    if not search_results:
        print("  [Browser] No search results — aborting enrichment")
        return raw_data

    print(f"  [Browser] Found {len(search_results)} candidate URLs")

    # ── Step 3: Fetch + Extract ────────────────────────────────────
    max_chars_per_page = getattr(config, 'BROWSER_MAX_CHARS_PER_PAGE', 8000)
    extractions: list[dict] = []
    fetched = 0

    for sr in search_results:
        if fetched >= max_pages:
            break
        url = sr['url']
        print(f"  [Browser] [{fetched+1}/{max_pages}] Fetching: {url[:70]}")

        page_text = _fetch_url(url, max_chars=max_chars_per_page)
        if not page_text:
            print(f"  [Browser]   -> Empty or unreachable")
            continue

        print(f"  [Browser]   -> {len(page_text):,} chars — extracting facts...")
        ext = _extract_facts(page_text, topic_summary, url)
        if ext:
            n_facts    = len(ext.get('facts', []))
            n_stats    = len(ext.get('statistics', []))
            n_insights = len(ext.get('key_insights', []))
            quality    = ext.get('source_quality', '?')
            print(f"  [Browser]   -> {n_facts} facts, {n_stats} stats, {n_insights} insights [{quality}]")
            if quality != 'low':
                extractions.append(ext)
        fetched += 1
        time.sleep(0.3)

    if not extractions:
        print("  [Browser] No usable extractions — returning original input")
        return raw_data

    # ── Step 4: Format and merge ───────────────────────────────────
    web_block = _format_web_research(topic_summary, extractions, search_results)

    total_facts    = sum(len(e.get('facts', []))       for e in extractions)
    total_stats    = sum(len(e.get('statistics', []))  for e in extractions)
    total_insights = sum(len(e.get('key_insights', [])) for e in extractions)

    print(
        f"  [Browser] Done — {total_facts} facts, {total_stats} stats, "
        f"{total_insights} insights from {len(extractions)} pages"
    )

    enriched = f"{raw_data.strip()}\n\n{web_block}"
    return enriched
