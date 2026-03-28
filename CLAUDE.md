# WA Monitoring Agent — Claude Code Build Specs

## Overview

You are building an automated public affairs monitoring system for WA Communications, a Westminster lobbying firm. It produces a weekly client monitoring briefing from public sources, replacing 3-4 hours of manual work per client per week.

The system runs overnight Sunday and delivers a draft DOCX report for consultant review by Monday morning.

**This weekend's deliverable**: a working end-to-end system for the RWE Renewables client, with built-in quality evaluation via Opik, demonstrable to WA's CEO on Monday.

---

## Architecture

```
client_config.json
       │
       ▼
┌─────────────┐     ┌─────────────┐     ┌──────────────┐
│  Hansard API │     │  GOV.UK API │     │ Claude web   │
│  collector   │     │  collector  │     │ search       │
└──────┬───────┘     └──────┬──────┘     └──────┬───────┘
       └───────────────────┬┘───────────────────┘
                           │
                    ┌──────▼──────┐
                    │  Score,     │
                    │  filter,    │──► items.json (cached)
                    │  verify     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────▼────┐ ┌────▼─────┐ ┌────▼─────┐
        │ Theme    │ │ Theme    │ │ Theme    │  ... (parallel)
        │ analysis │ │ analysis │ │ analysis │
        └─────┬────┘ └────┬─────┘ └────┬─────┘
              └────────────┼────────────┘
                           │
                    ┌──────▼──────┐
                    │  Synthesis  │──► analysis.json
                    │  call       │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Generate   │──► report.docx
                    │  DOCX       │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │                         │
        ┌─────▼─────┐           ┌──────▼──────┐
        │ Template  │           │ LLM-as-     │
        │ validator │           │ judge       │
        └─────┬─────┘           └──────┬──────┘
              └────────────┬───────────┘
                           │
                    ┌──────▼──────┐
                    │  Final      │──► flagged report.docx
                    │  output     │    + Opik dashboard
                    └─────────────┘
```

## Repository structure

```
wa-monitoring-agent/
├── CLAUDE.md                          # This file — project context for Claude Code
├── specs/                             # Build specs (these files)
│   ├── 00-schema.md
│   ├── 01-config.md
│   ├── 02-collect.md
│   ├── 03-score-filter.md
│   ├── 04-analyse.md
│   ├── 05-generate.md
│   ├── 06-evaluate.md
│   └── 07-orchestrator.md
├── src/
│   ├── config/
│   │   └── rwe_client.json            # Client config (RWE)
│   ├── collect/
│   │   ├── __init__.py
│   │   ├── hansard.py                 # Hansard API collector
│   │   ├── govuk.py                   # GOV.UK API collector
│   │   ├── web_search.py             # Claude web search collector
│   │   └── forward_scan.py           # Future events collector
│   ├── score/
│   │   ├── __init__.py
│   │   ├── keyword_scorer.py
│   │   ├── dedup.py
│   │   └── source_verifier.py
│   ├── analyse/
│   │   ├── __init__.py
│   │   ├── theme_analyser.py          # Per-theme analysis calls
│   │   └── synthesiser.py            # Cross-theme synthesis
│   ├── generate/
│   │   ├── generate-report.js         # DOCX generator (Node.js)
│   │   └── package.json
│   ├── evaluate/
│   │   ├── __init__.py
│   │   ├── template_validator.py
│   │   └── judge.py                   # LLM-as-judge via Opik
│   └── orchestrator.py               # Main pipeline runner
├── schemas/
│   ├── items.schema.json
│   └── analysis.schema.json
├── output/                            # Generated artefacts per run
├── docker-compose.yml                 # Opik self-hosted
├── requirements.txt
└── package.json
```

## Tech stack

- **Python 3.11+**: pipeline, collection, analysis, evaluation
- **Node.js 18+**: DOCX generation only (docx-js)
- **Anthropic SDK**: Claude API calls for analysis and web search
- **Opik SDK**: tracing, LLM-as-judge metrics, cost tracking, dashboard
- **httpx**: async HTTP for API collection
- **Docker Compose**: Opik self-hosted

## Key constraints

- Multi-client from the start: nothing hardcoded to RWE. All client context comes from config JSON.
- Every Claude call traced via Opik `@track` decorator.
- Source provenance required: every claim in the output must reference which source item it came from.
- Confidence score per claim: 0-1 float, claims below 0.7 get flagged in the DOCX with an inline marker.
- analysis.json is the contract between Python and Node — both sides are built to the schema.

## Build order

1. `00-schema.md` — Define analysis.json schema (shared contract)
2. `01-config.md` — Client config structure
3. `02-collect.md` — Collection layer
4. `03-score-filter.md` — Scoring, filtering, verification
5. `04-analyse.md` — Claude analysis calls
6. `05-generate.md` — DOCX generator refactor
7. `06-evaluate.md` — Quality evaluation layer
8. `07-orchestrator.md` — Main pipeline + Opik setup

Build each spec in order. Each spec is self-contained with inputs, outputs, and acceptance criteria.
