"""Claude web search collector — two-pass approach for richer source content.

Pass 1: Claude web search to find URLs and snippets.
Pass 2: Fetch top pages, ask Claude to extract detailed findings from full text.

Expanded to 14 theme queries per Section 10 of V7 spec.
"""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta

import anthropic
import httpx
from bs4 import BeautifulSoup

from utils.retry import retry_api_call

log = logging.getLogger(__name__)

PASS_2_PROMPT = """You are a UK public affairs researcher extracting findings from source articles.

Below are full articles relevant to: {theme_description}
Client: {client_name}

{page_contents}

Extract every significant finding from these articles. For each finding, return:
{{
  "title": "concise headline",
  "date": "YYYY-MM-DD (only if explicitly stated in the article)",
  "url": "the source URL this finding comes from",
  "content": "200-500 word detailed summary using ONLY facts from the source text. Include specific dates, figures, names, and organisations as stated. Do NOT add context from your own knowledge.",
  "source_name": "publication name e.g. Recharge News, GOV.UK"
}}

RULES:
- Only extract facts that are explicitly stated in the article text
- Do not infer dates, numbers, or attribution not present in the source
- If a fact is ambiguous or the article is unclear, note that in the summary
- Do not add background context the article doesn't provide
- Only return results published between {start_date} and {end_date}. Do NOT return older announcements, background information, or historical context.

Return ONLY a JSON array of findings."""


def _fingerprint(url: str, title: str) -> str:
    raw = f"{url}:{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def _build_theme_queries(config: dict, week_start: datetime) -> dict[str, dict]:
    """Build search queries per monitoring theme — 14 themes for full coverage."""
    client_name = config["client"]["name"]
    month_year = week_start.strftime("%B %Y")
    start = week_start.strftime("%d %B %Y")
    end = (week_start + timedelta(days=6)).strftime("%d %B %Y")

    return {
        # Existing themes (improved)
        "policy_government": {
            "query": f"UK government energy policy DESNZ announcement {month_year}",
            "description": (
                "UK government energy policy. DESNZ announcements, CfD rounds, "
                "Clean Power 2030, energy security, consultations."
            ),
        },
        "parliamentary": {
            "query": f"UK Parliament energy debate question committee {month_year}",
            "description": (
                "UK parliamentary activity. Debates, questions, "
                "committee hearings, EDMs."
            ),
        },
        "regulatory_legal": {
            "query": f"Ofgem NESO Crown Estate grid connection offshore wind {month_year}",
            "description": (
                "Regulatory developments. Ofgem decisions, NESO announcements, "
                "Crown Estate leasing, planning decisions."
            ),
        },
        "media_coverage": {
            "query": f"{client_name} offshore wind UK news {month_year}",
            "description": (
                f"Media coverage of {client_name} and UK offshore wind sector."
            ),
        },
        "competitor_industry": {
            "query": f"Ørsted SSE Equinor ScottishPower UK offshore wind {month_year}",
            "description": (
                "Competitor announcements and industry body publications."
            ),
        },
        "stakeholder_third_party": {
            "query": f"UK offshore wind community opposition NGO campaign {month_year}",
            "description": (
                "Stakeholder activity. NGO campaigns, community groups, union statements."
            ),
        },
        "forward_scan": {
            "query": "UK energy consultation deadline committee session offshore wind upcoming",
            "description": (
                "Upcoming events and deadlines. Consultations, committee sessions, conferences."
            ),
        },
        # NEW themes (from monitoring briefing gaps)
        "political_context": {
            "query": f"UK energy crisis government response Chancellor energy prices {month_year}",
            "description": (
                "Broader political context. Chancellor statements, energy pricing debate, "
                "crisis response, North Sea policy."
            ),
        },
        "ministers": {
            "query": f"Ed Miliband Michael Shanks energy announcement UK {month_year}",
            "description": (
                "Ministerial activity. Statements, speeches, media appearances by energy ministers."
            ),
        },
        "ofgem_specific": {
            "query": f"Ofgem consultation call for evidence charging reform {month_year}",
            "description": (
                "Ofgem publications. Consultations, calls for evidence, decisions, market reform."
            ),
        },
        "industry_reports": {
            "query": f"Energy UK RenewableUK OEUK report publication UK energy {month_year}",
            "description": (
                "Industry body reports. Energy UK, RenewableUK, OEUK publications."
            ),
        },
        "supply_chain": {
            "query": f"UK offshore wind supply chain turbine factory port investment {month_year}",
            "description": (
                "Supply chain developments. New factories, port investments, turbine orders, manufacturing."
            ),
        },
        "gas_ccus": {
            "query": f"UK carbon storage licensing CCUS CCS North Sea gas capacity market {month_year}",
            "description": (
                "Carbon storage licensing, CCUS projects, gas generation developments."
            ),
        },
        "planning_consenting": {
            "query": f"UK planning reform DCO wind farm planning inspectorate {month_year}",
            "description": (
                "Planning and consenting. DCO decisions, planning reform, NSIP applications."
            ),
        },
    }


