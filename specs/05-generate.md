# Spec 05: DOCX Generator

## Purpose

Refactor the existing `generate-report.js` to read from `analysis.json` instead of hardcoded data. The generator is a pure template populator — no intelligence, no decisions. It takes structured data in, produces a formatted DOCX out.

## Source files

- `src/generate/generate-report.js`
- `src/generate/package.json`

## Input

Reads `output/analysis_{date}.json` — validated against `schemas/analysis.schema.json`.

Also reads the client config for branding (consultancy name, classification, etc).

## Invocation

```bash
node src/generate/generate-report.js \
  --analysis output/analysis_2026-03-24.json \
  --config src/config/rwe_client.json \
  --output output/RWE_Weekly_Monitoring_Report_wc_24_March_2026.docx
```

## Key changes from prototype

### 1. Read from JSON, not hardcoded

Replace all hardcoded strings, tables, and item cards with reads from the analysis JSON. The generator should work for ANY valid `analysis.json` — if you swapped in a different client's analysis, it should produce a correctly formatted report for that client.

### 2. Confidence flags

When rendering any text field that has an associated `confidence` score below 0.7, insert an inline marker:

```javascript
function renderText(text, confidence) {
  const runs = [new TextRun({ text, font: "Arial", size: 18 })];
  if (confidence !== undefined && confidence < 0.7) {
    runs.push(new TextRun({
      text: " [UNVERIFIED]",
      font: "Arial",
      size: 16,
      color: "CC7700",  // amber
      bold: true,
    }));
  }
  return runs;
}
```

Apply this to:
- Each `summary` field in `AnalysedItem`
- Each `client_relevance` field
- Each `development` field in `key_developments`
- Each `top_line` sentence (if the exec summary has a confidence score)

### 3. Section rendering

Map each section of the template to the analysis JSON:

| Report section | JSON path |
|---|---|
| Title page metadata | `metadata.*` + config `report.*` |
| 1.1 Top line | `executive_summary.top_line` |
| 1.2 Key developments table | `executive_summary.key_developments[]` |
| 2.1 Policy & Government | `sections.policy_government.items[]` |
| 2.2 Parliamentary | `sections.parliamentary.items[]` + `sections.parliamentary.routine_mentions[]` |
| 2.3 Regulatory & Legal | `sections.regulatory_legal.items[]` |
| 2.4 Media Coverage | `sections.media_coverage.coverage_table[]` + `sections.media_coverage.significant_items[]` |
| 2.5 Social Media | `sections.social_media.summary` + `.metrics` + `.notable_posts[]` |
| 2.6 Competitor & Industry | `sections.competitor_industry.table[]` |
| 2.7 Stakeholder & Third Party | `sections.stakeholder_third_party.items[]` or "No significant developments this week" if `no_developments: true` |
| 3. Forward Look | `forward_look[]` |
| 4. Emerging Themes | `emerging_themes[]` |
| 5. Actions Tracker | `actions_tracker[]` |
| 6. Coverage Summary | `coverage_summary[]` |

### 4. Empty section handling

For any theme where `items` is empty and `no_developments` is not explicitly true, render: "No significant developments this week."

This is a template requirement — every section must be present even if empty.

### 5. Sources unavailable

If `metadata.sources_unavailable` is non-empty, render a note at the bottom of the relevant section(s): "Note: [source name] was unavailable during collection for this reporting period."

### 6. Template structure preserved

Keep the existing formatting from the prototype:
- Cover page with WA branding, meta table
- Running header: WA COMMUNICATIONS | WEEKLY MONITORING REPORT | {client name}
- Running footer: CONFIDENTIAL | Prepared by WA Communications Research Team
- Navy headings, RAG-coloured dots, item card format, summary tables
- A4 page size, 1" margins, Arial font throughout

### 7. Validation before generation

Before building the DOCX, validate the analysis JSON against the schema. If validation fails, log the errors and exit — don't generate a partial report.

## package.json

```json
{
  "name": "wa-monitoring-report-generator",
  "version": "1.0.0",
  "dependencies": {
    "docx": "^9.0.0"
  }
}
```

## Acceptance criteria

- Given a valid `analysis.json`, produces a valid DOCX that passes `python scripts/office/validate.py`.
- All 6 report sections are present, including empty sections with "No significant developments" language.
- Confidence flags render as inline amber `[UNVERIFIED]` markers next to low-confidence text.
- RAG dots render in the correct colours (red/amber/green) with coloured cell backgrounds.
- Item cards render in the two-column label/value format.
- Summary tables (parliamentary, media, competitor) render with correct column counts.
- Forward look, actions tracker, and coverage summary tables match the template specification.
- Cross-references in Key Developments table (e.g. "see 2.1.1") appear and match actual item refs.
- The generator works with a different client config without code changes.
