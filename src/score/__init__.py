"""Score, filter, deduplicate, and verify collected items.

Enrichment now happens BEFORE scoring (in orchestrator.py) so that
GOV.UK items with thin Atom feed summaries get full page content
before keyword scoring runs.
"""

import logging
from datetime import datetime

import httpx

from .keyword_scorer import (
    score_item,
    is_within_reporting_window,
    is_uk_relevant,
    apply_false_positive_rules,
)
from .dedup import deduplicate
from .source_verifier import verify_sources

log = logging.getLogger(__name__)


async def score_and_filter(
    items: list[dict],
    config: dict,
    week_start: datetime,
    min_score: float = 0.08,
    max_items: int = 150,
) -> list[dict]:
    """
    1. Hard date filter (drop items outside reporting window)
    2. Hard geography filter (drop non-UK items)
    3. False positive filter
    4. Score all items
    5. Filter by min_score
    6. Deduplicate
    7. Verify sources
    8. Sort by relevance_score descending
    9. Cap at max_items

    NOTE: Enrichment happens before this function is called (in orchestrator.py).
    """
    original = len(items)

    # 1. Hard date filter
    items = [i for i in items if is_within_reporting_window(i.get("date", ""), week_start)]
    log.info(f"Date filter: {original} -> {len(items)}")

    # 2. Hard geography filter
    pre_geo = len(items)
    items = [i for i in items if is_uk_relevant(i)]
    log.info(f"Geography filter: {pre_geo} -> {len(items)}")

    # 3. False positive filter
    pre_fp = len(items)
    items = [i for i in items if apply_false_positive_rules(i)]
    log.info(f"False positive filter: {pre_fp} -> {len(items)}")

    # 4. Score
    for item in items:
        item["relevance_score"] = score_item(item, config)

    # 5. Filter by minimum score
    pre_score = len(items)
    items = [i for i in items if i["relevance_score"] >= min_score]
    log.info(f"Score filter: {pre_score} -> {len(items)} (min_score={min_score})")

    # 6. Deduplicate
    pre_dedup = len(items)
    items = deduplicate(items)
    log.info(f"Dedup: {pre_dedup} -> {len(items)}")

    # 7. Verify sources
    async with httpx.AsyncClient(timeout=5) as client:
        items = await verify_sources(items, client)

    # 8. Sort and cap
    items.sort(key=lambda x: x["relevance_score"], reverse=True)
    final = items[:max_items]

    verified_count = sum(1 for i in final if i.get("verified"))
    enriched_count = sum(1 for i in final if i.get("content_enriched"))
    log.info(
        f"Final: {len(final)} items ({verified_count} verified, "
        f"{enriched_count} enriched, from {original} collected)"
    )

    return final
