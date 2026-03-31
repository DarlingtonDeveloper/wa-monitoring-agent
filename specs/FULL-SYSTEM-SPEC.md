# WA Monitoring Agent — Full System Specification

## Overview

Automated public affairs monitoring pipeline for a Westminster lobbying firm. Runs overnight Sunday, collects the week's developments from UK public sources, analyses them through Claude, evaluates output quality, and produces a draft DOCX briefing report for consultant review Monday morning.

Replaces 3-4 hours of manual work per client per week. Current performance: ~23 minutes runtime, ~£2.60 per run.

---

## Design Principles

### Multi-client from the start

Nothing is hardcoded to any client. Everything is driven by a client config JSON. To add a new client, create a new config file. The pipeline, prompts, scoring, routing, and evaluation all adapt automatically.

### Source provenance everywhere

Every claim in the output must trace back to a specific collected item via a `fingerprint` reference. Items without provenance are automatically stripped. Broken citations reduce confidence scores. This creates an auditable chain from every claim in the report back to a specific source.

### Tiered model strategy

Cheap models for mechanical tasks, expensive models for judgement. This keeps cost manageable while maintaining quality where it matters.

| Task | Model | Reasoning |
|------|-------|-----------|
| Fact extraction (Pass 1) | Haiku 4.5 | Fast, cheap, good at structured extraction |
| Theme analysis (Pass 2) | Sonnet 4 | Balanced quality + tool_use for structured output |
| Web search / Forward scan | Sonnet 4 | Required for web_search tool support |
| Synthesis | Opus 4.6 | Highest quality + extended thinking for cross-cutting analysis |
| Factuality / Specificity judges | Opus 4.6 | Strictest, most calibrated evaluation |

### Evaluation before generation

The report is evaluated for factuality and specificity before the DOCX is generated. Flagged items get their confidence reduced, which the DOCX renderer marks with an inline warning. The consultant knows exactly which items to double-check.

### analysis.json is the contract

A JSON schema shared between the Python pipeline and the Node.js DOCX generator is the only interface between them. Both sides are built to the schema. The analysis stage and the generation stage are completely decoupled. You can re-run generation on a cached analysis, or swap the DOCX generator for a different output format.

### Graceful degradation everywhere

Every API call has retry with exponential backoff. Every analysis call has fallback defaults. If synthesis fails, a fallback structure is returned. If a web page can't be fetched, the snippet is kept. If fact extraction returns nothing, analysis falls back to single-pass. The pipeline never crashes.

### Cache intermediate outputs

`items.json` is cached after collection/scoring. `analysis.json` after analysis. `eval.json` after evaluation. Any downstream stage can be re-run without re-running upstream stages. Critical for iteration.

---

## Repository Structure

```
wa-monitoring-agent/
├── CLAUDE.md                          # Project context for Claude Code
├── specs/
│   ├── 00-schema.md                   # Schema contract (items + analysis JSON schemas)
│   ├── 01-config.md                   # Client config structure
│   ├── 02-collect.md                  # Collection layer
│   ├── 03-score-filter.md             # Scoring, filtering, verification
│   ├── 04-analyse.md                  # Claude analysis calls
│   ├── 05-generate.md                 # DOCX generator
│   ├── 06-evaluate.md                 # Quality evaluation layer
│   ├── 07-orchestrator.md             # Pipeline runner + Opik setup
│   └── FULL-SYSTEM-SPEC.md           # This file
├── src/
│   ├── orchestrator.py                # Main pipeline runner
│   ├── config/
│   │   └── rwe_client.json            # Client config (RWE Renewables)
│   ├── collect/
│   │   ├── __init__.py                # collect_all() — runs all collectors
│   │   ├── hansard.py                 # Hansard API collector
│   │   ├── govuk.py                   # GOV.UK API collector
│   │   ├── parliament.py              # Additional parliamentary endpoints
│   │   ├── rss.py                     # RSS feed collector
│   │   ├── web_search.py              # Two-pass web search collector
│   │   ├── forward_scan.py            # Forward events collector (legacy)
│   │   └── content_enricher.py        # Full page fetch for top items
│   ├── score/
│   │   ├── __init__.py                # score_and_filter() pipeline
│   │   ├── keyword_scorer.py          # Keyword-based relevance scoring
│   │   ├── dedup.py                   # URL + title deduplication
│   │   └── source_verifier.py         # HEAD request URL verification
│   ├── analyse/
│   │   ├── __init__.py                # analyse() — route, analyse, synthesise
│   │   ├── theme_analyser.py          # Two-pass theme analysis
│   │   └── synthesiser.py             # Cross-theme synthesis
│   ├── evaluate/
│   │   ├── __init__.py                # evaluate_report() — all checks
│   │   ├── template_validator.py      # Deterministic structural checks
│   │   └── judge.py                   # LLM-as-judge (factuality + specificity)
│   ├── generate/
│   │   ├── generate-report.js         # DOCX generator (Node.js)
│   │   └── package.json
│   └── utils/
│       ├── __init__.py
│       └── retry.py                   # Exponential backoff helpers
├── schemas/
│   ├── items.schema.json
│   └── analysis.schema.json
├── output/                            # Generated artefacts per run
├── docker-compose.yml                 # Opik self-hosted
├── requirements.txt
└── package.json
```

