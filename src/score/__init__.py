"""Score, filter, deduplicate, and verify collected items."""

import json
import logging
from datetime import datetime
from pathlib import Path

import httpx

from .keyword_scorer import score_item
from .dedup import deduplicate
from .source_verifier import verify_sources

log = logging.getLogger(__name__)


async def score_and_filter(
    items: list[dict],
    config: dict,
    min_score: float = 0.08,
    max_items: int = 100,
) -> list[dict]:
    """
    1. Score all items
    2. Filter by min_score
    3. Deduplicate
    4. Verify sources
    5. Sort by relevance_score descending
    6. Cap at max_items
    """
    total = len(items)

    # Score
    for item in items:
        item["relevance_score"] = score_item(item, config)

    # Filter
    filtered = [i for i in items if i["relevance_score"] >= min_score]
    log.info(f"Score filter: {total} -> {len(filtered)} (min_score={min_score})")

    # Deduplicate
    deduped = deduplicate(filtered)
    log.info(f"Dedup: {len(filtered)} -> {len(deduped)}")

    # Verify sources
    async with httpx.AsyncClient(timeout=5) as client:
        verified = await verify_sources(deduped, client)

    # Sort and cap
    verified.sort(key=lambda x: x["relevance_score"], reverse=True)
    final = verified[:max_items]

    verified_count = sum(1 for i in final if i["verified"])
    log.info(
        f"Final: {len(final)} items ({verified_count} verified, "
        f"{len(final) - verified_count} unverified)"
    )

    return final
