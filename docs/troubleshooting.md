# Troubleshooting

## Common issues

### Rate limiting (429 errors)

**Symptom**: `RateLimitError: 429 - rate limit of 50,000 input tokens per minute`

The Haiku web search stage hits API rate limits when processing 14 queries in batches. The pipeline has built-in mitigation:

- 4 queries per batch with 45s cooldowns between batches
- Exponential backoff retry (15s, 30s, 45s) via `src/utils/retry.py`
- Anthropic SDK's own retry with jitter

**If it persists**: Increase `BATCH_DELAY` in `src/collect/web_search.py` (default: 45s) or reduce `BATCH_SIZE` (default: 4).

### GOV.UK feeds returning 0 entries

**Symptom**: `NO ENTRIES - feed may be empty or URL may be wrong`

GOV.UK Atom feeds occasionally change URLs or return empty for date ranges with no publications. Run the diagnostic:

```bash
python3 scripts/test_feeds.py
```

This tests all 10 feeds and shows which ones have entries for the target week.

### Items missing from final report

Use the trace script to find where an item was lost:

```bash
python3 scripts/trace_missing.py
```

Common causes:
- **Never collected**: Source doesn't have the item in its feed/API for that date range
- **Filtered by date**: Item date outside reporting week +/- 1 day
- **Filtered by geography**: Item mentions non-UK country without UK markers
- **Scored below 0.08**: Thin content or no keyword matches
- **Deduped**: Another copy of the same item scored higher
- **Capped at 150**: Item scored in the tail end

### Enrichment not working

**Symptom**: GOV.UK items still have 200-300 char content

Check that enrichment runs **before** scoring in the pipeline log:

```
STAGE 1: COLLECT
...
STAGE 1b: ENRICH THIN ITEMS
Enriched 40/40 items with full content
STAGE 2: SCORE & FILTER
```

If enrichment shows 0 enriched, check:
- Network connectivity to target URLs
- Content-type filtering (only HTML pages are enriched)
- PDF URLs are skipped

### DOCX generation fails

**Symptom**: `DOCX generation failed: ...`

```bash
# Test the generator directly
node src/generate/generate-report.js \
  --analysis output/analysis_2026-03-23.json \
  --config src/config/rwe_client.json \
  --output test.docx
```

Common causes:
- Missing `node_modules` in `src/generate/` — run `cd src/generate && npm install`
- analysis.json schema validation errors — check `output/eval_*.json` for template_validation.errors
- Node.js version < 18

### Opik dashboard empty

**Symptom**: http://localhost:5173 shows no traces

1. Check containers are running: `docker ps | grep opik`
2. Check the Python SDK can connect: `python3 -c "import opik; opik.configure(use_local=True)"`
3. Check the project name matches: traces go to the `wa-monitoring-agent` project

If Opik was reinstalled with fresh volumes, previous trace data lives in the old Docker volumes (prefixed `opik-opik_*`). See the main README for volume mapping.

### Template validation errors

**Symptom**: `Template: FAIL (N errors, M warnings)`

Check `output/eval_*.json` → `template_validation.errors` for specifics. Common issues:
- Missing `source_items` on analysis items (synthesis didn't link back to sources)
- `significant_items` count below minimum
- Missing required fields in `executive_summary`

These are usually synthesis prompt issues, not data problems. The pipeline continues despite template errors.

### Low specificity scores

**Symptom**: `Specificity: 0.5-0.6 (many flagged)`

The specificity judge checks whether items are relevant to the **specific client** vs generic sector news. Low scores mean:
- Too many generic items surviving scoring (tighten keywords)
- Client context in config is too broad
- Items about the sector but not about the client's interests

### python vs python3

On macOS, use `python3` — the `python` command may not exist or may point to Python 2.

## Diagnostic scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `scripts/test_feeds.py` | Verify GOV.UK Atom feeds work | `python3 scripts/test_feeds.py` |
| `scripts/trace_missing.py` | Trace items through pipeline stages | `python3 scripts/trace_missing.py` |
| `scripts/score_urls.py` | Score specific URLs with full content | `python3 scripts/score_urls.py` |

## Log levels

The pipeline logs to stdout at INFO level. For more detail:

```python
# In src/orchestrator.py, change:
logging.basicConfig(level=logging.DEBUG, ...)
```

Content enricher and web search have DEBUG-level logs for individual URL fetches.
