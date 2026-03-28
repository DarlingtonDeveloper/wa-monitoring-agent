# Spec 06: Evaluation Layer

## Purpose

Two evaluation systems that run after report generation:

1. **Template validator** — deterministic checks on the DOCX structure. Catches the class of errors found in the prototype review (missing columns, missing sections, missing cross-references).

2. **LLM-as-judge** — uses Opik's built-in hallucination metric plus a custom specificity metric. Checks factual accuracy and analytical quality.

Both produce scores that are logged to Opik and can be viewed on the dashboard.

## Source files

- `src/evaluate/template_validator.py`
- `src/evaluate/judge.py`
- `src/evaluate/__init__.py` (exports `evaluate_report` function)

## 1. Template validator (`template_validator.py`)

Operates on the `analysis.json` (not the DOCX — checking the data before/after generation is equivalent and much easier than parsing XML).

```python
def validate_template_compliance(analysis: dict) -> list[dict]:
    """
    Returns a list of validation failures.
    Each failure: {"check": str, "severity": "error"|"warning", "detail": str}
    Empty list = all checks passed.
    """
```

### Checks to implement

**Section presence** (severity: error):
- `executive_summary` exists and has `top_line` (non-empty string)
- `executive_summary.key_developments` has 4-6 items
- All 7 theme sections exist under `sections`
- `forward_look` exists and has at least 1 item
- `emerging_themes` exists and has 2-4 items
- `actions_tracker` exists
- `coverage_summary` exists

**Key developments table** (severity: error):
- Each item has all required fields: `rag`, `development`, `relevance`, `recommended_action`, `section_ref`
- `rag` is one of `RED`, `AMBER`, `GREEN`
- `section_ref` values actually exist in the theme results (cross-reference check)

**Item cards** (severity: error):
- Every `AnalysedItem` has all required fields: `ref`, `headline`, `date`, `source`, `summary`, `client_relevance`, `recommended_action`
- `summary` is 2-4 sentences (count periods/question marks — at least 2, no more than 6)
- `client_relevance` is 2-3 sentences
- `escalation` is one of `IMMEDIATE`, `HIGH`, `STANDARD`

**Parliamentary section** (severity: warning):
- If `routine_mentions` is present, each has: `date`, `type`, `detail`, `members`, `significance`

**Media section** (severity: warning):
- If `coverage_table` is present, each row has: `date`, `outlet`, `angle`, `client_named`, `action`

**Coverage summary** (severity: warning):
- Each row has 4 fields: `metric`, `this_week`, `previous_week`, `trend`
- Required metrics present: "Total media mentions (client)", "Parliamentary mentions", "Competitor share of voice"

**Empty section handling** (severity: warning):
- Any theme with empty `items` should have `no_developments: true`

**Source provenance** (severity: error):
- Every `AnalysedItem` has a non-empty `source_items` array
- Each fingerprint in `source_items` exists in the cached `items.json`

**Confidence scores** (severity: warning):
- All `AnalysedItem` objects have a `confidence` field
- No confidence score is exactly 1.0 or exactly 0.0

## 2. LLM-as-judge (`judge.py`)

Uses Opik's evaluation framework with built-in and custom metrics.

### Setup

```python
import opik
from opik.evaluation.metrics import Hallucination, AnswerRelevance
from opik.evaluation import evaluate
from opik import track

opik.configure()  # reads OPIK_API_KEY, OPIK_WORKSPACE from env
```

### Factuality metric (Opik built-in)

For each `AnalysedItem` in the analysis, build an evaluation case:

```python
def build_factuality_cases(analysis: dict, items_cache: list[dict]) -> list[dict]:
    """
    For each AnalysedItem:
    - input: the source content (looked up via source_items fingerprints from items_cache)
    - output: the item's summary + client_relevance
    - context: the source content (same as input for hallucination check)

    Returns list of dicts ready for Opik evaluate().
    """
    cases = []
    items_by_fp = {item["fingerprint"]: item for item in items_cache}

    for theme_id, theme_data in analysis["sections"].items():
        for item in theme_data.get("items", []):
            source_texts = []
            for fp in item.get("source_items", []):
                if fp in items_by_fp:
                    source_texts.append(items_by_fp[fp]["content"])
            if not source_texts:
                continue

            cases.append({
                "input": "\n".join(source_texts),
                "output": f"{item['summary']} {item['client_relevance']}",
                "context": source_texts,
                "reference": item["ref"],
            })
    return cases
```

