"""Collection layer — pulls raw items from public sources."""

import logging
from datetime import datetime

import anthropic
import httpx

from .hansard import collect as collect_hansard
from .govuk import collect as collect_govuk
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
    Hansard and GOV.UK run in parallel (async). Web search and forward scan
    run sequentially (Anthropic API).
    """
    week_end = week_start + __import__("datetime").timedelta(days=4)
    results = []

    # Parallel: Hansard + GOV.UK
    async with httpx.AsyncClient(timeout=30) as client:
        import asyncio
        hansard_task = collect_hansard(client, config, week_start, week_end)
        govuk_task = collect_govuk(client, config, week_start, week_end)
        hansard_items, govuk_items = await asyncio.gather(
            hansard_task, govuk_task, return_exceptions=True
        )

        if isinstance(hansard_items, Exception):
            log.error(f"Hansard collector failed: {hansard_items}")
            hansard_items = []
        if isinstance(govuk_items, Exception):
            log.error(f"GOV.UK collector failed: {govuk_items}")
            govuk_items = []

        results.extend(hansard_items)
        results.extend(govuk_items)
        log.info(f"Hansard: {len(hansard_items)} items | GOV.UK: {len(govuk_items)} items")

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
