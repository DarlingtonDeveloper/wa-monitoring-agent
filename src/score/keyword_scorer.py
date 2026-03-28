"""Keyword-based relevance scorer for collected items."""

import re
from datetime import datetime, timedelta


def flatten_keywords(keyword_list: list[str]) -> list[str]:
    """Clean a keyword list: lowercase, strip quotes, split on AND/OR, skip short terms."""
    cleaned = []
    for kw in keyword_list:
        kw = kw.strip('"').strip("'")
        parts = re.split(r'\s+(?:AND|OR)\s+', kw)
        for part in parts:
            part = part.strip().lower()
            if len(part) >= 3:
                cleaned.append(part)
    return list(set(cleaned))


def flatten_all_keywords(config: dict) -> list[str]:
    """Extract all keywords across all groups from config."""
    all_kw = []
    for group in config.get("keywords", {}).values():
        all_kw.extend(flatten_keywords(group))
    return list(set(all_kw))


def score_item(item: dict, config: dict) -> float:
    """Score a RawItem for relevance. Returns 0-1 float."""
    text = f"{item.get('title', '')} {item.get('content', '')}".lower()
    score = 0.0

    # 1. Keyword matches (up to 0.5)
    all_keywords = flatten_all_keywords(config)
    matches = sum(1 for kw in all_keywords if kw in text)
    score += min(matches * 0.06, 0.5)

    # 2. Client-specific bonus (up to 0.2)
    client_terms = flatten_keywords(config.get("keywords", {}).get("rwe_corporate", []))
    client_matches = sum(1 for kw in client_terms if kw in text)
    score += min(client_matches * 0.1, 0.2)

    # 3. Source quality bonus (0.1)
    if item.get("source_type") in ("hansard", "govuk"):
        score += 0.1

    # 4. Trade press bonus (0.05)
    trade_names = [s.lower() for s in config.get("sources", {}).get("media_specialist", [])]
    source_name = item.get("source_name", "").lower()
    if any(t in source_name for t in trade_names):
        score += 0.05

    # 5. Recency bonus (0.1)
    date_str = item.get("date", "")
    if date_str:
        try:
            item_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
            if (datetime.now() - item_date) <= timedelta(days=7):
                score += 0.1
        except ValueError:
            pass

    return min(score, 1.0)
