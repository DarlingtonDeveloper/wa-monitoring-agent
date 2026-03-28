"""Per-theme analysis using Claude."""

import json
import logging
import re

import anthropic
from opik import track

from score.keyword_scorer import flatten_keywords

log = logging.getLogger(__name__)

THEME_ROUTING = {
    "policy_government": {
        "source_types": ["govuk"],
        "keywords": ["desnz", "clean power", "cfd", "ar7", "ar8", "energy security",
                      "consultation", "policy", "minister", "announcement"],
    },
    "parliamentary": {
        "source_types": ["hansard"],
        "keywords": ["hansard", "debate", "committee", "question", "edm", "appg",
                      "parliament", "commons", "lords"],
    },
    "regulatory_legal": {
        "keywords": ["ofgem", "neso", "crown estate", "planning", "dco", "nsip",
                      "riio", "tnuos", "grid connection", "seabed lease"],
    },
    "media_coverage": {
        "keywords": [],  # Populated from config at runtime
    },
    "social_media": {
        "keywords": ["social media", "twitter", "linkedin", "viral", "trending",
                      "protest", "campaign"],
    },
    "competitor_industry": {
        "keywords": [],  # Populated from config at runtime
    },
    "stakeholder_third_party": {
        "keywords": ["ngo", "campaign", "protest", "community", "union",
                      "academic", "petition", "foi", "activist"],
    },
}

THEME_SPECIFIC_INSTRUCTIONS = {
    "parliamentary": (
        'Also produce a "routine_mentions" array for lower-significance parliamentary references. '
        "Each: {date, type, detail, members, significance}."
    ),
    "media_coverage": (
        'Produce a "coverage_table" array: {date, outlet, angle (own words — never the original headline), '
        'client_named, action}. Elevate significant stories to full item cards in "significant_items".'
    ),
    "competitor_industry": (
        'Produce a "table" array: {organisation, development, relevance, action}.'
    ),
    "social_media": (
        'Produce "summary" (paragraph), "metrics" object {total_mentions, sentiment_breakdown, '
        "top_engagement_post, trend_vs_previous}, and \"notable_posts\" array. "
        "Note: quantitative metrics are approximate without platform API access — flag this."
    ),
    "stakeholder_third_party": (
        'If nothing notable, set "no_developments": true.'
    ),
}

THEME_PROMPT = """You are a senior public affairs analyst at {consultancy_name}, a Westminster lobbying and public affairs firm.

CLIENT CONTEXT:
{client_context}

MONITORING THEME: {theme_label} (Section {section_number})

ITEMS TO ANALYSE:
{items_text}

For each significant item, produce a JSON object with:
- ref: section reference (e.g. "{section_number}.1", "{section_number}.2")
- headline: concise title
- date: the date of the event/publication
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

Return ONLY a JSON object: {{"items": [...], "no_developments": true/false}}"""


def build_client_context(config: dict) -> str:
    """Render client config into a concise text block for prompts."""
    client = config["client"]
    lines = [
        f"Client: {client['name']} ({client['full_name']})",
        f"Sector: {client['sector']}",
        f"Country: {client['country']}",
        "",
        "Key Projects:",
    ]
    for project in config.get("projects", []):
        cap = f" ({project['capacity_mw']}MW)" if project.get("capacity_mw") else ""
        lines.append(
            f"  - {project['name']}{cap}: {project['status']} [{project['priority']}]"
        )

    lines.extend(["", "Escalation Triggers (IMMEDIATE):"])
    for trigger in config.get("escalation", {}).get("IMMEDIATE", []):
        lines.append(f"  - {trigger}")

    return "\n".join(lines)


