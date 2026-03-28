"""LLM-as-judge evaluation using Opik."""

import json
import logging
import os
from datetime import datetime

import anthropic
from opik import track

log = logging.getLogger(__name__)


def _build_client_context(config: dict) -> str:
    """Build client context for specificity prompts."""
    client = config["client"]
    lines = [f"Client: {client['name']} ({client['full_name']})", f"Sector: {client['sector']}"]
    for project in config.get("projects", []):
        cap = f" ({project['capacity_mw']}MW)" if project.get("capacity_mw") else ""
        lines.append(f"  - {project['name']}{cap}: {project['status']} [{project['priority']}]")
    return "\n".join(lines)


def build_factuality_cases(analysis: dict, items_cache: list[dict]) -> list[dict]:
    """
    For each AnalysedItem, build a factuality evaluation case.
    """
    cases = []
    items_by_fp = {item["fingerprint"]: item for item in items_cache}

    for theme_id, theme_data in analysis.get("sections", {}).items():
        all_items = theme_data.get("items", []) + theme_data.get("significant_items", [])
        for item in all_items:
            source_texts = []
            for fp in item.get("source_items", []):
                if fp in items_by_fp:
                    source_texts.append(items_by_fp[fp].get("content", ""))

            if not source_texts:
                continue

            cases.append({
                "input": "\n".join(source_texts),
                "output": f"{item.get('summary', '')} {item.get('client_relevance', '')}",
                "context": source_texts,
                "reference": item.get("ref", ""),
            })

    return cases


@track(name="factuality_evaluation")
def run_factuality_check(analysis: dict, items_cache: list[dict]) -> dict:
    """
    Check factuality of analysed items against source material.
    Uses Claude as judge since Opik's built-in metrics may not be available.
    """
    cases = build_factuality_cases(analysis, items_cache)

    if not cases:
        return {"mean_score": 1.0, "flagged_items": [], "total_checked": 0}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key)

    scores = []
    flagged = []

    for case in cases:
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": (
                        "You are evaluating whether an analysis summary is factually grounded "
                        "in the source material.\n\n"
                        f"SOURCE MATERIAL:\n{case['input']}\n\n"
                        f"ANALYSIS OUTPUT:\n{case['output']}\n\n"
                        "Score 0-1 how well the analysis is supported by the source material. "
                        "1.0 = fully supported, 0.0 = completely fabricated.\n"
                        "Return ONLY a JSON object: {\"score\": float, \"reason\": \"brief\"}"
                    ),
                }],
            )

            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text

            result = json.loads(text.strip().strip("`").replace("```json", "").replace("```", ""))
            score = float(result.get("score", 0))
            scores.append(score)

            if score < 0.7:
                flagged.append(case["reference"])

        except Exception as e:
            log.warning(f"Factuality check failed for {case['reference']}: {e}")
            scores.append(0.5)  # Uncertain = middle score

    mean_score = sum(scores) / len(scores) if scores else 0.0

    return {
        "mean_score": round(mean_score, 3),
        "flagged_items": flagged,
        "total_checked": len(cases),
    }


@track(name="specificity_evaluation")
def run_specificity_check(analysis: dict, config: dict) -> dict:
    """
    Check whether client_relevance text is specific to the client
    or generic analysis that could apply to any energy company.
    """
    client_name = config["client"]["name"]
    client_context = _build_client_context(config)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key)

    cases = []
    for theme_id, theme_data in analysis.get("sections", {}).items():
        all_items = theme_data.get("items", []) + theme_data.get("significant_items", [])
        for item in all_items:
            if item.get("client_relevance"):
                cases.append({
                    "output": item["client_relevance"],
                    "reference": item.get("ref", ""),
                })

    if not cases:
        return {"mean_score": 1.0, "flagged_items": [], "total_checked": 0}

    scores = []
    flagged = []

    for case in cases:
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": (
                        f"You are evaluating a public affairs monitoring report for {client_name}.\n\n"
                        "The following 'client relevance' text should explain why a development matters "
                        f"specifically to {client_name} — referencing their specific projects, commercial "
                        "position, pipeline, or strategic priorities.\n\n"
                        f"CLIENT CONTEXT:\n{client_context}\n\n"
                        f"CLIENT RELEVANCE TEXT TO EVALUATE:\n{case['output']}\n\n"
                        "SCORING:\n"
                        "- 1.0: Highly specific. References specific projects (e.g. Norfolk Vanguard, Sofia), "
                        "specific commercial positions, or specific pipeline impacts.\n"
                        "- 0.7: Moderately specific. References the client's sector position but not projects.\n"
                        "- 0.4: Generic. Could apply to any offshore wind developer.\n"
                        "- 0.1: Completely generic. Could apply to any energy company.\n\n"
                        'Return ONLY a JSON object: {"score": float, "reason": "brief explanation"}'
                    ),
                }],
            )

            text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    text += block.text

            result = json.loads(text.strip().strip("`").replace("```json", "").replace("```", ""))
            score = float(result.get("score", 0))
            scores.append(score)

            if score < 0.5:
                flagged.append(case["reference"])

        except Exception as e:
            log.warning(f"Specificity check failed for {case['reference']}: {e}")
            scores.append(0.5)

    mean_score = sum(scores) / len(scores) if scores else 0.0

    return {
        "mean_score": round(mean_score, 3),
        "flagged_items": flagged,
        "total_checked": len(cases),
    }