---

## Tech Stack

- **Python 3.11+**: Pipeline, collection, analysis, evaluation
- **Node.js 18+**: DOCX generation only (docx-js)
- **Anthropic SDK** (`anthropic>=0.45.0`): Claude API calls for analysis and web search
- **Opik SDK** (`opik>=1.0.0`): Tracing, LLM-as-judge metrics, cost tracking, dashboard
- **httpx** (`httpx>=0.27.0`): Async HTTP for API collection and page fetching
- **BeautifulSoup** (`beautifulsoup4>=4.12.0`): HTML parsing for content enrichment
- **jsonschema** (`jsonschema>=4.20.0`): Analysis JSON validation
- **python-dotenv** (`python-dotenv>=1.0.0`): Environment variable loading
- **Docker Compose**: Opik self-hosted dashboard

---

## Client Config (`src/config/rwe_client.json`)

The config defines everything the pipeline needs to know about a client. To support a new client, create a new config file — no code changes required.

### Structure

```json
{
  "client": {
    "name": "RWE Renewables",         // Short name used in prompts and filenames
    "full_name": "RWE AG",            // Full legal name
    "sector": "Energy / Offshore Wind",
    "country": "United Kingdom"
  },

  "projects": [
    {
      "name": "Sofia Offshore Wind Farm",
      "capacity_mw": 1400,
      "location": "Dogger Bank, North Sea",
      "status": "Under construction",
      "partners": ["RWE (100%)"],
      "key_dates": ["First power expected 2026", "Full commissioning 2027"],
      "priority": "HIGH PROFILE"       // MOST STRATEGICALLY IMPORTANT | HIGH PROFILE | STANDARD | MONITOR
    }
    // ... more projects
  ],

  "keywords": {
    "rwe_corporate": [...],            // Client-specific terms (name, projects, people)
    "uk_energy_policy": [...],         // Policy landscape keywords
    "offshore_wind": [...],            // Sector-specific keywords
    "competitors": [...],              // Competitor names and projects
    "parliamentary": [...],            // Parliamentary procedure terms
    "social_reputational": [...],      // Social media and reputation terms
    "financial_investment": [...]      // Financial and investment terms
  },

  "false_positive_rules": [
    {
      "pattern": "Sofia",
      "exclude_context": ["Sofia Bulgaria", "Queen Sofia"],
      "note": "Sofia is a common name — require wind/offshore/energy context"
    }
  ],

  "monitoring_themes": [
    {"id": "policy_government", "label": "Policy & Government Activity", "section": "2.1"},
    {"id": "parliamentary", "label": "Parliamentary Activity", "section": "2.2"},
    {"id": "regulatory_legal", "label": "Regulatory & Legal", "section": "2.3"},
    {"id": "media_coverage", "label": "Media Coverage", "section": "2.4"},
    {"id": "social_media", "label": "Social Media & Digital", "section": "2.5"},
    {"id": "competitor_industry", "label": "Competitor & Industry Intelligence", "section": "2.6"},
    {"id": "stakeholder_third_party", "label": "Stakeholder & Third Party Activity", "section": "2.7"}
  ],

  "escalation": {
    "IMMEDIATE": ["Direct mention of client in Parliament", "Government announcements affecting client projects", ...],
    "HIGH": ["Policy changes affecting sector broadly", "CfD round announcements", ...],
    "STANDARD": ["Routine parliamentary mentions", "General energy commentary", ...]
  },

  "sources": {
    "programmatic": [
      {"name": "Hansard", "type": "api", "base_url": "https://hansard-api.parliament.uk"},
      {"name": "GOV.UK", "type": "api", "base_url": "https://www.gov.uk/api/search.json"}
    ],
    "web_search": [
      {"name": "Ofgem", "url": "https://www.ofgem.gov.uk"},
      {"name": "Crown Estate", "url": "https://www.thecrownestate.co.uk"}
      // ... more web sources
    ],
    "media_specialist": ["Recharge News", "Windpower Monthly", "Utility Week"],
    "media_national": ["Financial Times", "The Times", "Bloomberg", "Reuters"],
    "media_regional": ["Eastern Daily Press", "Grimsby Telegraph"],
    "media_political": ["Politico London Playbook", "PoliticsHome"],
    "industry": ["RenewableUK", "Energy UK", "OEUK"]
  },

  "report": {
    "consultancy_name": "WA Communications",
    "consultancy_subtitle": "Public Affairs & Strategic Communications",
    "classification": "CONFIDENTIAL",
    "prepared_by_default": "AI Monitoring Agent (Draft)",
    "reviewed_by_default": "[Account Lead]"
  }
}
```

