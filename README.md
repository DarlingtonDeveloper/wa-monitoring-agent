# WA Monitoring Agent

Automated public affairs monitoring system for [WA Communications](https://www.wacomms.co.uk/). Produces weekly client monitoring briefings from public sources, replacing 3-4 hours of manual work per client per week.

The system runs overnight Sunday and delivers a draft DOCX report for consultant review by Monday morning.

## How it works

```
                     client_config.json
                            |
              +-------------+-------------+
              |             |             |
         Hansard API   GOV.UK Atom   Claude web
         + Parliament   feeds        search (14
         APIs + RSS    + direct      theme queries)
              |         sources           |
              +-------------+-------------+
                            |
                     Enrich thin items
                     (fetch full pages)
                            |
                     Score & filter
                     (two-tier keywords)
                            |
                  +---------+---------+
                  |         |         |
              Theme 1   Theme 2   Theme N  ... (7 themes)
              analysis  analysis  analysis
                  |         |         |
                  +---------+---------+
                            |
                     Cross-theme synthesis
                            |
                  +---------+---------+
                  |                   |
             Template          LLM-as-judge
             validator         (factuality +
                               specificity)
                  |                   |
                  +---------+---------+
                            |
                      Generate DOCX
                            |
                   Weekly_Report.docx
```

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (for Opik dashboard)
- Anthropic API key

### Installation

```bash
git clone https://github.com/DarlingtonDeveloper/wa-monitoring-agent.git
cd wa-monitoring-agent

# Python dependencies
pip install -r requirements.txt

# Node.js dependencies (DOCX generator)
cd src/generate && npm install && cd ../..

# Environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### Start Opik (tracing dashboard)

```bash
cd /tmp && git clone --depth 1 --sparse https://github.com/comet-ml/opik.git
cd opik && git sparse-checkout set deployment/docker-compose
cd deployment/docker-compose && docker compose --profile opik up -d
```

Dashboard: http://localhost:5173

### Run the pipeline

```bash
# Full run for current week
python3 src/orchestrator.py

# Specific week
python3 src/orchestrator.py --week 2026-03-23

# Skip collection (use cached items)
python3 src/orchestrator.py --from-cache output/items_2026-03-23.json

# Collection only (no analysis/report)
python3 src/orchestrator.py --collect-only

# Skip evaluation (faster iteration)
python3 src/orchestrator.py --skip-eval

# Specific client config
python3 src/orchestrator.py --config src/config/rwe_client.json
```

### Output

All artefacts go to `output/`:

| File | Description |
|------|-------------|
| `raw_items_YYYY-MM-DD.json` | All collected items before scoring |
| `items_YYYY-MM-DD.json` | Scored and filtered items (top 150) |
| `analysis_YYYY-MM-DD.json` | Claude analysis output |
| `eval_YYYY-MM-DD.json` | Quality evaluation results |
| `Client_Weekly_Report_YYYY-MM-DD.docx` | Final report |

## Architecture

### Pipeline stages

| Stage | Module | What it does |
|-------|--------|-------------|
| 1. Collect | `src/collect/` | Pull items from 7 source types in parallel |
| 1b. Enrich | `src/collect/content_enricher.py` | Fetch full page content for thin items (<500 chars) |
| 2. Score & filter | `src/score/` | Two-tier keyword scoring, dedup, verify URLs |
| 3. Analyse | `src/analyse/` | Per-theme Claude analysis + cross-theme synthesis |
| 4. Evaluate | `src/evaluate/` | Template validation + LLM-as-judge quality checks |
| 5. Generate | `src/generate/` | Populate DOCX from analysis.json (Node.js) |

### Data sources

**Structured APIs** (parallel):
- **Hansard** - Parliamentary debates, questions, statements
- **GOV.UK Atom feeds** - 10 department/topic feeds (DESNZ, Ofgem, energy policy, planning)
- **Parliament APIs** - EDMs, written questions, committee transcripts
- **RSS feeds** - Trade media (Recharge, Windpower Monthly, etc.)
- **Committees** - Select committee evidence sessions
- **Direct sources** - Priority organisation websites (Ofgem, NESO, Crown Estate, Energy UK, RenewableUK, OEUK, ORE Catapult, CCC, GBE, NSTA)

**Claude web search** (sequential, 14 theme queries):
- Pass 1: Claude finds URLs via web search (Haiku)
- Pass 2: Fetch pages, Claude extracts findings (Sonnet)

### Scoring

Two-tier keyword scoring with source-awareness:

| Condition | Score |
|-----------|-------|
| **Tier 1**: Client named (e.g. "RWE", project names) | 0.5 - 1.0 |
| **Tier 2**: 2+ sector keywords + actionable signal | 0.10 - 0.45 |
| **Tier 2 alt**: 4+ sector keywords (no signal needed) | 0.10 - 0.35 |
| Priority source (Ofgem, NESO, etc.) | floor 0.20 |
| Hansard (always relevant) | floor 0.12 |
| Below threshold | 0.05 (filtered at 0.08) |

Additional hard filters: date window, UK geography, false positive rules.

### Analysis themes

Items are routed to 7 monitoring themes based on source type and content:

1. **Policy & Government** - DESNZ announcements, consultations, CfD rounds
2. **Parliamentary** - Debates, PQs, committee hearings, EDMs
3. **Regulatory & Legal** - Ofgem decisions, NESO, planning, Crown Estate
4. **Media Coverage** - Trade and national press
5. **Social Media** - (placeholder for future)
6. **Competitor & Industry** - Peer companies, industry body publications
7. **Stakeholder & Third Party** - NGOs, community groups, unions

### Model strategy

| Task | Model | Reasoning |
|------|-------|-----------|
| Web search (pass 1) | Haiku 4.5 | Fast, cheap URL discovery |
| Fact extraction | Haiku 4.5 | Structured extraction from source text |
| Theme analysis | Sonnet 4 | Nuanced interpretation and synthesis |
| Cross-theme synthesis | Sonnet 4 | Executive summary, emerging themes |
| Web search (pass 2) | Sonnet 4 | Detailed finding extraction |
| Factuality judge | Opus 4.6 | Highest accuracy for quality checks |
| Specificity judge | Opus 4.6 | Highest accuracy for relevance scoring |

### Quality evaluation

Three checks run before DOCX generation:

1. **Template validation** - Schema compliance (required fields, types, lengths)
2. **Factuality check** - LLM-as-judge compares each summary against source text (0-1 score, flag < 0.7)
3. **Specificity check** - LLM-as-judge evaluates relevance to client context (0-1 score, flag < 0.5)

Items flagged by either check get confidence scores reduced in the DOCX. Overall pass requires: template pass + factuality > 0.7 + specificity > 0.5.

### Opik tracing

Every Claude API call is traced via Opik `@track` decorators. The dashboard at http://localhost:5173 shows:

- Full pipeline spans with timing
- Per-call token usage and cost
- LLM-as-judge scores per item
- Error rates and retry counts

## Client configuration

All client-specific logic lives in a JSON config file. Nothing is hardcoded to any client.

```
src/config/rwe_client.json
```

Key sections:

| Section | Purpose |
|---------|---------|
| `client` | Name, sector, country, report display name |
| `projects` | Active projects with capacity, status, priority |
| `keywords` | Grouped keyword lists (corporate, policy, offshore wind, competitors, parliamentary, social, financial, gas) |
| `false_positive_rules` | Patterns to exclude (e.g. "RWE" in pharma context) |
| `monitoring_themes` | 7 theme IDs that drive routing and analysis |
| `escalation` | Priority levels (IMMEDIATE / HIGH / STANDARD) with trigger conditions |
| `sources` | Source URLs and types for each collector |
| `report` | Report metadata (company name, confidentiality, authors) |

To add a new client, copy `rwe_client.json`, update the fields, and pass `--config path/to/new_client.json`.

## Project structure

```
wa-monitoring-agent/
├── src/
│   ├── orchestrator.py            # Main pipeline (entry point)
│   ├── config/
│   │   └── rwe_client.json        # Client config
│   ├── collect/
│   │   ├── __init__.py            # collect_all() — runs all collectors
│   │   ├── hansard.py             # Hansard API
│   │   ├── govuk.py               # GOV.UK Atom feeds (feedparser)
│   │   ├── parliament.py          # Parliament APIs (EDMs, PQs)
│   │   ├── rss.py                 # RSS/Atom trade media feeds
│   │   ├── committees.py          # Select committee scraper
│   │   ├── direct_sources.py      # Priority org website scraper
│   │   ├── web_search.py          # Claude two-pass web search
│   │   ├── forward_scan.py        # Future events collector
│   │   └── content_enricher.py    # Fetch full pages for thin items
│   ├── score/
│   │   ├── __init__.py            # score_and_filter() pipeline
│   │   ├── keyword_scorer.py      # Two-tier scoring + filters
│   │   ├── dedup.py               # Fingerprint deduplication
│   │   └── source_verifier.py     # URL HEAD check verification
│   ├── analyse/
│   │   ├── __init__.py            # analyse() — themes + synthesis
│   │   ├── theme_analyser.py      # Per-theme Claude analysis
│   │   └── synthesiser.py         # Cross-theme synthesis
│   ├── generate/
│   │   ├── generate-report.js     # DOCX generator (Node.js)
│   │   └── package.json
│   ├── evaluate/
│   │   ├── __init__.py            # evaluate_report() entry
│   │   ├── template_validator.py  # Schema compliance
│   │   └── judge.py               # LLM-as-judge (Opus)
│   └── utils/
│       └── retry.py               # Exponential backoff for API calls
├── schemas/
│   ├── analysis.schema.json       # Python-to-Node contract
│   └── items.schema.json          # Scored items schema
├── scripts/
│   ├── test_feeds.py              # Verify GOV.UK Atom feeds
│   ├── trace_missing.py           # Trace items through pipeline
│   └── score_urls.py              # Score specific URLs
├── specs/                         # Build specifications
├── output/                        # Generated artefacts (gitignored)
├── requirements.txt
├── package.json
└── .env.example
```

## Diagnostic scripts

```bash
# Test all GOV.UK Atom feeds and search for known items
python3 scripts/test_feeds.py

# Trace specific items through collection and scoring
python3 scripts/trace_missing.py

# Score specific URLs with full content breakdown
python3 scripts/score_urls.py
```

## Key design decisions

- **Multi-client**: All client context comes from config JSON. Zero hardcoding.
- **Source provenance**: Every claim in the output references which source item it came from via fingerprint.
- **Confidence scoring**: 0-1 float per claim. Below 0.7 gets flagged in the DOCX with an inline marker.
- **Enrich before scoring**: GOV.UK Atom feed summaries are thin (200-300 chars). Full page content is fetched before keyword scoring runs, so items aren't filtered out due to thin content.
- **analysis.json contract**: Strict JSON schema shared between Python (producer) and Node.js (consumer). Both sides validate against it.
- **Tiered models**: Haiku for bulk extraction, Sonnet for analysis, Opus for quality evaluation. Balances cost vs accuracy.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude calls |
| `OPIK_URL_OVERRIDE` | No | Opik API endpoint (default: `http://localhost:5173/api`) |
| `OPIK_WORKSPACE` | No | Opik workspace name (default: `default`) |
| `OPIK_PROJECT_NAME` | No | Opik project name (default: `wa-monitoring-agent`) |

## License

Proprietary. WA Communications internal use only.
