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
from .committees import collect as collect_committees
from .direct_sources import collect as collect_direct
from .web_search import collect_two_pass

log = logging.getLogger(__name__)


async def collect_all(
    config: dict,
    week_start: datetime,
    anthropic_api_key: str,
) -> list[dict]:
    """
    Run all collectors, merge results, return combined list.
    Structured APIs + page checks run in parallel.
    Two-pass web search runs sequentially (uses Anthropic API).
    """
    week_end = week_start + timedelta(days=4)
    results = []

    # Parallel: Hansard + GOV.UK + Parliament APIs + RSS + Committees + Direct sources
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "WA-Monitoring/1.0"},
    ) as client:
        gather_results = await asyncio.gather(
            collect_hansard(client, config, week_start, week_end),
            collect_govuk(client, config, week_start, week_end),
            collect_parliament(client, config, week_start, week_end),
            collect_rss(client, config, week_start, week_end),
            collect_committees(client, config, week_start, week_end),
            collect_direct(client, config, week_start, week_end),
            return_exceptions=True,
        )

        collector_names = [
            "Hansard", "GOV.UK", "Parliament APIs", "RSS",
            "Committees", "Direct sources",
        ]
        collector_counts = {}

        for name, items in zip(collector_names, gather_results):
            if isinstance(items, Exception):
                log.error(f"{name} collector failed: {items}")
                collector_counts[name] = 0
            else:
                results.extend(items)
                collector_counts[name] = len(items)
                log.info(f"{name}: {len(items)} items")

    # Sequential: Two-pass web search (uses Anthropic API)
    ant_client = anthropic.Anthropic(api_key=anthropic_api_key)

    try:
        web_items = await collect_two_pass(ant_client, config, week_start)
        # Count web vs forward_scan for logging
        web_count = sum(1 for i in web_items if i.get("source_type") == "web")
        forward_count = sum(1 for i in web_items if i.get("source_type") == "forward_scan")
        results.extend(web_items)
        collector_counts["Web search"] = web_count
        collector_counts["Forward scan"] = forward_count
        log.info(f"Two-pass web search: {web_count} web items, {forward_count} forward scan items")
    except Exception as e:
        log.error(f"Two-pass web search failed: {e}")

    # Collection summary
    log.info("=== COLLECTION SUMMARY ===")
    for name, count in collector_counts.items():
        log.info(f"  {name:20s} {count:>4d}")
    log.info(f"  {'TOTAL':20s} {len(results):>4d}")

    return results
