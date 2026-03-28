"""Hansard API collector."""

import asyncio
import hashlib
import logging
from datetime import datetime

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://hansard-api.parliament.uk/search.json"

SEARCH_TERMS = [
    "RWE", "offshore wind", "energy security", "clean power",
    "CfD", "Contracts for Difference", "NESO", "Ofgem", "DESNZ",
    "grid connection", "Great British Energy", "Crown Estate",
    "REMA", "CCUS", "wind farm", "renewable energy",
]


def _fingerprint(url: str, title: str) -> str:
    """Generate a 12-char dedup hash."""
    raw = f"{url}:{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def _extract_item(result: dict, keyword: str) -> dict:
    """Extract a RawItem dict from a Hansard API result."""
    title = result.get("Title") or result.get("MemberName") or ""
    date_str = result.get("Date") or result.get("SittingDate") or ""
    if date_str and "T" in date_str:
        date_str = date_str.split("T")[0]

    url = result.get("Url") or result.get("Link") or ""
    if url and not url.startswith("http"):
        url = f"https://hansard.parliament.uk{url}"

    content = result.get("SearchResultText") or result.get("Text") or ""
    content = content[:1000]

    return {
        "source_type": "hansard",
        "title": title,
        "date": date_str,
        "url": url,
        "content": content,
        "source_name": "Hansard",
        "keywords_matched": [keyword],
        "relevance_score": 0.0,  # Set by scorer
        "verified": True,  # API source, auto-verified
        "fingerprint": _fingerprint(url, title),
    }


async def collect(
    client: httpx.AsyncClient,
    config: dict,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Collect items from Hansard API for the reporting period."""
    items = []

    for term in SEARCH_TERMS:
        try:
            params = {
                "searchTerm": term,
                "startDate": start.strftime("%Y-%m-%d"),
                "endDate": end.strftime("%Y-%m-%d"),
            }
            resp = await client.get(BASE_URL, params=params)

            if resp.status_code in (404, 500, 502, 503):
                log.warning(f"Hansard API {resp.status_code} for '{term}'")
                await asyncio.sleep(0.5)
                continue

            resp.raise_for_status()
            data = resp.json()

            results = data.get("Results") or data.get("results") or []
            if isinstance(results, list):
                for r in results:
                    items.append(_extract_item(r, term))

            log.debug(f"Hansard '{term}': {len(results)} results")

        except httpx.HTTPStatusError as e:
            log.warning(f"Hansard HTTP error for '{term}': {e}")
        except Exception as e:
            log.warning(f"Hansard error for '{term}': {e}")

        await asyncio.sleep(0.5)  # Rate limit

    log.info(f"Hansard: collected {len(items)} items across {len(SEARCH_TERMS)} terms")
    return items
