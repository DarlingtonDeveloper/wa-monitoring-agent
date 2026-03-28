"""Per-theme analysis using Claude — two-pass approach.

Pass 1: Extract structured facts from source items (Haiku — fast, cheap).
Pass 2: Analyse relevance and produce item cards (Sonnet — balanced).

Separating extraction from interpretation improves both accuracy and traceability.
"""

import json
import logging

import anthropic
from opik import track

from score.keyword_scorer import flatten_keywords
from utils.retry import retry_api_call

log = logging.getLogger(__name__)

# ── Model assignments (tiered) ──
MODEL_EXTRACTION = "claude-haiku-4-5-20251001"
MODEL_ANALYSIS = "claude-sonnet-4-20250514"

# ── Theme routing ──
THEME_ROUTING = {
    "policy_government": {
        "source_types": ["govuk"],
        "keywords": ["desnz", "clean power", "cfd", "ar7", "ar8", "energy security",
                      "consultation", "policy", "minister", "announcement"],
    },
    "parliamentary": {
        "source_types": ["hansard"],
        "keywords": ["hansard", "debate", "committee", "question", "edm", "appg",
                      "parliament", "commons", "lords", "written question",
                      "early day motion"],
    },
    "regulatory_legal": {
        "keywords": ["ofgem", "neso", "crown estate", "planning", "dco", "nsip",
                      "riio", "tnuos", "grid connection", "seabed lease"],
    },
    "media_coverage": {
        "keywords": [],
    },
    "social_media": {
        "keywords": ["social media", "twitter", "linkedin", "viral", "trending",
                      "protest", "campaign"],
    },
    "competitor_industry": {
        "keywords": [],
    },
    "stakeholder_third_party": {
        "keywords": ["ngo", "campaign", "protest", "community", "union",
                      "academic", "petition", "foi", "activist"],
    },
}

# Priority order for cross-theme dedup (most specific first)
THEME_PRIORITY = [
    "parliamentary",
    "policy_government",
    "regulatory_legal",
    "stakeholder_third_party",
    "competitor_industry",
    "social_media",
    "media_coverage",
]

THEME_SPECIFIC_INSTRUCTIONS = {
    "parliamentary": (
        'Also produce a "routine_mentions" array for lower-significance parliamentary references. '
        "Each: {date, type, detail, members, significance} where significance is exactly one of: "
        '"Low", "Medium", "High".'
    ),
    "media_coverage": (
        'Produce a "coverage_table" array: {date, outlet, angle (own words — never the original headline), '
        'client_named (string like "Yes — positive" or "No — sector story"), action}. '
        'Elevate significant stories to full item cards in "significant_items".'
    ),
    "competitor_industry": (
        'Produce a "table" array: {organisation, development, relevance, action}. '
        "Do NOT include the client (RWE) as a competitor — only analyse other companies."
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

# ── Tool definitions for structured output ──
EXTRACT_FACTS_TOOL = {
    "name": "extract_facts",
    "description": "Submit extracted facts from source items as a structured array.",
    "input_schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fingerprint": {"type": "string"},
                        "who": {"type": "string"},
                        "what": {"type": "string"},
                        "when": {"type": "string"},
                        "numbers": {"type": "string"},
                        "type": {"type": "string"},
                    },
                },
            },
        },
        "required": ["facts"],
    },
}

SUBMIT_ANALYSIS_TOOL = {
    "name": "submit_analysis",
    "description": "Submit theme analysis results with item cards and theme-specific data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"type": "object"}},
            "no_developments": {"type": "boolean"},
            "routine_mentions": {"type": "array", "items": {"type": "object"}},
            "coverage_table": {"type": "array", "items": {"type": "object"}},
            "significant_items": {"type": "array", "items": {"type": "object"}},
            "table": {"type": "array", "items": {"type": "object"}},
            "summary": {"type": "string"},
            "metrics": {"type": "object"},
            "notable_posts": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["items", "no_developments"],
    },
}

# ── Prompts ──
EXTRACTION_PROMPT = """Extract structured facts from the following source items.

For each item, extract:
- fingerprint: the item's fingerprint (copy exactly)
- who: people, organisations, or bodies involved
- what: what happened or was announced (1-2 sentences, factual only)
- when: specific date or timeframe
- numbers: any specific figures (MW, £, percentages, dates)
- type: "announcement" | "debate" | "question" | "consultation" | "decision" | "report" | "comment"

Only extract facts that are directly stated in the source text. Do NOT infer or assume.
If a field cannot be determined from the text, use null.

ITEMS:
{items_text}

Use the extract_facts tool to submit your results."""

ANALYSIS_PROMPT = """You are a senior public affairs analyst at {consultancy_name}, a Westminster lobbying and public affairs firm.

CLIENT CONTEXT:
{client_context}

MONITORING THEME: {theme_label} (Section {section_number})

EXTRACTED FACTS:
{facts_json}

ORIGINAL SOURCE ITEMS (for reference):
{items_brief}

Using ONLY the extracted facts above, produce analysis items. Do not add information not present in the facts.

For each significant development, produce a JSON object with:
- ref: section reference (e.g. "{section_number}.1", "{section_number}.2")
- headline: concise title
- date: the date of the event/publication
- source: where this came from (e.g. "GOV.UK press release, DESNZ" or "Hansard, House of Lords")
- summary: 2-4 sentences. What happened. Plain English, precise about dates, names, amounts. ONLY state facts from the extracted facts.
- client_relevance: 2-3 sentences. Why this matters to {client_name} SPECIFICALLY — reference specific projects, commercial positions, or pipeline impacts.
- recommended_action: specific action (e.g. "Brief client", "Prepare consultation response", "Monitor")
- escalation: "IMMEDIATE" | "HIGH" | "STANDARD"
- rag: "RED" | "AMBER" | "GREEN"
- confidence: float 0-1. Base this on how well-supported the facts are. If facts are clear and specific, use 0.8+. If ambiguous or thin, use 0.5-0.7.
- source_items: array of fingerprint strings from the facts that support this analysis

{theme_specific_instructions}

RULES:
- ONLY use information from the extracted facts. Do not add external knowledge.
- Summarise in own words with attribution. Never reproduce source text.
- Do not editorialise or offer political opinion. Facts and analysis only.
- Every item must answer: What happened? Why does it matter to THIS client? What should we do?
- If nothing significant occurred in this theme, return an empty items array with no_developments: true.
- Use arrow characters (\\u2191 \\u2193 \\u2194) in any trend descriptions.

Use the submit_analysis tool to submit your results."""


