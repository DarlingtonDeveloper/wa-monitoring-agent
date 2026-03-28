# Spec 02: Collection Layer

## Purpose

Pull raw items from public sources for the reporting week. Each collector returns `RawItem` objects (as defined in `schemas/items.schema.json`). Be honest about access: Hansard and GOV.UK have real APIs. Everything else uses Claude web search with URL verification.

## Source files

- `src/collect/hansard.py`
- `src/collect/govuk.py`
- `src/collect/web_search.py`
- `src/collect/forward_scan.py`
- `src/collect/__init__.py` (exports `collect_all` async function)

## Shared interface

Every collector implements:

```python
async def collect(
    client: httpx.AsyncClient,
    config: dict,            # Full client config
    start: datetime,         # Monday of reporting week
    end: datetime,           # Friday of reporting week
) -> list[RawItem]
```

Except `web_search.py` which uses the Anthropic SDK (synchronous):

```python
def collect(
    anthropic_client: anthropic.Anthropic,
    config: dict,
    start: datetime,
    end: datetime,
) -> list[RawItem]
```

## 1. Hansard collector (`hansard.py`)

**API**: `https://hansard-api.parliament.uk/search.json`

**Parameters**:
- `searchTerm`: keyword from config
- `startDate`, `endDate`: reporting period (YYYY-MM-DD)

**Search terms to use** (derived from config keywords, not all 200+):
```
"RWE", "offshore wind", "energy security", "clean power",
"CfD", "Contracts for Difference", "NESO", "Ofgem", "DESNZ",
"grid connection", "Great British Energy", "Crown Estate",
"REMA", "CCUS", "wind farm", "renewable energy"
```

**Rate limiting**: 0.5s delay between requests.

**For each result, extract**:
- title: from `Title` or `MemberName`
- date: from `Date` or `SittingDate`
- url: from `Url` or `Link` (prepend `https://hansard.parliament.uk` if relative)
- content: from `SearchResultText` or `Text` (truncate to 1000 chars)
- source_name: `"Hansard"`
- source_type: `"hansard"`
- keywords_matched: which search term produced this result

**Edge cases**:
- API returns 404 or 500: log warning, return empty list, do NOT raise.
- API returns empty results for a keyword: normal, continue to next keyword.
- Duplicate results across keywords: handled downstream by dedup, don't worry here.

## 2. GOV.UK collector (`govuk.py`)

**API**: `https://www.gov.uk/api/search.json`

**Parameters**:
- `q`: search query
- `count`: 10
- `order`: `"most-recent"`
- `filter_organisations[]`: varies by query (use `department-for-energy-security-and-net-zero` for most, omit for cross-department queries like Crown Estate)

**Search queries**:
```
"offshore wind CfD", "DESNZ energy announcement",
"Ofgem consultation decision", "Great British Energy",
"REMA electricity market", "grid connections reform",
"energy resilience strategy", "Crown Estate seabed",
"NESO strategic spatial", "CCUS carbon capture",
"planning inspectorate energy", "onshore wind planning",
"clean power 2030"
```

**Date filtering**: The API doesn't filter by date natively. After fetching, filter by `public_timestamp` — keep items from the last 14 days (not just the reporting week, to catch items published just before the period that are still relevant).

**For each result, extract**:
- title: from `title`
- date: from `public_timestamp`
- url: `https://www.gov.uk` + `link`
- content: from `description` (truncate to 1000 chars)
- source_name: `"GOV.UK"` or more specific if `organisations` field available (e.g. `"GOV.UK DESNZ"`)
- source_type: `"govuk"`

**Rate limiting**: 0.3s delay between requests.

## 3. Web search collector (`web_search.py`)

Uses the Anthropic API with `web_search_20250305` tool. This covers sources without APIs: Ofgem, NESO, Crown Estate, GBE, media, industry bodies, competitors.

**Approach**: Make one Claude API call per search query. The prompt instructs Claude to search and return structured results.

**Search queries** (construct from config — the client name, project names, policy areas, competitors):
```python
queries = [
    f"{config['client']['name']} UK {month_year}",
    f"Sofia offshore wind farm {year}",
    f"Norfolk Vanguard offshore wind {year}",
    f"DESNZ energy policy {month_year}",
    f"UK offshore wind AR8 allocation round {year}",
    f"Great British Energy investment fund {year}",
    f"Crown Estate seabed leasing offshore wind {year}",
    f"REMA reformed national pricing UK {year}",
    f"Ofgem consultation energy {month_year}",
    f"NESO strategic spatial energy plan {year}",
    f"Orsted SSE Equinor UK offshore wind {month_year}",
    f"UK energy security resilience {month_year}",
    f"RenewableUK Energy UK offshore wind {month_year}",
    f"offshore wind supply chain UK {month_year}",
    f"CCUS carbon capture UK {year}",
]
```

**For each query, API call**:
```python
response = anthropic_client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=2048,
    tools=[{"type": "web_search_20250305", "name": "web_search"}],
    messages=[{
        "role": "user",
        "content": f"Search for: {query}\n\nReturn a JSON array of the most relevant results from the past 2 weeks. Each object: {{title, date, url, snippet, source_name}}. Return ONLY the JSON array."
    }],
)
```

**Parse response**: Extract text blocks, strip markdown fences, parse JSON. If JSON parsing fails, log and skip — don't crash.

**source_type**: `"web"` for all items from this collector.

## 4. Forward scan collector (`forward_scan.py`)

Collects *future* events for Section 3 (Forward Look). Uses Claude web search.

**Search queries**:
```python
forward_queries = [
    "UK energy consultation deadline upcoming 2026",
    "parliamentary calendar energy committee session upcoming",
    "offshore wind industry conference UK 2026",
    "CfD allocation round 8 AR8 timeline 2026",
    "SSEP strategic spatial energy plan publication date",
    "Great British Energy investment fund launch date",
    "Norfolk Vanguard FID final investment decision date",
    "Crown Estate leasing round timeline",
    "Ofgem RIIO consultation deadline",
]
```

**Output**: Same `RawItem` format. These get tagged with `source_type: "forward_scan"` so the analysis stage knows to route them to the Forward Look section rather than the main monitoring themes.

## 5. `collect_all` function (`__init__.py`)

```python
async def collect_all(
    config: dict,
    week_start: datetime,
    anthropic_api_key: str,
) -> list[RawItem]:
    """
    Run all collectors, merge results, return combined list.
    Log collection stats: items per source, any failures.
    """
```

Run Hansard and GOV.UK collectors in parallel (both async). Run web search and forward scan sequentially (they use the Anthropic API).

Return the merged list. Don't deduplicate here — that's the next stage.

## Acceptance criteria

- `collect_all` returns a list of `RawItem` objects.
- Hansard collector hits the real API and returns results for at least 3 of the search terms.
- GOV.UK collector returns results filtered to the last 14 days.
- Web search collector makes at least 12 searches and returns parseable results.
- Forward scan collector returns future-dated items.
- No collector raises an exception that kills the pipeline. All failures are logged and return empty lists.
- Total collection time under 3 minutes.
