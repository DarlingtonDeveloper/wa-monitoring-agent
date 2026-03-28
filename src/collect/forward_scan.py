"""Forward scan collector — future events for Forward Look section."""

import hashlib
import json
import logging
import re
from datetime import datetime

import anthropic

from utils.retry import retry_api_call

log = logging.getLogger(__name__)

FORWARD_QUERIES = [
    "UK energy consultation deadline upcoming 2026",
    "parliamentary calendar energy committee session upcoming",
    "offshore wind industry conference UK 2026",
    "CfD allocation round 8 AR8 timeline 2026",
    "SSEP strategic spatial energy plan publication date",
    "Great British Energy investment fund launch date",
    "Norfolk Vanguard FID final investment decision date",
    "Crown Estate leasing round timeline",
    "Ofgem RIIO consultation deadline",
]


def _fingerprint(url: str, title: str) -> str:
    raw = f"{url}:{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def _parse_response(response, query: str) -> list[dict]:
    """Extract structured items from Claude's response."""
    items = []

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    if not text.strip():
        return items

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

            title = entry.get("title") or entry.get("event") or ""
            url = entry.get("url", "")
            date = entry.get("date", "")
            snippet = (entry.get("snippet") or entry.get("description") or entry.get("relevance") or "")[:1000]
            source_name = entry.get("source_name") or entry.get("source") or "Web"

            if not title:
                continue

            items.append({
                "source_type": "forward_scan",
                "title": title,
                "date": date,
                "url": url or "",
                "content": snippet,
                "source_name": source_name,
                "keywords_matched": [query],
                "relevance_score": 0.0,
                "verified": False,
                "fingerprint": _fingerprint(url or title, title),
            })

    except json.JSONDecodeError:
        log.warning(f"Failed to parse JSON for forward query: {query}")

    return items


def collect(
    anthropic_client: anthropic.Anthropic,
    config: dict,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Collect future events via Claude web search."""
    items = []

    for query in FORWARD_QUERIES:
        try:
            response = retry_api_call(
                anthropic_client.messages.create,
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
                messages=[{
                    "role": "user",
                    "content": (
                        f"Search for: {query}\n\n"
                        "Return a JSON array of upcoming events, deadlines, or milestones. "
                        "Each object: {title, date, url, snippet, source_name}. "
                        "Focus on future dates. Return ONLY the JSON array, no other text."
                    ),
                }],
            )

            parsed = _parse_response(response, query)
            items.extend(parsed)
            log.debug(f"Forward scan '{query}': {len(parsed)} items")

        except anthropic.APIError as e:
            log.warning(f"Anthropic API error for forward '{query}': {e}")
        except Exception as e:
            log.warning(f"Forward scan error for '{query}': {e}")

    log.info(f"Forward scan: collected {len(items)} items across {len(FORWARD_QUERIES)} queries")
    return items
