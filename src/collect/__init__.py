"""Collection layer — pulls raw items from public sources."""

import asyncio
import logging
from datetime import datetime, timedelta

import anthropic
import httpx

from .hansard import collect as collect_hansard
from .govuk import collect as collect_govuk
from .parliament import collect as collect_parliament
from .rss import collect as collect_rss
from .web_search import collect as collect_web
from .forward_scan import collect as collect_forward

log = logging.getLogger(__name__)


async def collect_all(
    config: dict,
    week_start: datetime,
    anthropic_api_key: str,
) -> list[dict]:
    """
    Run all collectors, merge results, return combined list.
    API collectors run in parallel. Anthropic collectors run sequentially.
    """
    week_end = week_start + timedelta(days=4)
    results = []

    # Parallel: Hansard + GOV.UK + Parliament APIs + RSS
    async with httpx.AsyncClient(timeout=30) as client:
        hansard_items, govuk_items, parliament_items, rss_items = await asyncio.gather(
            collect_hansard(client, config, week_start, week_end),
            collect_govuk(client, config, week_start, week_end),
            collect_parliament(client, config, week_start, week_end),
            collect_rss(client, config, week_start, week_end),
            return_exceptions=True,
        )

        for name, items in [
            ("Hansard", hansard_items),
            ("GOV.UK", govuk_items),
            ("Parliament APIs", parliament_items),
            ("RSS", rss_items),
        ]:
            if isinstance(items, Exception):
                log.error(f"{name} collector failed: {items}")
            else:
                results.extend(items)
                log.info(f"{name}: {len(items)} items")

    # Sequential: Web search + Forward scan (Anthropic API)
    ant_client = anthropic.Anthropic(api_key=anthropic_api_key)

    try:
        web_items = collect_web(ant_client, config, week_start, week_end)
        results.extend(web_items)
        log.info(f"Web search: {len(web_items)} items")
    except Exception as e:
        log.error(f"Web search collector failed: {e}")

    try:
        forward_items = collect_forward(ant_client, config, week_start, week_end)
        results.extend(forward_items)
        log.info(f"Forward scan: {len(forward_items)} items")
    except Exception as e:
        log.error(f"Forward scan collector failed: {e}")

    log.info(f"Total collected: {len(results)} items")
    return results
