"""Deduplication of collected items."""

import re


def deduplicate(items: list[dict]) -> list[dict]:
    """
    Deduplicate items by URL and normalised title.
    Keeps the highest-scored item in each case.
    """
    seen_urls: dict[str, bool] = {}
    seen_titles: dict[str, bool] = {}
    unique = []

    # Sort by score descending so we keep the best version
    for item in sorted(items, key=lambda x: x.get("relevance_score", 0), reverse=True):
        url_key = item.get("url", "").lower().rstrip("/")
        title_key = re.sub(r'[^a-z0-9]', '', item.get("title", "").lower())[:60]

        if url_key and url_key in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue

        if url_key:
            seen_urls[url_key] = True
        if title_key:
            seen_titles[title_key] = True
        unique.append(item)

    return unique