### How config drives the pipeline

- **`keywords`** drive the scoring stage — every collected item is scored against all keyword groups
- **`monitoring_themes`** drive item routing — each item goes to exactly one theme
- **`projects`** drive specificity — the analysis model is instructed to reference projects by name and capacity; the specificity judge evaluates whether it did
- **`escalation`** triggers are included in the analysis prompt so the model can set correct escalation levels
- **`sources`** drive collection — API base URLs, web search targets, and media lists used for routing
- **`false_positive_rules`** are available for scoring refinement
- **`report`** metadata flows through to DOCX header/footer

---

## Pipeline Stages

### Stage 1: COLLECT (`src/collect/`)

**Goal:** Cast a wide net. Pull raw items from all available public sources. Filter later.

**Typical output:** ~750 raw items.

#### Collectors

**API collectors (run in parallel via `asyncio.gather`):**

1. **Hansard** (`hansard.py`)
   - Searches UK Parliament's typed contribution endpoints (Spoken + Written)
   - 16 search terms: "RWE", "offshore wind", "energy security", "CfD", etc.
   - Resolves each contribution to a full URL via `ContributionExtId` redirect API
   - Gets full contribution text (not just snippets)
   - Items auto-verified (official API)
   - Rate limited: 0.3s delay between searches

2. **GOV.UK** (`govuk.py`)
   - Searches the GOV.UK search API (`/api/search.json`)
   - 13 queries filtered by department (DESNZ) and topic
   - Filters to last 14 days by `public_timestamp`
   - Items auto-verified (official API)
   - Rate limited: 0.3s delay between searches

3. **Parliament** (`parliament.py`) — Additional parliamentary data endpoints

4. **RSS** (`rss.py`) — RSS feed collector for trade press and media

**Claude-powered collectors (sequential):**

5. **Two-pass web search** (`web_search.py`)
   - **7 theme-based queries** generated from client config (one per monitoring theme + forward_scan)
   - **Pass 1:** Claude Sonnet with `web_search` tool finds URLs and snippets
   - **Page fetch:** Top 5 URLs fetched via httpx, parsed with BeautifulSoup (strips nav/footer/script/style/header/aside, extracts `<article>` or `<main>` or `<body>` text, up to 5000 chars)
   - **Pass 2:** Full page text sent to Claude Sonnet with factuality-focused prompt: "extract every significant finding, 200-500 words each, ONLY facts from the source text"
   - **Fallback:** If page fetch or Pass 2 fails, falls back to Pass 1 snippets
   - Forward scan items get `source_type: "forward_scan"` for later separation

#### Standard item format

Every collector produces items in this format:

```python
{
    "source_type": "hansard" | "govuk" | "web" | "forward_scan" | "rss",
    "title": str,
    "date": "YYYY-MM-DD",
    "url": str,
    "content": str,              # Source text, 200-8000 chars after enrichment
    "source_name": str,          # e.g. "Hansard, House of Lords", "GOV.UK DESNZ"
    "keywords_matched": [str],
    "relevance_score": 0.0,      # Set to 0 here, computed in Stage 2
    "verified": bool,            # True for API sources, checked for web sources
    "fingerprint": str,          # SHA256[:12] of url:title — unique item identifier
}
```

#### Retry

