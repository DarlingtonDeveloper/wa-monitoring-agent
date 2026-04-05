# Schema Reference

Two JSON schemas define the contracts between pipeline stages.

## analysis.schema.json

The critical contract between the Python analysis layer and the Node.js DOCX generator. Both sides validate against this schema.

**Location**: `schemas/analysis.schema.json`

### Top-level structure

```json
{
  "metadata": { ... },
  "executive_summary": { ... },
  "sections": {
    "policy_government": { ... },
    "parliamentary": { ... },
    "regulatory_legal": { ... },
    "media_coverage": { ... },
    "social_media": { ... },
    "competitor_industry": { ... },
    "stakeholder_third_party": { ... }
  },
  "forward_look": [ ... ],
  "emerging_themes": [ ... ],
  "actions_tracker": [ ... ],
  "coverage_summary": [ ... ]
}
```

### metadata

| Field | Type | Description |
|-------|------|-------------|
| `client_name` | string | Display name for the report |
| `reporting_period` | string | e.g. "24-28 March 2026" |
| `report_date` | string | e.g. "31 March 2026" |
| `generated_at` | string | ISO 8601 timestamp |
| `items_collected` | integer | Raw items before filtering |
| `items_scored` | integer | Items after scoring |
| `items_analysed` | integer | Items sent to Claude |
| `sources_unavailable` | array | Sources that failed during collection |

### executive_summary

| Field | Type | Description |
|-------|------|-------------|
| `top_line` | string | 3-5 sentence overview of the week |
| `key_developments` | array | Top items with RAG status |

Each key_development:

| Field | Type | Description |
|-------|------|-------------|
| `rag` | string | "red", "amber", or "green" |
| `development` | string | What happened |
| `relevance` | string | Why it matters to the client |
| `recommended_action` | string | What the consultant should do |
| `section_ref` | string | e.g. "2.1" — links to the theme section |

### sections (per theme)

| Field | Type | Description |
|-------|------|-------------|
| `overview` | string | 2-3 paragraph theme summary |
| `significant_items` | array | Top items for this theme |
| `items` | array | All analysed items |

Each item:

| Field | Type | Description |
|-------|------|-------------|
| `ref` | string | e.g. "2.1.1" — unique reference |
| `headline` | string | Short title |
| `summary` | string | 100-300 word analysis |
| `relevance` | string | Why it matters to the client |
| `recommended_action` | string | Suggested next step |
| `confidence` | float | 0-1, below 0.7 gets flagged |
| `source_items` | array | Fingerprints of source items |
| `rag` | string | "red", "amber", or "green" |
| `date` | string | When this happened |

### forward_look

Array of upcoming events:

| Field | Type | Description |
|-------|------|-------------|
| `date` | string | When |
| `event` | string | What |
| `relevance` | string | Why it matters |
| `action` | string | Suggested preparation |

### emerging_themes

Array of 2-4 strings, each a paragraph describing a cross-cutting pattern.

### actions_tracker

| Field | Type | Description |
|-------|------|-------------|
| `action` | string | What needs to happen |
| `theme` | string | Which monitoring theme |
| `priority` | string | "high", "medium", "low" |
| `owner` | string | Suggested owner (usually "WA team") |
| `due_date` | string | Suggested deadline |
| `status` | string | "new", "in_progress", "complete" |

### coverage_summary

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | Source name |
| `this_week` | integer | Items from this source this week |
| `previous_week` | integer | Items from this source last week |
| `trend` | string | "up", "down", "stable" |

---

## items.schema.json

Schema for scored items (the cached `items_YYYY-MM-DD.json`).

**Location**: `schemas/items.schema.json`

### Item fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_type` | string | Yes | One of: hansard, govuk, web, parliament, rss, committees, forward_scan |
| `title` | string | Yes | Item title |
| `date` | string | No | ISO 8601 date |
| `url` | string | No | Source URL |
| `content` | string | Yes | Full text or summary (max 8000 chars) |
| `source_name` | string | Yes | Human-readable source |
| `keywords_matched` | array | No | Which keyword groups matched |
| `relevance_score` | float | Yes | 0-1 score from keyword_scorer |
| `verified` | boolean | No | URL HEAD check passed |
| `fingerprint` | string | Yes | SHA256(url:title)[:12] for dedup |
| `content_enriched` | boolean | No | Full page content was fetched |
