"""GOV.UK API collector."""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://www.gov.uk/api/search.json"

SEARCH_QUERIES = [
    {"q": "offshore wind CfD", "filter_organisations[]": "department-for-energy-security-and-net-zero"},
    {"q": "DESNZ energy announcement", "filter_organisations[]": "department-for-energy-security-and-net-zero"},
    {"q": "Ofgem consultation decision"},
    {"q": "Great British Energy"},
    {"q": "REMA electricity market", "filter_organisations[]": "department-for-energy-security-and-net-zero"},
    {"q": "grid connections reform"},
    {"q": "energy resilience strategy", "filter_organisations[]": "department-for-energy-security-and-net-zero"},
    {"q": "Crown Estate seabed"},
    {"q": "NESO strategic spatial"},
    {"q": "CCUS carbon capture", "filter_organisations[]": "department-for-energy-security-and-net-zero"},
    {"q": "planning inspectorate energy"},
    {"q": "onshore wind planning"},
    {"q": "clean power 2030"},
]


def _fingerprint(url: str, title: str) -> str:
    raw = f"{url}:{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def _extract_item(result: dict, query: str) -> dict | None:
    """Extract a RawItem dict from a GOV.UK API result."""
    title = result.get("title", "")
    link = result.get("link", "")
    url = f"https://www.gov.uk{link}" if link else ""
    description = (result.get("description") or "")[:1000]

    date_str = result.get("public_timestamp", "")
    if date_str and "T" in date_str:
        date_str = date_str.split("T")[0]

    # Build source name from organisations
    orgs = result.get("organisations", [])
    if orgs and isinstance(orgs, list):
        org_names = [o.get("title", "") if isinstance(o, dict) else str(o) for o in orgs]
        source_name = f"GOV.UK {', '.join(n for n in org_names if n)}" if any(org_names) else "GOV.UK"
    else:
        source_name = "GOV.UK"

    return {
        "source_type": "govuk",
        "title": title,
        "date": date_str,
        "url": url,
        "content": description,
        "source_name": source_name,
        "keywords_matched": [query],
        "relevance_score": 0.0,
        "verified": True,
        "fingerprint": _fingerprint(url, title),
    }


async def collect(
    client: httpx.AsyncClient,
    config: dict,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Collect items from GOV.UK API, filtered to last 14 days."""
    items = []
    cutoff = datetime.now() - timedelta(days=14)

    for query_params in SEARCH_QUERIES:
        try:
            params = {
                **query_params,
                "count": 20,
                "order": "-public_timestamp",  # Newest first (NOT "most-recent" which returns 422)
            }
            resp = await client.get(BASE_URL, params=params)

            if resp.status_code in (404, 422, 500, 502, 503):
                log.warning(f"GOV.UK API {resp.status_code} for '{query_params['q']}'")
                await asyncio.sleep(0.3)
                continue

            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            for r in results:
                item = _extract_item(r, query_params["q"])
                if not item:
                    continue

                # Date filter: keep items from last 14 days
                if item["date"]:
                    try:
                        item_date = datetime.strptime(item["date"], "%Y-%m-%d")
                        if item_date < cutoff:
                            continue
                    except ValueError:
                        pass

                items.append(item)

            log.debug(f"GOV.UK '{query_params['q']}': {len(results)} results")

        except httpx.HTTPStatusError as e:
            log.warning(f"GOV.UK HTTP error for '{query_params['q']}': {e}")
        except Exception as e:
            log.warning(f"GOV.UK error for '{query_params['q']}': {e}")

        await asyncio.sleep(0.3)

    log.info(f"GOV.UK: collected {len(items)} items across {len(SEARCH_QUERIES)} queries")
    return items
