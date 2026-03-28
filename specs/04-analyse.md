# Spec 04: Analysis Layer

## Purpose

Take scored items and produce the structured analysis that fills the report. Two-stage approach: per-theme analysis calls (parallelised), then a synthesis call that produces the executive summary, forward look, and emerging themes from the theme outputs.

Every call is traced via Opik `@track` decorator.

## Source files

- `src/analyse/theme_analyser.py`
- `src/analyse/synthesiser.py`
- `src/analyse/__init__.py` (exports `analyse` function)

## Shared context block

Both the theme analyser and synthesiser need the client context. Build it once from the config:

```python
def build_client_context(config: dict) -> str:
    """
    Render the client config into a concise text block for inclusion
    in analysis prompts. Include: client name, sector, key projects
    (name, capacity, status, priority), key policy areas.
    Keep under 2000 tokens.
    """
```

## 1. Theme analyser (`theme_analyser.py`)

For each monitoring theme, run a Claude call with only the items relevant to that theme.

### Routing items to themes

Before calling Claude, pre-route items to themes based on `source_type` and keyword matches:

```python
THEME_ROUTING = {
    "policy_government": {
        "source_types": ["govuk"],
        "keywords": ["DESNZ", "clean power", "CfD", "AR7", "AR8", "energy security",
                      "consultation", "policy", "minister", "announcement"],
    },
    "parliamentary": {
        "source_types": ["hansard"],
        "keywords": ["Hansard", "debate", "committee", "question", "EDM", "APPG",
                      "Parliament", "Commons", "Lords"],
    },
    "regulatory_legal": {
        "keywords": ["Ofgem", "NESO", "Crown Estate", "planning", "DCO", "NSIP",
                      "RIIO", "TNUoS", "grid connection", "seabed lease"],
    },
    "media_coverage": {
        "keywords": config["sources"]["media_specialist"] +
                    config["sources"]["media_national"] +
                    config["sources"]["media_regional"],
    },
    "competitor_industry": {
        "keywords": flatten_keywords(config["keywords"]["competitors"]) +
                    [s["name"] for s in config["sources"].get("industry", [])],
    },
    "stakeholder_third_party": {
        "keywords": ["NGO", "campaign", "protest", "community", "union",
                      "academic", "petition", "FOI", "activist"],
    },
}
```

Items can appear in multiple themes. Items that match no theme get assigned to the closest theme by keyword overlap or dropped if relevance_score < 0.15.

Forward scan items (`source_type: "forward_scan"`) are collected separately — they go to the synthesiser, not the theme analysers.

### Per-theme prompt

```python
THEME_PROMPT = """You are a senior public affairs analyst at {consultancy_name}, a Westminster lobbying and public affairs firm.

CLIENT CONTEXT:
{client_context}

MONITORING THEME: {theme_label} (Section {section_number})

ITEMS TO ANALYSE:
{items_text}

For each significant item, produce a JSON object with:
- ref: section reference (e.g. "{section_number}.1", "{section_number}.2")
- headline: concise title
- date: DD/MM/YYYY
- source: where this came from (e.g. "GOV.UK press release, DESNZ" or "Hansard, House of Lords")
- summary: 2-4 sentences. What happened. Plain English, precise about dates, names, amounts.
- client_relevance: 2-3 sentences. Why this matters to {client_name} SPECIFICALLY — reference specific projects, commercial positions, or pipeline impacts. Do not write generic analysis that could apply to any energy company.
- recommended_action: specific action (e.g. "Brief client", "Prepare consultation response", "Monitor", "Amplify via media")
- escalation: "IMMEDIATE" | "HIGH" | "STANDARD"
- rag: "RED" | "AMBER" | "GREEN"
- confidence: float 0-1. How confident are you that your summary accurately represents the source material? Lower this if the source snippet is ambiguous, if you're inferring rather than reporting, or if the claim would need verification.
- source_items: array of fingerprint strings from the items that support this analysis

{theme_specific_instructions}

RULES:
- Summarise, never reproduce source text. Always own words with attribution.
- Do not editorialise or offer political opinion. Facts and analysis only.
- Every item must answer: What happened? Why does it matter to THIS client? What should we do?
- If nothing significant occurred in this theme, return an empty items array.

Return ONLY a JSON object: {{"items": [...], "no_developments": true/false}}
"""
```

**Theme-specific instructions** (appended per theme):

