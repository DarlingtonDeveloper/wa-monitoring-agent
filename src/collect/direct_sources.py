"""Direct source checks — scrapes publication/news pages from Section 6 of monitoring briefing."""

import asyncio
import hashlib
import logging
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

SOURCES = [
    # Section 6.1 — Government & Regulatory
    {
        "name": "Ofgem",
        "url": "https://www.ofgem.gov.uk/publications",
        "keywords": ["consultation", "decision", "call for evidence", "open letter",
                      "market reform", "network", "charging", "connection", "price control"],
    },
    {
        "name": "NESO",
        "url": "https://www.neso.energy/news-and-events",
        "keywords": ["connection", "ssep", "spatial", "reform", "scenario", "fes",
                      "curtailment", "constraint", "balancing", "pricing"],
    },
    {
        "name": "Planning Inspectorate",
        "url": "https://www.gov.uk/government/organisations/planning-inspectorate",
        "keywords": ["dco", "decision", "energy", "wind", "solar", "nsip", "examination"],
    },
    {
        "name": "Crown Estate",
        "url": "https://www.thecrownestate.co.uk/news",
        "keywords": ["offshore", "leasing", "seabed", "wind", "round", "marine"],
    },
    {
        "name": "Great British Energy",
        "url": "https://www.gbe.gov.uk/blog",
        "keywords": ["investment", "fund", "community", "supply chain", "partnership",
                      "clean energy", "local power"],
    },
    {
        "name": "CMA",
        "url": "https://www.gov.uk/government/organisations/competition-and-markets-authority",
        "keywords": ["energy", "merger", "acquisition", "investigation", "market study"],
    },
    # Section 6.3 — Industry & Stakeholder
    {
        "name": "RenewableUK",
        "url": "https://www.renewableuk.com/news",
        "keywords": ["wind", "offshore", "onshore", "energy", "report", "publication",
                      "policy", "planning", "grid"],
    },
    {
        "name": "Energy UK",
        "url": "https://www.energy-uk.org.uk/publications/",
        "keywords": ["report", "publication", "scotland", "wales", "energy", "electricity",
                      "market", "policy", "vision", "outlook"],
        "url_filter": ["/publications/", "/insights/", "/reports/"],
    },
    {
        "name": "OEUK",
        "url": "https://oeuk.org.uk/category/news/",
        "keywords": ["offshore", "energy", "oil", "gas", "ccus", "hydrogen", "investment"],
    },
    {
        "name": "ORE Catapult",
        "url": "https://ore.catapult.org.uk/news-and-events/",
        "keywords": ["offshore", "wind", "innovation", "technology", "research", "supply chain"],
    },
    {
        "name": "Climate Change Committee",
        "url": "https://www.theccc.org.uk/news/",
        "keywords": ["energy", "emissions", "carbon", "progress", "advice", "report",
                      "recommendation"],
    },
    {
        "name": "North Sea Transition Authority",
        "url": "https://www.nstauthority.co.uk/news-publications/news/",
        "keywords": ["carbon storage", "licensing", "CCS", "CCUS",
                      "carbon capture", "storage licence", "acreage"],
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
    """Check publication/news pages for every priority source."""
    items = []

    for source in SOURCES:
        try:
            resp = await client.get(source["url"], follow_redirects=True, timeout=10)
            if resp.status_code != 200:
                log.warning(f"Direct source {source['name']}: HTTP {resp.status_code}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            for link in soup.find_all("a", href=True):
                title = link.get_text(strip=True)
                href = link.get("href", "")
                if len(title) < 20:
                    continue

                # If source has URL path filters, check those first
                url_filters = source.get("url_filter")
                if url_filters:
                    if not any(uf in href for uf in url_filters):
                        continue
                else:
                    title_lower = title.lower()
                    if not any(kw in title_lower for kw in source["keywords"]):
                        continue

                if href.startswith("/"):
                    parsed = urlparse(source["url"])
                    full_url = f"{parsed.scheme}://{parsed.netloc}{href}"
                elif href.startswith("http"):
                    full_url = href
                else:
                    continue

                items.append({
                    "source_type": "web",
                    "title": title,
                    "date": "",
                    "url": full_url,
                    "content": title,
                    "source_name": source["name"],
                    "keywords_matched": [],
                    "relevance_score": 0.0,
                    "verified": True,
                    "fingerprint": _fingerprint(full_url, title),
                })

        except Exception as e:
            log.warning(f"Direct source {source['name']} failed: {e}")

        await asyncio.sleep(0.3)

    log.info(f"Direct sources: {len(items)} items from {len(SOURCES)} sources")
    return items
