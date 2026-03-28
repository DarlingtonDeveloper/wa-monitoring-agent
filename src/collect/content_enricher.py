"""Content enricher — fetches full page text for top-scored items.

This improves factuality by giving the analysis stage more source material
to ground its claims in, rather than relying on short snippets.
"""

import asyncio
import logging
import re

import httpx

log = logging.getLogger(__name__)

MAX_CONCURRENT = 5
MAX_CONTENT_LENGTH = 2000
TOP_N = 30  # Enrich the top N items by score


def _extract_text(html: str) -> str:
    """Extract readable text from HTML, stripping tags and boilerplate."""
    # Remove script and style blocks
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # Try to extract article/main content first
    article_match = re.search(
        r'<(?:article|main)[^>]*>(.*?)</(?:article|main)>',
        html, re.DOTALL | re.IGNORECASE
    )
    if article_match:
        html = article_match.group(1)

    # Strip remaining tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Decode common HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')

    return text


async def enrich_items(
    items: list[dict],
    client: httpx.AsyncClient,
) -> list[dict]:
    """
    Fetch full page content for the top-scored items.
    Replaces short snippets with richer text for better analysis grounding.
    Only enriches items where the existing content is short (<300 chars).
    """
    # Sort by score, pick top N with short content
    candidates = sorted(items, key=lambda x: x.get("relevance_score", 0), reverse=True)
    to_enrich = [
        i for i in candidates[:TOP_N]
        if len(i.get("content", "")) < 300
        and i.get("url")
        and i.get("source_type") != "hansard"  # Hansard already has full text
    ]

    if not to_enrich:
        return items

    log.info(f"Enriching {len(to_enrich)} items with full page content...")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def fetch_content(item: dict) -> None:
        async with semaphore:
            url = item.get("url", "")
            try:
                resp = await client.get(url, follow_redirects=True, timeout=10)
                if resp.status_code != 200:
                    return

                content_type = resp.headers.get("content-type", "")
                if "html" not in content_type.lower():
                    return

                text = _extract_text(resp.text)
                if len(text) > len(item.get("content", "")):
                    # Keep original as prefix, append enriched content
                    original = item.get("content", "")
                    enriched = text[:MAX_CONTENT_LENGTH]
                    if original and original not in enriched:
                        item["content"] = f"{original}\n\n{enriched}"[:MAX_CONTENT_LENGTH]
                    else:
                        item["content"] = enriched
                    log.debug(f"Enriched: {item.get('title', '')[:50]} ({len(item['content'])} chars)")

            except (httpx.TimeoutException, httpx.HTTPError):
                pass
            except Exception as e:
                log.debug(f"Enrich failed for {url}: {e}")

    await asyncio.gather(*[fetch_content(i) for i in to_enrich])

    enriched_count = sum(1 for i in to_enrich if len(i.get("content", "")) > 300)
    log.info(f"Enriched {enriched_count}/{len(to_enrich)} items with full content")

    return items