All API calls wrapped in `retry_api_call` / `retry_async_call` (`utils/retry.py`):
- 3 retries with exponential backoff (1s, 2s, 4s)
- Catches: `RateLimitError`, `APIConnectionError`, `InternalServerError`, `ConnectError`, `ReadTimeout`, `WriteTimeout`, `PoolTimeout`, `ConnectionError`, `TimeoutError`

#### Integration (`collect/__init__.py`)

```python
async def collect_all(config, week_start, anthropic_api_key) -> list[dict]:
    # 1. Parallel: Hansard + GOV.UK + Parliament + RSS via asyncio.gather
    # 2. Sequential: Two-pass web search (replaces old web search + forward scan)
    # 3. Merge all results
    # Returns ~750 raw items
```

---

### Stage 2: SCORE & FILTER (`src/score/`)

**Goal:** Distill ~750 raw items to the 100 most relevant.

#### Pipeline (`score/__init__.py`)

```python
async def score_and_filter(items, config, min_score=0.08, max_items=100) -> list[dict]:
    # 1. Score all items                    (keyword_scorer.py)
    # 2. Filter by min_score (0.08)
    # 3. Deduplicate                        (dedup.py)
    # 4. Verify source URLs                 (source_verifier.py)
    # 5. Enrich top items with full content (content_enricher.py)
    # 6. Sort by relevance_score descending
    # 7. Cap at max_items (100)
```

#### Step 1: Keyword scoring (`keyword_scorer.py`)

Each item gets a 0-1 relevance score:

| Signal | Weight | Max |
|--------|--------|-----|
| General keyword matches (all 7 groups) | 0.06 per match | 0.5 |
| Client-specific keyword matches | 0.1 per match | 0.2 |
| Source quality (Hansard/GOV.UK) | flat bonus | 0.1 |
| Trade press source | flat bonus | 0.05 |
| Recency (last 7 days) | flat bonus | 0.1 |
| **Total** | | **1.0** |

`flatten_keywords` normalises: lowercase, strip quotes, split on AND/OR, skip terms < 3 chars.

The `min_score` threshold of 0.08 is deliberately low — better to over-include than miss a relevant item.

#### Step 2: Filter

Items below 0.08 are dropped.

#### Step 3: Deduplication (`dedup.py`)

Removes duplicates by:
- Normalised URL (lowercase, strip trailing slash)
- Normalised title (first 60 alphanumeric chars, lowercase)

Sorted by score descending first, so the highest-scored version of each duplicate is kept.

#### Step 4: Source verification (`source_verifier.py`)

- HEAD requests each URL (10 concurrent, 5s timeout)
- Hansard/GOV.UK items auto-verified
- Failed items keep `verified: false` but are not removed — they just won't be enriched

#### Step 5: Content enrichment (`content_enricher.py`)

Fetches full HTML pages for the top 25 verified non-API items:
- Skips: empty URL, unverified, Hansard/GOV.UK (already have structured content), PDFs
- Uses BeautifulSoup: strips nav/footer/script/style/header/aside, extracts `<article>` or `<main>` or `<body>` text
- Replaces snippet with up to 8000 chars of article text if > 200 chars extracted
- Sets `content_enriched: true` flag
- 8 concurrent fetches

This is the second layer of enrichment after the two-pass web search. Items already enriched by Pass 2 may get additional content here.

#### Output

Cached to `output/items_YYYY-MM-DD.json`. Pipeline can be re-run with `--from-cache` to skip collection and scoring.

---

### Stage 3: ANALYSE (`src/analyse/`)

**Goal:** Produce the structured `analysis.json` that drives the report.

#### 3a. Item routing (`theme_analyser.py:route_items_to_themes`)

Each item is assigned to exactly one monitoring theme (cross-theme deduplication).

**Routing priority:**
1. **Source type match** (definitive): Hansard -> parliamentary, GOV.UK -> policy_government
2. **Best keyword match count**: Count keyword hits per theme, assign to theme with most hits, tie-broken by priority order
3. **Fallback**: Unmatched web/RSS items with score >= 0.15 -> media_coverage; other unmatched -> policy_government

**Theme priority order** (most specific first):
```
parliamentary > policy_government > regulatory_legal > stakeholder_third_party >
competitor_industry > social_media > media_coverage
```

`media_coverage` is last because it's the catch-all.

**Keyword sources per theme:**