def _parse_pass1_response(response) -> list[dict]:
    """Extract structured results from Claude's pass 1 response."""
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    if not text.strip():
        return []

    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()

    try:
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            parsed = [parsed]
        return [e for e in parsed if isinstance(e, dict)]
    except json.JSONDecodeError:
        return []


async def _fetch_page_text(url: str, http_client: httpx.AsyncClient) -> str | None:
    """Fetch a URL and extract body text with BeautifulSoup."""
    try:
        resp = await http_client.get(url, timeout=10, follow_redirects=True)
        if resp.status_code != 200:
            return None
        if "html" not in resp.headers.get("content-type", "").lower():
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup.find_all(["nav", "footer", "script", "style", "header", "aside"]):
            tag.decompose()
        main = soup.find("article") or soup.find("main") or soup.find("body")
        if main:
            text = main.get_text(separator=" ", strip=True)
            text = " ".join(text.split())
            if len(text) > 200:
                return text[:5000]
    except Exception:
        pass
    return None


async def _two_pass_search(
    theme_id: str,
    theme_query: str,
    theme_description: str,
    config: dict,
    anthropic_client: anthropic.Anthropic,
    http_client: httpx.AsyncClient,
    week_start: datetime,
) -> list[dict]:
    """
    Pass 1: Claude web search — get URLs and snippets.
    Pass 2: Fetch top pages, ask Claude to extract detailed findings.
    """
    start_date = week_start.strftime("%d %B %Y")
    end_date = (week_start + timedelta(days=6)).strftime("%d %B %Y")

    # ── Pass 1: Web search ──
    log.info(f"Pass 1 [{theme_id}]: searching '{theme_query[:60]}...'")
    try:
        response = retry_api_call(
            anthropic_client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            messages=[{
                "role": "user",
                "content": (
                    f"Search for: {theme_query}\n\n"
                    f"Only return results published between {start_date} and {end_date}. "
                    "Do NOT return older announcements, background information, or historical context.\n\n"
                    "Return a JSON array of the most relevant results from the past 14 days. "
                    "Each object: {title, date, url, snippet, source_name}. "
                    "Return ONLY the JSON array."
                ),
            }],
        )
        pass_1_results = _parse_pass1_response(response)
    except Exception as e:
        log.warning(f"Pass 1 [{theme_id}] failed: {e}")
        return []

    if not pass_1_results:
        log.info(f"Pass 1 [{theme_id}]: no results")
        return []

    log.info(f"Pass 1 [{theme_id}]: {len(pass_1_results)} results")

    # ── Fetch top URLs ──
    urls_to_fetch = []
    for r in pass_1_results[:5]:
        url = r.get("url", "")
        if url and url.startswith("http") and not url.lower().endswith(".pdf"):
            urls_to_fetch.append(url)

    if not urls_to_fetch:
        # No fetchable URLs — return pass 1 results as items
        return _pass1_to_items(pass_1_results, theme_id)

    page_contents = ""
    fetched_count = 0
    for url in urls_to_fetch:
        text = await _fetch_page_text(url, http_client)
        if text:
            page_contents += f"\n\n--- SOURCE: {url} ---\n{text}\n"
            fetched_count += 1
        await asyncio.sleep(0.3)

    if fetched_count == 0:
        log.info(f"Pass 2 [{theme_id}]: no pages fetched, using pass 1 results")
        return _pass1_to_items(pass_1_results, theme_id)

    # ── Pass 2: Extract detailed findings from full page content ──
    log.info(f"Pass 2 [{theme_id}]: extracting from {fetched_count} pages")
    try:
        response = retry_api_call(
            anthropic_client.messages.create,
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": PASS_2_PROMPT.format(
                    theme_description=theme_description,
                    client_name=config["client"]["name"],
                    page_contents=page_contents,
                    start_date=start_date,
                    end_date=end_date,
                ),
            }],
        )

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        cleaned = re.sub(r"```json\s*|```\s*", "", text).strip()
        pass_2_results = json.loads(cleaned)

        if isinstance(pass_2_results, list) and len(pass_2_results) > 0:
            log.info(f"Pass 2 [{theme_id}]: {len(pass_2_results)} detailed findings")
            return _findings_to_items(pass_2_results, theme_id)

    except (json.JSONDecodeError, Exception) as e:
        log.warning(f"Pass 2 [{theme_id}] failed: {e}, falling back to pass 1")

    return _pass1_to_items(pass_1_results, theme_id)


