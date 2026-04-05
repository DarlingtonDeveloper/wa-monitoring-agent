# Pipeline Stages

Detailed reference for each stage of the monitoring pipeline.

## Stage 1: Collect

**Module**: `src/collect/__init__.py`
**Entry**: `collect_all(config, week_start, api_key) -> list[dict]`

Runs 7 collectors. Structured APIs run in parallel; web search runs sequentially (API rate limits).

### Collectors

| Collector | Source | Items/week (typical) | Rate limited? |
|-----------|--------|---------------------|---------------|
| `hansard.py` | Hansard API | 700-900 | No |
| `govuk.py` | 10 GOV.UK Atom feeds | 20-50 | No |
| `parliament.py` | EDMs, written questions | 10-30 | No |
| `rss.py` | Trade media RSS | 5-15 | No |
| `committees.py` | Select committee evidence | 5-10 | No |
| `direct_sources.py` | 12 priority org websites | 10-30 | No |
| `web_search.py` | Claude web search (14 queries) | 20-40 | Yes (Haiku 50k/min) |

### GOV.UK Atom feeds

10 feeds covering energy policy departments and topics:

- DESNZ organisation feed
- Ofgem organisation feed
- Planning Inspectorate organisation feed
- CMA organisation feed
- DESNZ policy papers and consultations
- DESNZ news and communications
- Energy topic policy papers
- Energy topic news
- DLUHC planning policy papers
- HM Treasury energy news

### Two-pass web search

14 theme queries processed in batches of 4 with 45s rate limit cooldowns:

1. **Pass 1** (Haiku): Claude web search finds URLs + snippets
2. **Page fetch**: Top 5 URLs fetched with BeautifulSoup
3. **Pass 2** (Sonnet): Extract detailed findings from full page text

Themes: policy_government, parliamentary, regulatory_legal, media_coverage, competitor_industry, stakeholder_third_party, forward_scan, political_context, ministers, ofgem_specific, industry_reports, supply_chain, gas_ccus, planning_consenting.

### Item schema

Every collector returns dicts with:

```python
{
    "source_type": "hansard|govuk|web|parliament|rss|committees|forward_scan",
    "title": "Item title",
    "date": "2026-03-25",           # ISO 8601
    "url": "https://...",
    "content": "Full text or summary",
    "source_name": "Hansard|GOV.UK|Recharge News|...",
    "keywords_matched": [],
    "relevance_score": 0.0,          # Set later by scorer
    "verified": False,               # Set later by verifier
    "fingerprint": "abc123def456",   # SHA256(url:title)[:12]
}
```

---

## Stage 1b: Enrich

**Module**: `src/collect/content_enricher.py`
**Entry**: `enrich_items(items, client) -> list[dict]`

Fetches full page content for items with thin source text. Runs **before** scoring so that GOV.UK Atom feed summaries (200-300 chars) get full content before keyword matching.

### Rules

- Enriches items with `content < 500 chars`
- Caps at 40 items per run
- Skips Hansard (API gives full text) and PDFs
- Only replaces content if fetched text is longer than existing
- 8 concurrent fetches
- Sets `content_enriched: True` on success

---

## Stage 2: Score & Filter

**Module**: `src/score/__init__.py`
**Entry**: `score_and_filter(items, config, week_start) -> list[dict]`

### Pipeline

1. **Date filter** - Drop items outside reporting week +/- 1 day buffer
2. **Geography filter** - Drop items clearly about non-UK countries with no UK connection
3. **False positive filter** - Drop items matching false positive rules (e.g. "RWE" in pharma)
4. **Score** - Two-tier keyword scoring (see README)
5. **Min score filter** - Drop items below 0.08
6. **Deduplicate** - Fingerprint-based (URL + title hash)
7. **Verify sources** - HTTP HEAD check on URLs
8. **Sort & cap** - Top 150 by score

### Typical funnel

```
966 collected
 → 965 after date filter
 → 949 after geography filter
 → 949 after false positive filter
 → 878 after min score (0.08)
 → 421 after dedup
 → 150 after cap
```

---

## Stage 3: Analyse

**Module**: `src/analyse/__init__.py`
**Entry**: `analyse(items, config, api_key, week_start) -> dict`

### Two-phase analysis

**Phase 1: Per-theme extraction** (Haiku)
- Items routed to 7 themes by source type + content
- Claude extracts structured facts from source items (up to 30 per theme)
- Returns: title, date, source_ref, finding, significance

**Phase 2: Per-theme analysis** (Sonnet)
- Takes extracted facts + client context
- Produces: overview, significant_items (with RAG status, headline, summary, relevance, recommended_action), items list
- Each item references source fingerprints for provenance

**Phase 3: Cross-theme synthesis** (Sonnet)
- Takes all theme results
- Produces: executive_summary (top_line + key_developments), emerging_themes, actions_tracker, coverage_summary, forward_look

### Theme routing

Source-type-first routing:
- `hansard` → parliamentary (or regulatory if mentions Ofgem/NESO)
- `govuk` → policy_government (or regulatory if mentions regulators)
- `web` → check source name against media/industry/competitor lists, then content keywords
- `forward_scan` → forward_look (not a theme)

### Output

`analysis.json` conforming to `schemas/analysis.schema.json`. This is the contract between Python and the Node.js DOCX generator.

---

## Stage 4: Evaluate

**Module**: `src/evaluate/__init__.py`
**Entry**: `evaluate_report(analysis, items_cache, config) -> dict`

Three quality checks:

### Template validation

Checks analysis.json against schema requirements:
- All required sections present
- Field types correct
- Min/max lengths met
- Source references valid

### Factuality check (Opus)

For each significant_item in the analysis:
- Compares the summary text against the source item content
- Scores 0-1 for factual accuracy
- Flags items < 0.7

### Specificity check (Opus)

For each significant_item:
- Evaluates relevance to the specific client (not just generic sector news)
- Scores 0-1
- Flags items < 0.5

### Overall pass

Requires all three:
- Template validation: 0 errors
- Factuality mean: > 0.7
- Specificity mean: > 0.5

Flagged items get confidence scores reduced to max 0.5 in the analysis, which triggers visual markers in the DOCX.

---

## Stage 5: Generate DOCX

**Module**: `src/generate/generate-report.js`
**Runtime**: Node.js (subprocess from Python)

Pure template populator. No intelligence, no decisions. Reads `analysis.json` + client config and produces a branded DOCX.

### Sections

1. Title page (client name, reporting period, confidentiality)
2. Executive summary (top_line + key developments with RAG)
3. Per-theme sections (overview + significant items + full items list)
4. Forward look (upcoming events/deadlines)
5. Emerging themes
6. Actions tracker
7. Coverage summary

### Visual markers

- RAG status badges (Red/Amber/Green) on key developments
- Confidence markers on low-confidence items (< 0.7)
- Source references as footnotes/inline citations
