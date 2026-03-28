"""Claude web search collector for sources without APIs."""

import hashlib
import json
import logging
import re
from datetime import datetime

import anthropic

log = logging.getLogger(__name__)


def _fingerprint(url: str, title: str) -> str:
    raw = f"{url}:{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def _build_queries(config: dict, start: datetime) -> list[str]:
    """Build search queries from client config."""
    month_year = start.strftime("%B %Y")
    year = start.strftime("%Y")
    client_name = config["client"]["name"]

    return [
        f"{client_name} UK {month_year}",
        f"Sofia offshore wind farm {year}",
        f"Norfolk Vanguard offshore wind {year}",
        f"DESNZ energy policy {month_year}",
        f"UK offshore wind allocation round {year}",
        f"Great British Energy investment fund {year}",
        f"Crown Estate seabed leasing offshore wind {year}",
        f"REMA reformed national pricing UK {year}",
        f"Ofgem consultation energy {month_year}",
        f"NESO strategic spatial energy plan {year}",
        f"Orsted SSE Equinor UK offshore wind {month_year}",
        f"UK energy security resilience {month_year}",
        f"RenewableUK Energy UK offshore wind {month_year}",
        f"offshore wind supply chain UK {month_year}",
        f"CCUS carbon capture UK {year}",
    ]


def _parse_response(response, query: str) -> list[dict]:
    """Extract structured items from Claude's response."""
    items = []

    # Get text content from response
    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    if not text.strip():
        return items

    # Strip markdown code fences
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()

    try:
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            parsed = [parsed]

        for entry in parsed:
            if not isinstance(entry, dict):
                continue

            title = entry.get("title", "")
            url = entry.get("url", "")
            date = entry.get("date", "")
            snippet = (entry.get("snippet") or entry.get("description") or "")[:1000]
            source_name = entry.get("source_name") or entry.get("source") or "Web"

            if not title and not url:
                continue

            items.append({
                "source_type": "web",
                "title": title,
                "date": date,
                "url": url,
                "content": snippet,
                "source_name": source_name,
                "keywords_matched": [query],
                "relevance_score": 0.0,
                "verified": False,  # Needs verification
                "fingerprint": _fingerprint(url, title),
            })

    except json.JSONDecodeError:
        log.warning(f"Failed to parse JSON for query: {query}")

    return items


def collect(
    anthropic_client: anthropic.Anthropic,
    config: dict,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Collect items via Claude web search."""
    queries = _build_queries(config, start)
    items = []

    for query in queries:
        try:
            response = anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
                messages=[{
                    "role": "user",
                    "content": (
                        f"Search for: {query}\n\n"
                        "Return a JSON array of the most relevant results from the past 2 weeks. "
                        "Each object: {title, date, url, snippet, source_name}. "
                        "Return ONLY the JSON array, no other text."
                    ),
                }],
            )

            parsed = _parse_response(response, query)
            items.extend(parsed)
            log.debug(f"Web search '{query}': {len(parsed)} items")

        except anthropic.APIError as e:
            log.warning(f"Anthropic API error for '{query}': {e}")
        except Exception as e:
            log.warning(f"Web search error for '{query}': {e}")

    log.info(f"Web search: collected {len(items)} items across {len(queries)} queries")
    return items