| Theme | Source types | Keyword sources |
|-------|-------------|-----------------|
| policy_government | govuk | "desnz", "clean power", "cfd", "ar7", "energy security", etc. |
| parliamentary | hansard | "hansard", "debate", "committee", "question", "edm", etc. |
| regulatory_legal | — | "ofgem", "neso", "crown estate", "planning", "dco", etc. |
| media_coverage | — | Populated from config `media_specialist` + `media_national` + `media_regional` |
| social_media | — | "social media", "twitter", "linkedin", "viral", etc. |
| competitor_industry | — | Populated from config `competitors` keywords + `industry` source names |
| stakeholder_third_party | — | "ngo", "campaign", "protest", "community", etc. |

#### 3b. Two-pass theme analysis

**Pass 1: Fact extraction (Haiku — fast, cheap)**

For each theme, the first 30 items are sent to Haiku with forced `tool_use`:

```python
# Tool definition
EXTRACT_FACTS_TOOL = {
    "name": "extract_facts",
    "input_schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fingerprint": {"type": "string"},  # Copied from source item
                        "who": {"type": "string"},           # People/organisations involved
                        "what": {"type": "string"},          # What happened (1-2 sentences)
                        "when": {"type": "string"},          # Specific date/timeframe
                        "numbers": {"type": "string"},       # MW, £, percentages, dates
                        "type": {"type": "string"},          # announcement|debate|question|etc
                    },
                },
            },
        },
        "required": ["facts"],
    },
}

# Forced tool call
tool_choice={"type": "tool", "name": "extract_facts"}
```

This is pure extraction — no interpretation. The `fingerprint` links each fact back to its source item.

**Pass 2: Theme analysis (Sonnet — balanced)**

Sonnet receives:
- Extracted facts from Pass 1
- Full source content (up to 3000 chars per item, first 30 items)
- Client context (projects with names, capacities, locations, priorities, escalation triggers)
- Theme-specific instructions
- Strict factuality rules, specificity examples, confidence calibration scale

Output via forced `tool_use` to `submit_analysis`:

```python
{
    "items": [{
        "ref": "2.1.1",                          # Section reference (e.g. "2.1.1", "2.1.2")
        "headline": str,                          # Concise title
        "date": str,                              # Event/publication date
        "source": str,                            # e.g. "GOV.UK press release, DESNZ"
        "summary": str,                           # 2-4 sentences. Facts only.
        "client_relevance": str,                  # 2-3 sentences. Specific to THIS client.
        "recommended_action": str,                # e.g. "Brief client", "Prepare response"
        "escalation": "IMMEDIATE"|"HIGH"|"STANDARD",
        "rag": "RED"|"AMBER"|"GREEN",
        "confidence": float,                      # 0-1 calibrated score
        "source_items": [str],                    # Fingerprints linking to collected items
    }],
    "no_developments": bool,
    # Theme-specific fields (varies by theme):
    "routine_mentions": [...],                    # parliamentary only
    "coverage_table": [...],                      # media_coverage only
    "significant_items": [...],                   # media_coverage only
    "table": [...],                               # competitor_industry only
    "summary": str,                               # social_media only
    "metrics": {...},                             # social_media only
    "notable_posts": [...],                       # social_media only
}
```

**Key prompt engineering decisions:**

1. **Factuality rules** (in ANALYSIS_PROMPT):
   - "Your summary MUST only contain facts stated in the extracted facts or source item content"
   - "Do NOT add context from your own knowledge"
   - "Do NOT attribute statements to specific people or organisations unless the source explicitly names them"
   - "Do NOT name government departments as the source of an announcement unless the source text explicitly states which department made it"
   - "If a source snippet is ambiguous or incomplete, say so rather than filling in details"

2. **Specificity examples** (BAD vs GOOD):
   - BAD: "This is relevant to offshore wind developers as it affects project economics."
   - GOOD: "This directly impacts RWE's Norfolk Vanguard East and West projects (3.1GW combined), which are targeting FID in summer 2026."

3. **Confidence calibration** (explicit scoring scale):
   - 0.9-1.0: Government press release, official announcement, Hansard record
   - 0.8-0.89: Named source in reputable outlet, multiple corroborating sources
   - 0.7-0.79: Single trade press report, plausible but unconfirmed
   - 0.5-0.69: Vague source, partial information
   - Below 0.5: Speculative, rumour, very thin sourcing

4. **Source provenance rule**: "Every item MUST include source_items with at least one fingerprint. Items with empty source_items will be automatically removed."

#### 3c. Synthesis (Opus + extended thinking)

All theme results are fed to Opus with extended thinking:

```python
response = anthropic_client.messages.create(
    model="claude-opus-4-6",
    max_tokens=20000,
    thinking={"type": "enabled", "budget_tokens": 16000},
    messages=[{"role": "user", "content": prompt}],
)
```

**API constraint:** Extended thinking cannot be combined with forced `tool_use`. So the synthesis outputs text-based JSON, and markdown code fences are stripped with regex before parsing.

The synthesis produces 5 cross-cutting sections:

1. **Executive Summary**
   - `top_line`: 3-5 sentences. "If you had 30 seconds in a lift with the client, what would you say?"
   - `key_developments`: 4-6 most significant items across ALL themes. Each has: `rag`, `development`, `relevance`, `recommended_action`, `section_ref` (cross-reference to theme item), `confidence`

2. **Forward Look**
   - Array of upcoming events/milestones in next 2-4 weeks
   - Each: `date`, `event`, `relevance`, `preparation`
   - Sourced from forward_scan items collected earlier

3. **Emerging Themes**
   - 2-4 paragraphs stepping back from individual items
   - Broader patterns: political mood shifts, stakeholder activity changes, policy windows opening/closing

4. **Actions Tracker**
   - Derived actions with: `ref`, `action`, `owner`, `deadline`, `origin`, `status`

5. **Coverage Summary**
   - Media metrics table: total mentions, national/trade/social/parliamentary mentions, competitor share of voice
   - Each: `metric`, `this_week`, `previous_week`, `trend` (with unicode arrows)

**Fallback handling:**
- Missing keys get safe defaults via `_default_for()`
- Complete failure returns `_fallback_synthesis()` with placeholder text

#### 3d. Post-analysis checks (`analyse/__init__.py`)

After theme analyses and synthesis complete:

1. **Strip items with empty source_items**: Removes any analysed item that has no provenance (empty `source_items` array).

2. **Citation verification**: Every fingerprint in `source_items` is checked against the set of collected items. Broken citations:
   - Add `citation_warnings` to the item
   - Reduce confidence by 0.2 (min 0.3)
   - Log warnings

3. **Section structure enforcement**: Ensures all 7 themes exist with their required keys, filling defaults for missing themes.

4. **Schema validation**: Validates the full `analysis.json` against the JSON schema. Logs errors but does not block.

#### Output

Saved to `output/analysis_YYYY-MM-DD.json`.

---

### Stage 4: EVALUATE (`src/evaluate/`)

**Goal:** Quality gate. Three independent checks determine overall pass/fail.

#### 4a. Template validation (`template_validator.py`)

Deterministic, no LLM calls. ~30 structural rules:

**Errors (hard fail):**
- Executive summary missing or empty top_line
- key_developments count outside 4-6 (< 4 is error, > 6 is warning)
- key_developments missing required fields (rag, development, relevance, recommended_action, section_ref)
- Invalid RAG values (must be RED, AMBER, or GREEN)
- Section cross-references don't resolve (supports compound refs like "2.1.1 / 2.4.1 / 2.6.1" — splits on ` / `, passes if any individual ref exists)
- Required theme sections missing
- Item cards missing required fields (ref, headline, date, source, summary, client_relevance, recommended_action)
- Invalid escalation values
- Empty source_items (no provenance)
- Forward look empty
- Emerging themes count outside 2-4 (< 2 is error, > 4 is warning)
- Actions tracker or coverage summary missing

**Warnings (informational):**
- Summary sentence count outside 2-4 (< 2 or > 6)
- Client relevance sentence count < 2
- Confidence uncalibrated (exactly 0.0 or 1.0) or missing
- Routine mentions missing fields
- Coverage table missing fields
- Empty section without no_developments flag

#### 4b. Factuality check (`judge.py:run_factuality_check`)

For each analysed item, builds a case:
- **input**: Concatenated source content from items referenced in `source_items` (looked up by fingerprint from the items cache)
- **output**: The item's `summary` field ONLY (not `client_relevance`)

Sends each case to Opus with forced `tool_use`:

```python
SUBMIT_SCORE_TOOL = {
    "name": "submit_score",
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
        "required": ["score", "reason"],
    },
}

# Prompt:
"Score 0-1 how well the analysis is supported by the source material.
 1.0 = fully supported, 0.0 = completely fabricated."
```

Items scoring below 0.7 are flagged.