Run Opik evaluation:

```python
@track(name="factuality_evaluation")
def run_factuality_check(analysis: dict, items_cache: list[dict]) -> dict:
    cases = build_factuality_cases(analysis, items_cache)
    results = evaluate(
        experiment_name=f"factuality_{datetime.now().strftime('%Y%m%d')}",
        dataset=cases,
        metrics=[Hallucination()],
    )
    return {
        "mean_score": results.mean_score,
        "flagged_items": [
            r["reference"] for r in results.results
            if r["score"] < 0.7
        ],
        "total_checked": len(cases),
    }
```

### Specificity metric (custom)

This checks whether the `client_relevance` text is actually specific to the client or could apply to any energy company.

```python
from opik.evaluation.metrics import LLMJudge

specificity_metric = LLMJudge(
    name="client_specificity",
    model="claude-sonnet-4-20250514",
    prompt_template="""You are evaluating a public affairs monitoring report for {client_name}.

The following "client relevance" text should explain why a development matters specifically to {client_name} — referencing their specific projects, commercial position, pipeline, or strategic priorities.

CLIENT CONTEXT:
{client_context}

CLIENT RELEVANCE TEXT TO EVALUATE:
{output}

SCORING:
- 1.0: Highly specific. References specific projects (e.g. Norfolk Vanguard, Sofia), specific commercial positions (e.g. AR7 CfD strike prices), or specific pipeline impacts.
- 0.7: Moderately specific. References the client's sector position but not individual projects.
- 0.4: Generic. Could apply to any offshore wind developer.
- 0.1: Completely generic. Could apply to any energy company.

Return ONLY a JSON object: {{"score": float, "reason": "brief explanation"}}
""",
)
```

Run specificity check on all `client_relevance` fields:

```python
@track(name="specificity_evaluation")
def run_specificity_check(analysis: dict, config: dict) -> dict:
    cases = []
    for theme_id, theme_data in analysis["sections"].items():
        for item in theme_data.get("items", []):
            cases.append({
                "output": item["client_relevance"],
                "client_name": config["client"]["name"],
                "client_context": build_client_context(config),
                "reference": item["ref"],
            })

    results = evaluate(
        experiment_name=f"specificity_{datetime.now().strftime('%Y%m%d')}",
        dataset=cases,
        metrics=[specificity_metric],
    )
    return {
        "mean_score": results.mean_score,
        "flagged_items": [
            r["reference"] for r in results.results
            if r["score"] < 0.5
        ],
        "total_checked": len(cases),
    }
```

## 3. Main function (`__init__.py`)

```python
@track(name="full_evaluation")
def evaluate_report(
    analysis: dict,
    items_cache: list[dict],
    config: dict,
) -> dict:
    """
    1. Run template validator
    2. Run factuality check
    3. Run specificity check
    4. Merge results into evaluation report
    5. Log summary to Opik
    6. Return evaluation dict

    Returns:
    {
        "template_validation": {
            "passed": bool,
            "errors": [...],
            "warnings": [...]
        },
        "factuality": {
            "mean_score": float,
            "flagged_items": [refs],
            "total_checked": int
        },
        "specificity": {
            "mean_score": float,
            "flagged_items": [refs],
            "total_checked": int
        },
        "overall_pass": bool,
        "flagged_refs": [all refs that need human review]
    }
    """
```

`overall_pass` is `True` if:
- Template validation has zero errors (warnings OK)
- Factuality mean_score > 0.7
- Specificity mean_score > 0.5

Even if `overall_pass` is `False`, the report is still generated — just with flags. The system never silently drops content.

## Acceptance criteria

- Template validator catches all 6 structural errors found in the prototype review (missing cross-refs, wrong column count, missing required language, etc).
- Factuality check runs against actual source material and produces scores in the 0-1 range.
- Specificity check distinguishes between RWE-specific analysis and generic energy sector commentary.
- All evaluation results are logged to Opik and visible in the dashboard.
- Flagged items from the evaluation are passed back to the DOCX generator to insert `[UNVERIFIED]` markers.
- The evaluation runs in under 60 seconds for a typical report (~20 analysed items).
