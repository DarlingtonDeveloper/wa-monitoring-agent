# Spec 00: Schema Contract

## Purpose

Define the `analysis.json` schema that sits between the Python pipeline and the Node.js DOCX generator. This is the single source of truth. Both sides build to this contract. Define it before writing any pipeline or generator code.

## Task

Create two JSON schema files:

### 1. `schemas/items.schema.json`

This is the output of the collection + scoring stage. Array of scored items cached to disk.

```
RawItem:
  source_type: string enum ["hansard", "govuk", "web"]
  title: string
  date: string (ISO 8601, e.g. "2026-03-26")
  url: string (verified URL)
  content: string (max 1000 chars, snippet or extract)
  source_name: string (e.g. "Hansard", "GOV.UK DESNZ", "Recharge News")
  keywords_matched: string[] (which keywords from the config matched)
  relevance_score: float 0-1
  verified: boolean (did the source URL resolve)
  fingerprint: string (dedup hash, 12 chars)
```

### 2. `schemas/analysis.schema.json`

This is the output of the analysis stage and the input to the DOCX generator. This is the critical contract.

```
AnalysisOutput:
  metadata:
    client_name: string
    reporting_period: string (e.g. "w/c 24 March 2026")
    report_date: string (e.g. "27 March 2026")
    generated_at: string (ISO 8601 timestamp)
    items_collected: integer
    items_scored: integer
    items_analysed: integer
    sources_unavailable: string[] (any sources that failed collection)

  executive_summary:
    top_line: string (3-5 sentences)
    key_developments: array of:
      rag: string enum ["RED", "AMBER", "GREEN"]
      development: string
      relevance: string
      recommended_action: string
      section_ref: string (e.g. "2.1.1")
      confidence: float 0-1

  sections: object with keys matching theme IDs:
    policy_government:
      items: array of AnalysedItem
    parliamentary:
      items: array of AnalysedItem
      routine_mentions: array of RoutineMention
    regulatory_legal:
      items: array of AnalysedItem
    media_coverage:
      coverage_table: array of MediaRow
      significant_items: array of AnalysedItem
    social_media:
      summary: string
      metrics:
        total_mentions: string
        sentiment_breakdown: string
        top_engagement_post: string
        trend_vs_previous: string
      notable_posts: array of AnalysedItem
    competitor_industry:
      table: array of CompetitorRow
    stakeholder_third_party:
      items: array of AnalysedItem
      no_developments: boolean (if true, render "No significant developments this week")

  forward_look: array of:
    date: string
    event: string
    relevance: string
    preparation: string

  emerging_themes: string[] (array of 2-4 paragraphs)

  actions_tracker: array of:
    ref: string (e.g. "001")
    action: string
    owner: string (default "[Name]")
    deadline: string
    origin: string (e.g. "Report w/c 24 March 2026")
    status: string enum ["Open", "DONE"]

  coverage_summary: array of:
    metric: string
    this_week: string
    previous_week: string (default "[Baseline TBC]" for first run)
    trend: string

Sub-schemas:

AnalysedItem:
  ref: string (e.g. "2.1.1")
  headline: string
  date: string
  source: string
  summary: string (2-4 sentences)
  client_relevance: string (2-3 sentences)
  recommended_action: string
  escalation: string enum ["IMMEDIATE", "HIGH", "STANDARD"]
  rag: string enum ["RED", "AMBER", "GREEN"]
  confidence: float 0-1
  source_items: string[] (fingerprints of RawItems this was derived from)

RoutineMention:
  date: string
  type: string (e.g. "WQ", "OQ", "Debate", "EDM", "Cttee")
  detail: string
  members: string
  significance: string enum ["Low", "Medium", "High"]

MediaRow:
  date: string
  outlet: string
  angle: string (own words summary, never verbatim headline)
  client_named: string (e.g. "Yes — positive" or "No — sector story")
  action: string enum ["Monitor", "Amplify", "Respond", "Correct"]

CompetitorRow:
  organisation: string
  development: string
  relevance: string
  action: string
```

## Acceptance criteria

- Both schema files pass JSON Schema Draft 2020-12 validation.
- Write a small Python validation function `validate_analysis(data: dict) -> list[str]` that returns a list of errors. Empty list = valid. This function is used by both the analysis stage (validate before writing) and the generator (validate before generating).
- Write a small Node.js validation function that does the same check before DOCX generation.