- `parliamentary`: "Also produce a `routine_mentions` array for lower-significance parliamentary references. Each: {date, type, detail, members, significance}."
- `media_coverage`: "Produce a `coverage_table` array: {date, outlet, angle (own words — never the original headline), client_named, action}. Elevate significant stories to full item cards in `significant_items`."
- `competitor_industry`: "Produce a `table` array: {organisation, development, relevance, action}."
- `social_media`: "Produce `summary` (paragraph), `metrics` object {total_mentions, sentiment_breakdown, top_engagement_post, trend_vs_previous}, and `notable_posts` array. Note: quantitative metrics are approximate without platform API access — flag this."
- `stakeholder_third_party`: "If nothing notable, set `no_developments: true`."

### Parallelisation

Run theme calls concurrently using `asyncio.gather` (or sequential — overnight batch, speed doesn't matter much, but parallel is cleaner). Use the Anthropic Python SDK's synchronous client in threads, or use multiple sequential calls.

```python
@track(name="theme_analysis")
def analyse_theme(
    theme_id: str,
    theme_config: dict,
    items: list[RawItem],
    client_context: str,
    config: dict,
    anthropic_client: anthropic.Anthropic,
) -> dict:
    """
    Build prompt, call Claude, parse JSON response.
    Model: claude-sonnet-4-20250514
    Max tokens: 4096
    """
```

## 2. Synthesiser (`synthesiser.py`)

Takes all theme outputs + forward scan items and produces the cross-cutting sections.

```python
@track(name="synthesis")
def synthesise(
    theme_results: dict[str, dict],  # theme_id -> theme output
    forward_items: list[RawItem],
    config: dict,
    anthropic_client: anthropic.Anthropic,
) -> dict:
```

### Synthesis prompt

```python
SYNTHESIS_PROMPT = """You are a senior public affairs analyst at {consultancy_name}.

CLIENT: {client_name}
REPORTING PERIOD: {reporting_period}

THEME ANALYSIS RESULTS:
{theme_results_json}

FORWARD-LOOKING ITEMS:
{forward_items_text}

Produce:

1. EXECUTIVE SUMMARY
   - top_line: 3-5 sentences. The single most important development first. If you had 30 seconds in a lift with the client, what would you say?
   - key_developments: the 4-6 most significant items across ALL themes. Each needs: rag, development, relevance, recommended_action, section_ref (reference to the theme item), confidence.

2. FORWARD LOOK
   Array of upcoming events/milestones in the next 2-4 weeks. Each: date, event, relevance, preparation. Include consultation deadlines, committee sessions, planned announcements, competitor milestones, political calendar dates.

3. EMERGING THEMES
   2-4 paragraphs. Step back from individual items. Are there broader patterns? Is the political mood shifting? Is a previously quiet stakeholder becoming vocal? Is a policy window opening or closing? Is media framing changing?

4. ACTIONS TRACKER
   Derive actions from the analysis. Each: ref (001, 002...), action, owner ("[Name]"), deadline, origin ("Report {reporting_period}"), status ("Open").

5. COVERAGE SUMMARY
   Array of metrics: total media mentions (client), national media mentions, trade/specialist mentions, social media mentions (client), parliamentary mentions (client + key issues), competitor share of voice (top 3). Each: metric, this_week, previous_week ("[Baseline TBC]"), trend.

Return ONLY a JSON object with keys: executive_summary, forward_look, emerging_themes, actions_tracker, coverage_summary.
"""
```

## 3. Main function (`__init__.py`)

```python
@track(name="full_analysis")
async def analyse(
    items: list[RawItem],
    config: dict,
    anthropic_api_key: str,
    week_start: datetime,
) -> dict:
    """
    1. Build client context from config
    2. Route items to themes
    3. Run theme analyses (parallel or sequential)
    4. Separate forward scan items
    5. Run synthesis
    6. Merge all outputs into analysis.json schema
    7. Validate against schema
    8. Write to output/analysis_{date}.json
    9. Return the full analysis dict
    """
```

## Acceptance criteria

- Each theme analysis call returns valid JSON matching the theme's expected structure.
- Source provenance: every `AnalysedItem` has a non-empty `source_items` array linking to `RawItem` fingerprints.
- Confidence scores: no item has confidence of exactly 1.0 (that would suggest the model isn't calibrating). Most should be 0.6-0.9.
- Executive summary `key_developments` contains 4-6 items with valid `section_ref` values that match items in the theme results.
- Forward look contains at least 3 future-dated events.
- Emerging themes contains 2-4 non-trivial paragraphs (not generic filler).
- The merged output validates against `schemas/analysis.schema.json`.
- Every Claude call appears in the Opik trace with input/output, tokens, cost, and latency.
