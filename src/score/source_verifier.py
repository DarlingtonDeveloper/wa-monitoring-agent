"""Source URL verification."""

import asyncio
import logging

import httpx

log = logging.getLogger(__name__)

MAX_CONCURRENT = 10


async def verify_sources(items: list[dict], client: httpx.AsyncClient) -> list[dict]:
    """
    HEAD request each URL to verify it resolves.
    Hansard/GOV.UK items are auto-verified (came from API).
    Max 10 concurrent requests, 5s timeout per request.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def verify_one(item: dict) -> dict:
        # API sources are auto-verified
        if item.get("source_type") in ("hansard", "govuk"):
            item["verified"] = True
            return item

        url = item.get("url", "")
        if not url:
            item["verified"] = False
            return item

        async with semaphore:
            try:
                resp = await client.head(url, follow_redirects=True, timeout=5)
                item["verified"] = 200 <= resp.status_code < 400
            except (httpx.HTTPError, httpx.TimeoutException):
                item["verified"] = False
            except Exception:
                item["verified"] = False

        return item

    results = await asyncio.gather(
        *[verify_one(item) for item in items],
        return_exceptions=True,
    )

    verified = []
    for r in results:
        if isinstance(r, Exception):
            log.warning(f"Verification error: {r}")
        elif isinstance(r, dict):
            verified.append(r)

    return verified
