"""Content enricher — fetches full page text for items with thin content.

Enriches by content length, not by score. Fabrication comes from items with
thin source content regardless of their relevance score. A GOV.UK one-liner
that scores 0.3 still produces fabricated attribution. With full page content,
the model doesn't need to fill gaps from its own knowledge.
"""

import asyncio
import logging

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

MIN_CONTENT_LENGTH = 500
MAX_TO_ENRICH = 40
MAX_CONTENT_LENGTH = 8000
MAX_CONCURRENT = 8


async def enrich_items(
    items: list[dict],
    client: httpx.AsyncClient,
) -> list[dict]:
    """
    Enrich items that have thin source content, regardless of score.
    Any item with content under MIN_CONTENT_LENGTH gets its page fetched.

    Skip items where:
    - URL is empty
    - source_type is "hansard" (API gives full text)
    - URL is a PDF
    """
    to_enrich = [
        item for item in items
        if len(item.get("content", "")) < MIN_CONTENT_LENGTH
        and item.get("url")
        and item.get("source_type") != "hansard"
        and not item.get("url", "").lower().endswith(".pdf")
    ]

    # Cap to avoid fetching hundreds of pages
    to_enrich = to_enrich[:MAX_TO_ENRICH]

    if not to_enrich:
        return items

    log.info(
        f"Enriching {len(to_enrich)} items with thin content "
        f"(< {MIN_CONTENT_LENGTH} chars)..."
    )

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    enriched_count = 0

    async def fetch_content(item: dict) -> None:
        nonlocal enriched_count
        async with semaphore:
            url = item.get("url", "")
            try:
                resp = await client.get(url, follow_redirects=True, timeout=10)
                if resp.status_code != 200:
                    return

                content_type = resp.headers.get("content-type", "")
                if "html" not in content_type.lower():
                    return

                soup = BeautifulSoup(resp.text, "html.parser")

                # Remove non-content elements
                for tag in soup.find_all(
                    ["nav", "footer", "script", "style", "header", "aside"]
                ):
                    tag.decompose()

                # Extract main content
                main = (
                    soup.find("article")
                    or soup.find("main")
                    or soup.find("body")
                )
                if main:
                    text = main.get_text(separator=" ", strip=True)
                    text = " ".join(text.split())
                    # Only replace if we got more content than we had
                    if len(text) > len(item.get("content", "")):
                        item["content"] = text[:MAX_CONTENT_LENGTH]
                        item["content_enriched"] = True
                        enriched_count += 1
                        log.debug(
                            f"Enriched: {item.get('title', '')[:50]} "
                            f"({len(item['content'])} chars)"
                        )

            except (httpx.TimeoutException, httpx.HTTPError):
                pass
            except Exception as e:
                log.debug(f"Enrich failed for {url}: {e}")

    await asyncio.gather(*[fetch_content(i) for i in to_enrich])

    log.info(
        f"Enriched {enriched_count}/{len(to_enrich)} items with full content"
    )
    return items