def _pass1_to_items(results: list[dict], theme_id: str) -> list[dict]:
    """Convert pass 1 search results to standard item dicts."""
    source_type = "forward_scan" if theme_id == "forward_scan" else "web"
    items = []
    for entry in results:
        title = entry.get("title", "")
        url = entry.get("url", "")
        if not title and not url:
            continue
        items.append({
            "source_type": source_type,
            "title": title,
            "date": entry.get("date", ""),
            "url": url,
            "content": (entry.get("snippet") or entry.get("description") or "")[:1000],
            "source_name": entry.get("source_name") or entry.get("source") or "Web",
            "keywords_matched": [theme_id],
            "relevance_score": 0.0,
            "verified": False,
            "fingerprint": _fingerprint(url, title),
        })
    return items


def _findings_to_items(results: list[dict], theme_id: str) -> list[dict]:
    """Convert pass 2 detailed findings to standard item dicts."""
    source_type = "forward_scan" if theme_id == "forward_scan" else "web"
    items = []
    for entry in results:
        title = entry.get("title", "")
        url = entry.get("url", "")
        if not title and not url:
            continue
        items.append({
            "source_type": source_type,
            "title": title,
            "date": entry.get("date", ""),
            "url": url,
            "content": (entry.get("content") or entry.get("snippet") or "")[:8000],
            "source_name": entry.get("source_name") or entry.get("source") or "Web",
            "keywords_matched": [theme_id],
            "relevance_score": 0.0,
            "verified": False,
            "content_enriched": True,
            "fingerprint": _fingerprint(url, title),
        })
    return items


BATCH_SIZE = 4
BATCH_DELAY = 45  # seconds between batches


async def collect_two_pass(
    anthropic_client: anthropic.Anthropic,
    config: dict,
    week_start: datetime,
) -> list[dict]:
    """Collect items via two-pass web search across all themes.

    Themes are processed in batches with delays between batches
    to stay within API rate limits.
    """
    theme_queries = _build_theme_queries(config, week_start)
    items = []
    themes = list(theme_queries.items())

    async with httpx.AsyncClient(
        headers={"User-Agent": "WA-Monitoring-Agent/1.0"},
        follow_redirects=True,
    ) as http_client:
        for i in range(0, len(themes), BATCH_SIZE):
            batch = themes[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            total_batches = (len(themes) + BATCH_SIZE - 1) // BATCH_SIZE
            log.info(f"Web search batch {batch_num}/{total_batches}: {[t[0] for t in batch]}")

            for theme_id, theme_config in batch:
                try:
                    results = await _two_pass_search(
                        theme_id=theme_id,
                        theme_query=theme_config["query"],
                        theme_description=theme_config["description"],
                        config=config,
                        anthropic_client=anthropic_client,
                        http_client=http_client,
                        week_start=week_start,
                    )
                    items.extend(results)
                except Exception as e:
                    log.warning(f"Two-pass search [{theme_id}] failed: {e}")
                await asyncio.sleep(2)  # small delay within batch

            if i + BATCH_SIZE < len(themes):
                log.info(f"Batch complete, waiting {BATCH_DELAY}s for rate limit cooldown...")
                await asyncio.sleep(BATCH_DELAY)

    log.info(f"Two-pass web search: collected {len(items)} items across {len(theme_queries)} themes")
    return items


# Keep the old single-pass collect for backwards compatibility
def collect(
    anthropic_client: anthropic.Anthropic,
    config: dict,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Collect items via Claude web search (single-pass, legacy)."""
    return asyncio.run(collect_two_pass(anthropic_client, config, start))