**Critical design: factuality evaluates only `summary`, NOT `client_relevance`.** The summary must be grounded in sources. The client_relevance is expected to add client-specific context (project names, capacities) that isn't in the source material. If you evaluate both fields together, factuality and specificity fight each other — this was a real bug we fixed.

Returns per-item details (score, reason, source/output text) for debugging flagged items.

#### 4c. Specificity check (`judge.py:run_specificity_check`)

For each analysed item with a `client_relevance` field, sends the text plus client context to Opus:

```
Scoring rubric:
- 1.0: References specific projects by name (Norfolk Vanguard, Sofia), specific commercial positions
- 0.7: References sector position but not specific projects
- 0.4: Generic — could apply to any offshore wind developer
- 0.1: Completely generic — could apply to any energy company
```

Items scoring below 0.5 are flagged.

#### 4d. Overall pass/fail

```python
overall_pass = (
    template_result["passed"]              # 0 errors
    and factuality["mean_score"] > 0.7     # factuality threshold
    and specificity["mean_score"] > 0.5    # specificity threshold
)
```

All flagged refs are collected. The orchestrator reduces confidence of flagged items to max 0.5 and re-saves the analysis JSON, so the DOCX generator can render visual warnings.

**Debug output:** Flagged factuality items are printed with their score, reason, summary, and source text for manual inspection.

#### Output

Saved to `output/eval_YYYY-MM-DD.json`.

---

### Stage 5: GENERATE DOCX (`src/generate/`)

Node.js script (`generate-report.js`) using `docx-js`. Reads `analysis.json` and client config, produces a professional Word document.

Called via `subprocess.run` from the Python orchestrator:

```python
result = subprocess.run(
    ["node", "generate-report.js",
     "--analysis", str(analysis_path),
     "--config", config_path,
     "--output", str(report_path)],
    capture_output=True, text=True,
)
```

The analysis JSON is the only interface. The Node script has zero knowledge of how the analysis was produced.

---

## Orchestrator (`src/orchestrator.py`)

CLI arguments:

```
python src/orchestrator.py                              # Full run, current week
python src/orchestrator.py --week 2026-03-24            # Specific week
python src/orchestrator.py --from-cache output/items.json  # Skip collection
python src/orchestrator.py --config path/to/config.json    # Specific client
python src/orchestrator.py --collect-only               # Stop after collection
python src/orchestrator.py --skip-eval                  # Skip evaluation (faster dev)
```

Flow:
1. Load config, determine reporting period
2. Check ANTHROPIC_API_KEY
3. COLLECT (or load from cache)
4. SCORE & FILTER
5. Cache items
6. ANALYSE
7. Save analysis
8. EVALUATE (unless --skip-eval)
9. Save eval, update flagged item confidence, re-save analysis
10. GENERATE DOCX

Every stage logged with `=====` separators. Full pipeline traced as a single Opik span.

---

## Observability (Opik)

Every Claude API call is traced:

```python
@track(name="full_pipeline")          # orchestrator.py
@track(name="full_analysis")          # analyse/__init__.py
@track(name="fact_extraction")        # theme_analyser.py Pass 1
@track(name="theme_analysis")         # theme_analyser.py Pass 2
@track(name="synthesis")              # synthesiser.py
@track(name="full_evaluation")        # evaluate/__init__.py
@track(name="factuality_evaluation")  # judge.py
@track(name="specificity_evaluation") # judge.py
```

Opik self-hosted via Docker Compose at `localhost:5173`. Dashboard shows:
- Full pipeline traces with nested spans
- Token usage and cost per call
- LLM-as-judge scores
- Latency breakdowns

---

## Retry Strategy (`src/utils/retry.py`)

Two helpers: `retry_api_call` (sync) and `retry_async_call` (async).

```python
RETRIABLE_EXCEPTIONS = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    ConnectionError,
    TimeoutError,
)

# 3 retries, exponential backoff: 1s, 2s, 4s
retry_api_call(fn, *args, max_retries=3, backoff_base=1.0, **kwargs)
```

---

## Key Patterns and Lessons Learned

### 1. Two-pass analysis (extraction then interpretation)

Separating fact extraction (cheap model, structured output) from analysis (smarter model, richer prompt) improves both accuracy and cost. The extraction pass forces the model to identify what's in the source material before a second model interprets it.

### 2. Two-pass web search (search then fetch then re-extract)

Claude's web search returns snippets. Fetching the actual pages and re-extracting with a factuality-focused prompt gives 200-500 word grounded summaries instead of one-line snippets. This was the single biggest factuality improvement in the project: 0.76 -> 0.85.