def _get_tool_input(response, tool_name: str) -> dict:
    """Extract tool input from a forced tool_use response."""
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input
    raise ValueError(f"No '{tool_name}' tool_use block in response")


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
    """Route items to monitoring themes. Each item goes to exactly one theme."""
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
        assigned = False

        # Priority 1: source type match (definitive routing)
        for theme_id in THEME_PRIORITY:
            rules = routing[theme_id]
            if source_type in rules.get("source_types", []):
                theme_items[theme_id].append(item)
                assigned = True
                break

        if assigned:
            continue

        # Priority 2: best keyword match count, tie-broken by theme priority
        best_theme = None
        best_count = 0
        for theme_id in THEME_PRIORITY:
            rules = routing[theme_id]
            count = sum(1 for kw in rules.get("keywords", []) if kw in text)
            if count > best_count:
                best_count = count
                best_theme = theme_id

        if best_theme:
            theme_items[best_theme].append(item)
        elif item.get("relevance_score", 0) >= 0.15:
            theme_items["policy_government"].append(item)

    return theme_items


@track(name="fact_extraction")
def _extract_facts(
    items: list[dict],
    anthropic_client: anthropic.Anthropic,
) -> list[dict]:
    """Pass 1: Extract structured facts from source items (Haiku — fast, cheap)."""
    items_text = ""
    for i, item in enumerate(items[:30], 1):
        items_text += (
            f"\n[{i}] Fingerprint: {item.get('fingerprint', 'N/A')}\n"
            f"    Title: {item.get('title', '')}\n"
            f"    Date: {item.get('date', '')}\n"
            f"    Source: {item.get('source_name', '')} ({item.get('source_type', '')})\n"
            f"    Content: {item.get('content', '')}\n"
        )

    prompt = EXTRACTION_PROMPT.format(items_text=items_text)

    try:
        response = retry_api_call(
            anthropic_client.messages.create,
            model=MODEL_EXTRACTION,
            max_tokens=4096,
            tools=[EXTRACT_FACTS_TOOL],
            tool_choice={"type": "tool", "name": "extract_facts"},
            messages=[{"role": "user", "content": prompt}],
        )
        result = _get_tool_input(response, "extract_facts")
        facts = result.get("facts", [])
        log.info(f"Extracted {len(facts)} facts from {len(items)} items")
        return facts
    except Exception as e:
        log.warning(f"Fact extraction failed: {e}")
        return []


@track(name="theme_analysis")
def analyse_theme(
    theme_id: str,
    theme_config: dict,
    items: list[dict],
    client_context: str,
    config: dict,
    anthropic_client: anthropic.Anthropic,
) -> dict:
    """Analyse a single monitoring theme using two-pass approach."""
    if not items:
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

    # ── Pass 1: Extract facts (Haiku) ──
    facts = _extract_facts(items, anthropic_client)
    if not facts:
        log.warning(f"No facts extracted for theme '{theme_id}', falling back to single-pass")
        facts = []

    # ── Pass 2: Analyse from facts (Sonnet) ──
    items_brief = ""
    for i, item in enumerate(items[:30], 1):
        items_brief += (
            f"[{i}] {item.get('fingerprint', '')} | {item.get('title', '')[:60]} | "
            f"{item.get('source_name', '')} | Verified: {item.get('verified', False)} | "
            f"Score: {item.get('relevance_score', 0):.2f}\n"
        )

    prompt = ANALYSIS_PROMPT.format(
        consultancy_name=config.get("report", {}).get("consultancy_name", "WA Communications"),
        client_context=client_context,
        theme_label=theme_config["label"],
        section_number=theme_config["section"],
        facts_json=json.dumps(facts, indent=2, default=str),
        items_brief=items_brief,
        client_name=config["client"]["name"],
        theme_specific_instructions=THEME_SPECIFIC_INSTRUCTIONS.get(theme_id, ""),
    )

    try:
        response = retry_api_call(
            anthropic_client.messages.create,
            model=MODEL_ANALYSIS,
            max_tokens=4096,
            tools=[SUBMIT_ANALYSIS_TOOL],
            tool_choice={"type": "tool", "name": "submit_analysis"},
            messages=[{"role": "user", "content": prompt}],
        )

        result = _get_tool_input(response, "submit_analysis")

        if "items" not in result:
            result["items"] = result.get("significant_items", [])

        return result

    except json.JSONDecodeError as e:
        log.error(f"Failed to parse theme '{theme_id}' response: {e}")
        return {"items": [], "no_developments": True}
    except Exception as e:
        log.error(f"Theme analysis '{theme_id}' failed: {e}")
        return {"items": [], "no_developments": True}
