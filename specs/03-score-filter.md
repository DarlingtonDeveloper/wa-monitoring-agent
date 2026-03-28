# Spec 03: Score, Filter, Verify

## Purpose

Take the raw collected items, score them for relevance, deduplicate, verify source URLs, and cache the result as `items.json`. This stage is entirely deterministic — no LLM calls.

## Source files

- `src/score/keyword_scorer.py`
- `src/score/dedup.py`
- `src/score/source_verifier.py`
- `src/score/__init__.py` (exports `score_and_filter` function)

## 1. Keyword scorer (`keyword_scorer.py`)

Takes a `RawItem` and the client config, returns a relevance score 0-1.

**Scoring logic**:

```python
def score_item(item: RawItem, config: dict) -> float:
    text = f"{item.title} {item.content}".lower()
    score = 0.0

    # 1. Keyword matches (up to 0.5)
    all_keywords = flatten_all_keywords(config)  # strip quotes, boolean ops
    matches = sum(1 for kw in all_keywords if kw in text)
    score += min(matches * 0.06, 0.5)

    # 2. Client-specific bonus (up to 0.2)
    # Direct mentions of the client or its projects score higher
    client_terms = flatten_keywords(config["keywords"]["rwe_corporate"])
    client_matches = sum(1 for kw in client_terms if kw in text)
    score += min(client_matches * 0.1, 0.2)

    # 3. Source quality bonus (0.1)
    # Programmatic sources (Hansard, GOV.UK) > web search
    if item.source_type in ("hansard", "govuk"):
        score += 0.1

    # 4. Trade press bonus (0.05)
    trade_names = [s.lower() for s in config["sources"]["media_specialist"]]
    if any(t in item.source_name.lower() for t in trade_names):
        score += 0.05

    # 5. Recency bonus (0.1)
    # Items from the current reporting week score higher
    if item_is_within_reporting_week(item.date):
        score += 0.1

    return min(score, 1.0)
```

**`flatten_all_keywords` helper**: Takes the keyword config object, extracts all keywords across all groups, strips quote marks, splits on `AND`/`OR` operators, lowercases, deduplicates, and returns a list of clean match terms. Skip terms shorter than 3 characters.

## 2. Deduplicator (`dedup.py`)

Two dedup strategies applied in sequence:

**URL dedup**: Same URL = same item. Keep the one with the higher relevance score.

**Title similarity dedup**: Normalise titles (lowercase, strip non-alphanumeric, truncate to 60 chars). If two items have the same normalised title, keep the one with the higher relevance score.

```python
def deduplicate(items: list[RawItem]) -> list[RawItem]:
    seen_urls = {}
    seen_titles = {}
    unique = []
    for item in sorted(items, key=lambda x: x.relevance_score, reverse=True):
        url_key = item.url.lower().rstrip("/")
        title_key = re.sub(r'[^a-z0-9]', '', item.title.lower())[:60]

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
```

## 3. Source verifier (`source_verifier.py`)

For each item, check that the source URL actually resolves. This catches hallucinated sources from the web search collector.

```python
async def verify_sources(items: list[RawItem], client: httpx.AsyncClient) -> list[RawItem]:
    """
    HEAD request each URL. Set item.verified = True/False.
    Don't remove unverified items — flag them. The analysis stage
    can use this as a confidence signal.

    Rate limit: max 10 concurrent requests.
    Timeout: 5 seconds per request.
    """
```

**Rules**:
- Hansard and GOV.UK items (`source_type` in `["hansard", "govuk"]`): auto-verified, skip the HTTP check (they came from the API).
- Web search items: HEAD request the URL. 200-399 = verified. 404/500/timeout = unverified.
- Items with empty URLs: mark unverified.

## 4. Main function (`__init__.py`)

```python
async def score_and_filter(
    items: list[RawItem],
    config: dict,
    min_score: float = 0.08,
    max_items: int = 100,
) -> list[RawItem]:
    """
    1. Score all items
    2. Filter by min_score
    3. Deduplicate
    4. Verify sources
    5. Sort by relevance_score descending
    6. Cap at max_items
    7. Cache to output/items_{date}.json
    8. Log stats: total -> filtered -> deduped -> final count
    """
```

## Output

Write `output/items_{week_start}.json` — array of `RawItem` dicts, validated against `schemas/items.schema.json`.

This file can be used as input to the analysis stage via `--from-cache` flag, enabling replay without re-collecting.

## Acceptance criteria

- Given 200 raw items, the scorer produces a sensible distribution (not all 0s, not all 1s).
- Items directly mentioning RWE or its projects score > 0.3.
- Generic energy sector items with no client relevance score < 0.15.
- Dedup removes genuine duplicates (same URL or near-identical title) and keeps the higher-scored one.
- Source verification marks web-sourced items as verified/unverified without crashing on 404s or timeouts.
- The cached JSON file is valid and can be loaded by the analysis stage.
