"""Select committee scraper — checks 7 key committees from Section 6.2 of monitoring briefing."""

import asyncio
import hashlib
import logging

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

COMMITTEES = [
    {
        "name": "Energy Security and Net Zero Committee",
        "url": "https://committees.parliament.uk/committee/135/energy-security-and-net-zero-committee/",
        "keywords": ["energy", "wind", "offshore", "power", "grid", "net zero", "resilience"],
    },
    {
        "name": "Environmental Audit Committee",
        "url": "https://committees.parliament.uk/committee/62/environmental-audit-committee/",
        "keywords": ["energy", "climate", "environment", "biodiversity", "carbon"],
    },
    {
        "name": "Business and Trade Committee",
        "url": "https://committees.parliament.uk/committee/365/business-and-trade-committee/",
        "keywords": ["energy", "supply chain", "industry", "investment"],
    },
    {
        "name": "Science, Innovation and Technology Committee",
        "url": "https://committees.parliament.uk/committee/135/",
        "keywords": ["energy", "technology", "innovation", "digital"],
    },
    {
        "name": "Lords Industry and Regulators Committee",
        "url": "https://committees.parliament.uk/committee/517/industry-and-regulators-committee/",
        "keywords": ["energy", "regulation", "ofgem", "industry"],
    },
    {
        "name": "Welsh Affairs Committee",
        "url": "https://committees.parliament.uk/committee/46/welsh-affairs-committee/",
        "keywords": ["energy", "wind", "wales", "marine"],
    },
    {
        "name": "Scottish Affairs Committee",
        "url": "https://committees.parliament.uk/committee/136/scottish-affairs-committee/",
        "keywords": ["energy", "wind", "scotland", "oil", "gas"],
    },
]


def _fingerprint(url: str, title: str) -> str:
    raw = f"{url}:{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


async def collect(
    client: httpx.AsyncClient,
    config: dict,
    start, end,
) -> list[dict]:
    """Scrape select committee pages for energy-relevant activity."""
    items = []

    for committee in COMMITTEES:
        try:
            resp = await client.get(committee["url"], follow_redirects=True, timeout=10)
            if resp.status_code != 200:
                log.warning(f"Committee {committee['name']}: HTTP {resp.status_code}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True)
                href = link.get("href", "")
                if len(text) < 15:
                    continue
                text_lower = text.lower()
                if any(kw in text_lower for kw in committee["keywords"]):
                    if href.startswith("http"):
                        full_url = href
                    elif href.startswith("/"):
                        full_url = f"https://committees.parliament.uk{href}"
                    else:
                        continue

                    items.append({
                        "source_type": "hansard",
                        "title": f"{committee['name']}: {text}",
                        "date": "",
                        "url": full_url,
                        "content": text,
                        "source_name": committee["name"],
                        "keywords_matched": ["committee"],
                        "relevance_score": 0.0,
                        "verified": True,
                        "fingerprint": _fingerprint(full_url, text),
                    })

        except Exception as e:
            log.warning(f"Committee scrape failed: {committee['name']}: {e}")

        await asyncio.sleep(0.3)

    log.info(f"Committees: {len(items)} items from {len(COMMITTEES)} committees")
    return items
