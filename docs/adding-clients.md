# Adding a New Client

The system is multi-client by design. All client-specific logic lives in a JSON config file. To add a new client, create a new config and pass it to the pipeline.

## Steps

### 1. Copy the template

```bash
cp src/config/rwe_client.json src/config/new_client.json
```

### 2. Update client details

```json
{
  "client": {
    "name": "ClientName",
    "full_name": "Client Full Legal Name",
    "report_display_name": "Client Display Name",
    "sector": "Energy / Offshore Wind",
    "country": "United Kingdom"
  }
}
```

`report_display_name` appears in the DOCX header and filename. `name` is used in prompts and logging.

### 3. Define projects

```json
{
  "projects": [
    {
      "name": "Project Name",
      "type": "Offshore Wind",
      "capacity_mw": 1400,
      "status": "Under Construction",
      "location": "North Sea",
      "notes": "Brief context for the analyst",
      "priority": "HIGH PROFILE"
    }
  ]
}
```

Projects are included in Claude prompts as context. High-priority projects get more attention in analysis.

### 4. Configure keyword groups

Keywords drive the scoring engine. They're split into groups:

```json
{
  "keywords": {
    "client_corporate": [
      "Client Name",
      "\"exact phrase match\"",
      "Project Name One",
      "Project Name Two"
    ],
    "sector_keywords": [
      "offshore wind",
      "renewable energy",
      "grid connection"
    ],
    "competitors": [
      "Competitor A",
      "Competitor B"
    ],
    "parliamentary": [
      "select committee keyword",
      "PQ topic"
    ]
  }
}
```

The first keyword group (matching the pattern `*_corporate`) is treated as **Tier 1** (client-named, score 0.5+). All other groups are **Tier 2** (sector, capped at 0.45).

Keywords support:
- Exact phrases in quotes: `"offshore wind farm"`
- AND/OR operators: `"wind AND farm"` (split into separate terms)
- Minimum 3 characters (shorter terms are skipped)

### 5. Set false positive rules

```json
{
  "false_positive_rules": [
    {
      "term": "ClientName",
      "exclude_if_context": ["unrelated industry term"],
      "require_context": ["energy", "wind", "power"]
    }
  ]
}
```

### 6. Configure monitoring themes

The default 7 themes work for most energy sector clients:

```json
{
  "monitoring_themes": [
    "policy_government",
    "parliamentary",
    "regulatory_legal",
    "media_coverage",
    "social_media",
    "competitor_industry",
    "stakeholder_third_party"
  ]
}
```

### 7. Set escalation levels

```json
{
  "escalation": {
    "immediate": ["Client mentioned in Parliament", "Regulatory decision affecting client"],
    "high": ["Major sector policy change", "Competitor acquisition"],
    "standard": ["Routine mentions", "Industry statistics"]
  }
}
```

### 8. Configure sources

```json
{
  "sources": {
    "programmatic": ["Hansard API", "GOV.UK Atom feeds"],
    "web_search": ["Ofgem", "NESO", "Crown Estate"],
    "media_specialist": ["Trade Publication 1", "Trade Publication 2"],
    "media_national": ["Financial Times", "Guardian", "BBC"],
    "industry_bodies": ["Industry Body 1", "Industry Body 2"]
  }
}
```

### 9. Run the pipeline

```bash
python3 src/orchestrator.py --config src/config/new_client.json --week 2026-03-23
```

## What changes per client

| Component | Per-client? | Notes |
|-----------|-------------|-------|
| Config JSON | Yes | Everything client-specific |
| Collectors | No | Same sources, config drives filtering |
| Keyword scorer | No | Reads keywords from config |
| Theme analyser | No | Config provides project context to prompts |
| DOCX generator | No | Reads report metadata from config |
| Evaluator | No | Judges against client context from config |

## Testing a new config

```bash
# Collect only (fastest feedback loop)
python3 src/orchestrator.py --config src/config/new_client.json --collect-only

# Check scored items
python3 -c "
import json
with open('output/items_2026-03-23.json') as f:
    items = json.load(f)
print(f'Total: {len(items)}')
for item in items[:10]:
    print(f\"  {item['relevance_score']:.2f} | {item['title'][:60]}\")
"
```
