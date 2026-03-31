"""Hansard API collector — uses typed contribution endpoints for bulk retrieval."""

import asyncio
import hashlib
import logging
from datetime import datetime
from urllib.parse import urlencode

import httpx

from utils.retry import retry_async_call

log = logging.getLogger(__name__)

# Typed endpoints return full result sets (unlike /search.json which caps at 4 per type)
SPOKEN_URL = "https://hansard-api.parliament.uk/search/contributions/Spoken.json"
WRITTEN_URL = "https://hansard-api.parliament.uk/search/contributions/Written.json"
REDIRECT_URL = "https://hansard-api.parliament.uk/search/parlisearchredirect.json"

# Section 4.5 of monitoring briefing — broadened search terms
SEARCH_TERMS = [
    # Client-specific
    "RWE",
    # Policy areas
    "offshore wind", "onshore wind",
    "energy security", "energy prices", "energy bills",
    "clean power", "net zero",
    "CfD", "Contracts for Difference",
    "NESO", "Ofgem", "DESNZ",
    "grid connection", "Great British Energy",
    "Crown Estate", "REMA",
    "CCUS", "carbon capture",
    "capacity market",
    "planning reform",
    "energy resilience",
    # Political context
    "energy crisis",
    "energy statement",
    # Ministers (Section 4.5)
    "Ed Miliband",
    "Michael Shanks",
    "Sarah Jones",
]


def _fingerprint(url: str, title: str) -> str:
    raw = f"{url}:{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


async def _resolve_url(client: httpx.AsyncClient, ext_id: str) -> str:
    """Resolve a ContributionExtId to a full Hansard URL."""
    if not ext_id:
        return ""
    try:
        resp = await retry_async_call(client.get, REDIRECT_URL, params={"externalId": ext_id})
        if resp.status_code == 200:
            path = resp.text.strip().strip('"')
            return f"https://hansard.parliament.uk{path}"
    except Exception:
        pass
    return ""


def _extract_item(result: dict, keyword: str, resolved_url: str = "") -> dict:
    """Extract a RawItem dict from a Hansard contribution result."""
    # Use debate section as title, member name as fallback
    title = result.get("DebateSection") or result.get("MemberName") or ""
    member = result.get("AttributedTo") or result.get("MemberName") or ""
    if member and title:
        title = f"{title} — {member}"

    date_str = result.get("SittingDate") or ""
    if date_str and "T" in date_str:
        date_str = date_str.split("T")[0]

    url = resolved_url or ""
    house = result.get("House") or ""
    section = result.get("Section") or ""
    source_name = f"Hansard, {house}" if house else "Hansard"
    if section:
        source_name = f"Hansard, {section}"

    # Use full contribution text if available, fall back to snippet
    content = result.get("ContributionTextFull") or result.get("ContributionText") or ""
    content = content[:1000]

    return {
        "source_type": "hansard",
        "title": title,
        "date": date_str,
        "url": url,
        "content": content,
        "source_name": source_name,
        "keywords_matched": [keyword],
        "relevance_score": 0.0,
        "verified": True,
        "fingerprint": _fingerprint(url or title, title),
    }


async def _search_endpoint(
    client: httpx.AsyncClient,
    url: str,
    term: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Search a single Hansard contributions endpoint."""
    items = []
    try:
        params = {
            "searchTerm": term,
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d"),
            "take": 50,
        }
        log.info(f"Hansard request: {url}?{urlencode(params)}")

        resp = await retry_async_call(client.get, url, params=params)
        log.info(f"Hansard '{term}': HTTP {resp.status_code}")

        if resp.status_code in (404, 422, 500, 502, 503):
            log.debug(f"Hansard {resp.status_code} for '{term}' at {url}")
            if resp.status_code != 404:
                log.error(f"Hansard API error: {resp.text[:300]}")
            return []

        resp.raise_for_status()
        data = resp.json()

        results = data.get("Results") or data.get("results") or []
        if not isinstance(results, list):
            log.warning(f"Hansard '{term}': unexpected results type: {type(results)}")
            return []

        log.info(f"Hansard '{term}': {len(results)} results")

        for r in results:
            # Resolve URL from ContributionExtId
            ext_id = r.get("ContributionExtId", "")
            resolved_url = await _resolve_url(client, ext_id)
            items.append(_extract_item(r, term, resolved_url))

    except httpx.HTTPStatusError as e:
        log.warning(f"Hansard HTTP error for '{term}': {e}")
    except Exception as e:
        log.warning(f"Hansard error for '{term}': {e}")

    return items


async def collect(
    client: httpx.AsyncClient,
    config: dict,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Collect items from Hansard API for the reporting period."""
    items = []

    for term in SEARCH_TERMS:
        # Search both Spoken and Written contributions
        spoken = await _search_endpoint(client, SPOKEN_URL, term, start, end)
        items.extend(spoken)
        await asyncio.sleep(0.3)

        written = await _search_endpoint(client, WRITTEN_URL, term, start, end)
        items.extend(written)
        await asyncio.sleep(0.3)

    log.info(f"Hansard: collected {len(items)} items across {len(SEARCH_TERMS)} terms")
    return items