### 3. Forced tool_use for structured output

Instead of asking the model to return JSON in text and parsing with regex, define a tool schema and force `tool_choice={"type": "tool", "name": "..."}`. The model must return structured data. Eliminates parsing failures entirely.

**Exception:** Extended thinking cannot be combined with forced tool_use. For those calls (synthesis), use text-based JSON with regex code fence stripping.

### 4. Split evaluation scopes

If you have two quality dimensions that conflict, evaluate them on different fields. Summary gets judged for factuality (must be grounded in sources). Client_relevance gets judged for specificity (must reference specific projects). They never fight.

This was a real bug: when both fields were evaluated together for factuality, client_relevance text (which adds project names not in sources) was penalised, dragging factuality from 0.93 to 0.43.

### 5. Content enrichment at multiple layers

Don't rely on a single source of content:
- Layer 1: API responses give structured text
- Layer 2: Two-pass web search gives detailed extracts from full pages
- Layer 3: Post-scoring enrichment fetches full pages for top items

Each layer gives the analysis model more to work with. Short snippets cause the model to infer — inference gets flagged by the factuality judge.

### 6. Fingerprint-based provenance

Every collected item gets a SHA256[:12] fingerprint of `url:title`. Every analysed item must reference which fingerprints it used. Post-analysis:
- Broken fingerprints are detected and confidence is reduced
- Items with no fingerprints are stripped entirely

This creates an auditable chain from every claim in the report back to a specific source.

### 7. Cache intermediate outputs

The ability to re-run analysis from cached items (without re-collecting) saved enormous iteration time. Prompt engineering changes don't need 8 minutes of API collection each time.

### 8. Deterministic validation before LLM evaluation

Template validation catches structural issues (missing fields, wrong types) cheaply before spending money on Opus judge calls. This is your first line of defence.

---

## Cost and Runtime

Per run (run 6 actuals):

| Stage | Time | Cost | Notes |
|-------|------|------|-------|
| Collection (APIs) | ~2 min | £0.00 | HTTP calls only |
| Collection (web search, 7 themes x 2 passes) | ~8 min | ~£0.80 | 14 Sonnet calls |
| Score, filter, enrich | ~30 sec | £0.00 | HTTP calls only |
| Analysis (7 themes x 2 passes) | ~4 min | ~£0.60 | 7 Haiku + 7 Sonnet calls |
| Synthesis | ~2 min | ~£0.40 | 1 Opus call with extended thinking |
| Evaluation | ~6 min | ~£0.80 | ~40 Opus judge calls |
| DOCX generation | ~1 sec | £0.00 | Node.js |
| **Total** | **~23 min** | **~£2.60** | |

---

## Quality Scores Across Runs

| Run | Factuality | Specificity | Template | Overall | Key changes |
|-----|-----------|-------------|----------|---------|-------------|
| 1 | 0.93 | — | — | — | Baseline (Sonnet judge, inflated) |
| 2 | 0.43 | 0.69 | — | FAIL | Opus judge (strict), factuality+specificity conflict |
| 3 | 0.78 | 0.92 | — | PASS | Split eval scopes, enrichment expansion, prompt rules |
| 4 | 0.78 | 0.88 | PASS (0 err) | PASS | Compound refs fix, empty source_items filter |
| 5 | 0.76 | 0.90 | PASS (0 err) | PASS | Tightened factuality prompt (attribution rules) |
| 6 | 0.85 | 0.91 | 1 err | PASS* | Two-pass web search, BeautifulSoup enrichment |

*Run 6 template has 1 error (missing date on single item) — not a systemic issue.

---

## Adding a New Client

1. Create `src/config/newclient.json` following the structure above
2. Populate: client details, projects, keywords, sources, escalation triggers, monitoring themes
3. Run: `python src/orchestrator.py --config src/config/newclient.json`
4. No code changes required

The keywords are the most important part — they drive scoring quality. The projects are second — they drive specificity in the client_relevance text.

---

## Environment Setup

```bash
# Python dependencies
pip install -r requirements.txt

# Node.js dependencies (DOCX generator)
cd src/generate && npm install

# Opik dashboard (optional but recommended)
docker-compose up -d

# Environment variables
export ANTHROPIC_API_KEY=sk-ant-...
export OPIK_URL_OVERRIDE=http://localhost:5173/api  # If using Opik

# Run
python src/orchestrator.py --week 2026-03-23
```