def route_items_to_themes(items: list[dict], config: dict) -> dict[str, list[dict]]:
    """Route items to monitoring themes based on source type and keyword matches."""
    # Build dynamic keyword lists from config
    routing = {k: dict(v) for k, v in THEME_ROUTING.items()}

    media_names = (
        config.get("sources", {}).get("media_specialist", []) +
        config.get("sources", {}).get("media_national", []) +
        config.get("sources", {}).get("media_regional", [])
    )
    routing["media_coverage"]["keywords"] = [n.lower() for n in media_names]

    competitor_kws = flatten_keywords(config.get("keywords", {}).get("competitors", []))
    industry_names = config.get("sources", {}).get("industry", [])
    if isinstance(industry_names, list) and industry_names and isinstance(industry_names[0], dict):
        industry_names = [s["name"] for s in industry_names]
    routing["competitor_industry"]["keywords"] = competitor_kws + [n.lower() for n in industry_names]

    theme_items: dict[str, list[dict]] = {tid: [] for tid in routing}

    for item in items:
        text = f"{item.get('title', '')} {item.get('content', '')} {item.get('source_name', '')}".lower()
        source_type = item.get("source_type", "")
        matched = False

        for theme_id, rules in routing.items():
            # Check source type match
            if source_type in rules.get("source_types", []):
                theme_items[theme_id].append(item)
                matched = True
                continue

            # Check keyword match
            if any(kw in text for kw in rules.get("keywords", [])):
                theme_items[theme_id].append(item)
                matched = True

        # Unmatched items with decent score go to policy_government as default
        if not matched and item.get("relevance_score", 0) >= 0.15:
            theme_items["policy_government"].append(item)

    return theme_items


@track(name="theme_analysis")
def analyse_theme(
    theme_id: str,
    theme_config: dict,
    items: list[dict],
    client_context: str,
    config: dict,
    anthropic_client: anthropic.Anthropic,
) -> dict:
    """Analyse a single monitoring theme using Claude."""
    if not items:
        # Return empty structure for this theme
        base = {"items": [], "no_developments": True}
        if theme_id == "parliamentary":
            base["routine_mentions"] = []
        elif theme_id == "media_coverage":
            base = {"coverage_table": [], "significant_items": [], "items": []}
        elif theme_id == "social_media":
            base = {
                "summary": "No significant social media activity identified this week.",
                "metrics": {
                    "total_mentions": "N/A",
                    "sentiment_breakdown": "N/A",
                    "top_engagement_post": "N/A",
                    "trend_vs_previous": "N/A",
                },
                "notable_posts": [],
            }
        elif theme_id == "competitor_industry":
            base = {"table": []}
        return base

    # Build items text
    items_text = ""
    for i, item in enumerate(items[:30], 1):  # Cap at 30 items per theme
        items_text += (
            f"\n[{i}] Fingerprint: {item.get('fingerprint', 'N/A')}\n"
            f"    Title: {item.get('title', '')}\n"
            f"    Date: {item.get('date', '')}\n"
            f"    Source: {item.get('source_name', '')} ({item.get('source_type', '')})\n"
            f"    URL: {item.get('url', '')}\n"
            f"    Content: {item.get('content', '')}\n"
            f"    Verified: {item.get('verified', False)}\n"
            f"    Score: {item.get('relevance_score', 0):.2f}\n"
        )

    prompt = THEME_PROMPT.format(
        consultancy_name=config.get("report", {}).get("consultancy_name", "WA Communications"),
        client_context=client_context,
        theme_label=theme_config["label"],
        section_number=theme_config["section"],
        items_text=items_text,
        client_name=config["client"]["name"],
        theme_specific_instructions=THEME_SPECIFIC_INSTRUCTIONS.get(theme_id, ""),
    )

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        # Parse JSON from response
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        result = json.loads(text.strip())

        # Ensure required keys
        if "items" not in result:
            result["items"] = result.get("significant_items", [])

        return result

    except json.JSONDecodeError as e:
        log.error(f"Failed to parse theme '{theme_id}' response: {e}")
        return {"items": [], "no_developments": True}
    except Exception as e:
        log.error(f"Theme analysis '{theme_id}' failed: {e}")
        return {"items": [], "no_developments": True}
