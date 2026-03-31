"""GOV.UK Atom feed collector — replaces search API.

GOV.UK's search API returns the same generic pages for every query.
Atom feeds list every new publication chronologically per department/topic.
No relevance ranking to fight, no duplicates, deterministic.
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta

import feedparser
import httpx

log = logging.getLogger(__name__)

# GOV.UK Atom feeds — one per department/topic relevant to client
GOVUK_FEEDS = [
    # DESNZ — all publications
    "https://www.gov.uk/government/organisations/department-for-energy-security-and-net-zero.atom",

    # Ofgem
    "https://www.gov.uk/government/organisations/ofgem.atom",

    # Planning Inspectorate
    "https://www.gov.uk/government/organisations/planning-inspectorate.atom",

    # CMA
    "https://www.gov.uk/government/organisations/competition-and-markets-authority.atom",

    # DESNZ topic feeds (more specific)
    "https://www.gov.uk/search/policy-papers-and-consultations.atom?organisations%5B%5D=department-for-energy-security-and-net-zero",
    "https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=department-for-energy-security-and-net-zero",

    # Cross-department energy topics
    "https://www.gov.uk/search/policy-papers-and-consultations.atom?topics%5B%5D=energy",
    "https://www.gov.uk/search/news-and-communications.atom?topics%5B%5D=energy",

    # Planning (DLUHC)
    "https://www.gov.uk/search/policy-papers-and-consultations.atom?organisations%5B%5D=department-for-levelling-up-housing-and-communities&topics%5B%5D=planning-and-building",

    # Treasury — energy/climate relevant
    "https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=hm-treasury&topics%5B%5D=energy",
]


def _fingerprint(url: str, title: str) -> str:
    raw = f"{url}:{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


async def collect(
    client: httpx.AsyncClient,
    config: dict,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """
    Fetch GOV.UK Atom feeds. Each feed returns recent publications
    in chronological order — no search relevance ranking, no duplicates.
    """
    items = []
    seen_urls = set()

    for feed_url in GOVUK_FEEDS:
        try:
            resp = await client.get(feed_url, timeout=15)
            if resp.status_code != 200:
                log.warning(f"GOV.UK feed {feed_url}: HTTP {resp.status_code}")
                continue

            feed = feedparser.parse(resp.text)
            log.info(f"GOV.UK feed: {len(feed.entries)} entries from {feed_url[:80]}")

            for entry in feed.entries:
                url = entry.get("link", "").rstrip("/")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                # Parse date
                published = entry.get("published", entry.get("updated", ""))
                date_str = ""
                if published:
                    try:
                        entry_date = datetime.fromisoformat(
                            published.replace("Z", "+00:00")
                        )
                        # Date filter: keep items within start-1 to end+1
                        if entry_date.date() < (start - timedelta(days=1)).date():
                            continue
                        if entry_date.date() > (end + timedelta(days=1)).date():
                            continue
                        date_str = str(entry_date.date())
                    except (ValueError, TypeError):
                        pass  # no date = keep, let scorer handle it

                title = entry.get("title", "")
                summary = entry.get("summary", "")

                items.append({
                    "source_type": "govuk",
                    "title": title,
                    "date": date_str,
                    "url": url,
                    "content": f"{title}. {summary}"[:2000],
                    "source_name": "GOV.UK",
                    "keywords_matched": [],
                    "relevance_score": 0.0,
                    "verified": True,
                    "fingerprint": _fingerprint(url, title),
                })

        except Exception as e:
            log.warning(f"GOV.UK feed failed {feed_url[:60]}: {e}")

        await asyncio.sleep(0.3)

    log.info(f"GOV.UK total: {len(items)} unique items from {len(GOVUK_FEEDS)} feeds")
    return items
