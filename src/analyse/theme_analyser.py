"""Per-theme analysis using Claude — two-pass approach.

Pass 1: Extract structured facts from source items (Haiku — fast, cheap).
Pass 2: Analyse relevance and produce item cards (Sonnet — balanced).

Separating extraction from interpretation improves both accuracy and traceability.
"""

import json
import logging
from datetime import datetime, timedelta

import anthropic
from opik import track

from utils.retry import retry_api_call

log = logging.getLogger(__name__)

# ── Model assignments (tiered) ──
MODEL_EXTRACTION = "claude-haiku-4-5-20251001"
MODEL_ANALYSIS = "claude-sonnet-4-20250514"

# ── Single-theme routing by source type (Fix 3: source type first, content override) ──

# Known media outlets — items from these route to media
MEDIA_OUTLETS = {
    "recharge", "recharge news", "windpower monthly", "new power",
    "utility week", "current±", "the energyst", "energy voice",
    "financial times", "the times", "bloomberg", "reuters",
    "the guardian", "the telegraph", "bbc", "sky news",
    "politico", "politicshome",
    "eastern daily press", "grimsby telegraph", "northern echo",
    "daily post", "press and journal",
}

# Known industry bodies — items from these route to competitor
INDUSTRY_BODIES = {
    "renewableuk", "energy uk", "oeuk", "ore catapult",
    "rea", "windeurope", "climate change committee",
    "carbon tracker", "ember", "aurora energy research",
    "cornwall insight", "national infrastructure commission",
}

# Known competitors — items mentioning these route to competitor
COMPETITOR_NAMES = {
    "ørsted", "orsted", "sse renewables", "equinor", "vattenfall",
    "iberdrola", "scottishpower renewables", "ocean winds",
    "blue gem wind", "corio generation",
}

# Regulatory bodies — items mentioning these route to regulatory
REGULATORY_BODIES = {
    "ofgem", "neso", "crown estate", "planning inspectorate",
    "cma", "competition and markets authority",
}

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

CRITICAL DATE RULE: This report covers {start_date} to {end_date} ONLY.
Do NOT include any development dated before {start_date}. If an item is
from a previous week, it does not belong in this report regardless of
how important it is. The only exception is a consultation or process
from a previous week that has a NEW development this week (e.g. a new
response published, a deadline reached).

DEDUPLICATION RULE: If multiple source items cover the same development
(e.g. the same government announcement reported by Bloomberg, GOV.UK, and
Recharge News), consolidate them into a SINGLE item card. List all sources
in the source field (e.g. "GOV.UK press release; Bloomberg; Recharge News").
Include all source_item fingerprints. Do NOT create separate items for the
same development from different sources.

EXTRACTED FACTS:
{facts_json}

ORIGINAL SOURCE ITEMS (with full content for grounding):
{items_with_content}

For each significant development, produce a JSON object with:
- ref: section reference (e.g. "{section_number}.1", "{section_number}.2")
- headline: concise title
- date: the date of the event/publication
- source: where this came from (e.g. "GOV.UK press release, DESNZ" or "Hansard, House of Lords")
- summary: 2-4 sentences. What happened. Plain English, precise about dates, names, amounts.
- client_relevance: 2-3 sentences. Why this matters to {client_name} SPECIFICALLY.
- recommended_action: specific action (e.g. "Brief client", "Prepare consultation response", "Monitor")
- escalation: "IMMEDIATE" | "HIGH" | "STANDARD"
- rag: "RED" | "AMBER" | "GREEN"
- confidence: float 0-1
- source_items: array of fingerprint strings from the source items that support this analysis

{theme_specific_instructions}

FACTUALITY RULES (critical — your output will be evaluated against the source text):
- Your summary MUST only contain facts stated in the extracted facts or source item content above.
- If a number, date, name, or claim is not explicitly in the sources, do NOT include it.
- Do NOT add context from your own knowledge. If the source says "offshore wind" don't add that it's "in the North Sea" unless the source says so.
- Do NOT attribute statements to specific people or organisations unless the source explicitly names them. If a Hansard contribution does not identify the speaker, say "a member" or "a Lords member" rather than guessing the name.
- CRITICAL: Do NOT write "DESNZ announced", "the Department for Energy Security announced", "MoD announced", or similar department-specific attribution. Many GOV.UK publications are cross-departmental or published by agencies. Say "the government published" or "a government consultation" unless the source text EXPLICITLY names the specific department. This is a factuality requirement — fabricated attribution will be flagged.
- Your summary must ONLY contain information present in the source material provided. Do not infer dates, numbers, or facts that are not explicitly stated in the source snippets. If a source snippet is ambiguous or incomplete, say so rather than filling in details.
- When in doubt, be conservative. A shorter, fully-grounded summary beats a longer one with unsupported claims.
- Quote specific figures from the sources: MW amounts, £ values, percentages, dates.

CLIENT RELEVANCE — SPECIFICITY RULES (critical — your output will be evaluated for specificity):
The client_relevance field must reference {client_name}'s SPECIFIC situation. Do NOT write generic energy sector analysis.

BAD (generic — will be flagged):
  "This is relevant to offshore wind developers as it affects project economics."
  "RWE should monitor this development as it could impact their UK operations."

GOOD (specific — references actual projects, positions, pipeline):
  "This directly impacts RWE's Norfolk Vanguard East and West projects (3.1GW combined), which are targeting FID in summer 2026. The strike price of £91.20/MWh confirms commercial viability for these specific assets."
  "RWE's Sofia project (1.4GW) is the closest comparable UK offshore wind farm to this development. With 100 of 100 turbines now installed, RWE has operational experience directly relevant to the supply chain issues raised."

Always reference specific projects by name and capacity where relevant to the development.

CONFIDENCE CALIBRATION:
- 0.9-1.0: Government press release, official announcement, Hansard record with specific quotes, confirmed corporate filing
- 0.8-0.89: Named source in reputable outlet, multiple corroborating sources, specific figures cited
- 0.7-0.79: Single trade press report, plausible but not independently confirmed
- 0.5-0.69: Vague source, partial information, or inferred from limited context
- Below 0.5: Speculative, rumour, or very thin sourcing
Do NOT default to 0.5. Assess each item individually against this scale.

OTHER RULES:
- Every item MUST include source_items with at least one fingerprint from the provided items. If you cannot trace a claim to a specific collected item, do not include it in the output. Items with empty source_items will be automatically removed.
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
    """Render client config into a detailed text block for prompts.

    Includes project details so the analysis model can reference specific
    projects, capacities, and timelines in client_relevance text.
    """
    client = config["client"]
    lines = [
        f"Client: {client['name']} ({client['full_name']})",
        f"Sector: {client['sector']}",
        f"Country: {client['country']}",
        "",
        "Key Projects (reference these by name and capacity in client_relevance):",
    ]
    for project in config.get("projects", []):
        cap = f" ({project['capacity_mw']}MW)" if project.get("capacity_mw") else ""
        detail = f"  - {project['name']}{cap}: {project['status']} [{project['priority']}]"
        if project.get("location"):
            detail += f" — {project['location']}"
        if project.get("technology"):
            detail += f", {project['technology']}"
        lines.append(detail)

    lines.extend(["", "Escalation Triggers (IMMEDIATE):"])
    for trigger in config.get("escalation", {}).get("IMMEDIATE", []):
        lines.append(f"  - {trigger}")

    # Add strategic context if available
    if config.get("client", {}).get("strategic_priorities"):
        lines.extend(["", "Strategic Priorities:"])
        for p in config["client"]["strategic_priorities"]:
            lines.append(f"  - {p}")

    return "\n".join(lines)


def _route_item(item: dict, config: dict) -> str:
    """Assign each item to exactly ONE theme.

    Source type first, content override second.
    """
    text = f"{item.get('title', '')} {item.get('content', '')}".lower()
    source = item.get("source_name", "").lower()
    source_type = item.get("source_type", "")

    # 1. Source-type routing (primary)
    if source_type == "hansard":
        if any(r in text for r in REGULATORY_BODIES):
            return "regulatory_legal"
        return "parliamentary"

    if source_type == "govuk":
        if any(r in text for r in REGULATORY_BODIES):
            return "regulatory_legal"
        return "policy_government"

    if source_type == "committee":
        return "parliamentary"

    # 2. Web items — route by source name first
    # Also check config-derived media names
    config_media = set()
    for key in ("media_specialist", "media_national", "media_regional"):
        for name in config.get("sources", {}).get(key, []):
            config_media.add(name.lower())

    all_media = MEDIA_OUTLETS | config_media
    if any(outlet in source for outlet in all_media):
        return "media_coverage"

    if any(body in source for body in INDUSTRY_BODIES):
        return "competitor_industry"

    # 3. Web items — route by content
    if any(comp in text for comp in COMPETITOR_NAMES):
        return "competitor_industry"

    if any(r in text for r in REGULATORY_BODIES):
        return "regulatory_legal"

    if any(kw in text for kw in [
        "protest", "campaign", "opposition",
        "community", "ngo", "activist",
    ]):
        return "stakeholder_third_party"

    # 4. Default: policy_government
    return "policy_government"


def route_items_to_themes(items: list[dict], config: dict) -> dict[str, list[dict]]:
    """Route items to monitoring themes. Each item assigned to exactly one theme."""
    theme_items: dict[str, list[dict]] = {
        "policy_government": [],
        "parliamentary": [],
        "regulatory_legal": [],
        "media_coverage": [],
        "social_media": [],
        "competitor_industry": [],
        "stakeholder_third_party": [],
    }

    for item in items:
        theme = _route_item(item, config)
        if theme in theme_items:
            theme_items[theme].append(item)
        else:
            theme_items["policy_government"].append(item)

    log.info("Item routing:")
    for theme, titems in theme_items.items():
        if titems:
            log.info(f"  {theme}: {len(titems)} items")

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
    week_start: datetime | None = None,
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
    # Include full source content so the model can ground claims in actual text
    items_with_content = ""
    for i, item in enumerate(items[:30], 1):
        content = item.get("content", "")[:3000]  # Cap per item to fit context
        items_with_content += (
            f"\n[{i}] Fingerprint: {item.get('fingerprint', '')}\n"
            f"    Title: {item.get('title', '')}\n"
            f"    Source: {item.get('source_name', '')} ({item.get('source_type', '')})\n"
            f"    Date: {item.get('date', '')}\n"
            f"    Verified: {item.get('verified', False)}\n"
            f"    Content: {content}\n"
        )

    # Build date range for prompt
    if week_start:
        start_date = week_start.strftime("%-d %B %Y")
        end_date = (week_start + timedelta(days=6)).strftime("%-d %B %Y")
    else:
        start_date = "the reporting week start"
        end_date = "the reporting week end"

    prompt = ANALYSIS_PROMPT.format(
        consultancy_name=config.get("report", {}).get("consultancy_name", "WA Communications"),
        client_context=client_context,
        theme_label=theme_config["label"],
        section_number=theme_config["section"],
        facts_json=json.dumps(facts, indent=2, default=str),
        items_with_content=items_with_content,
        client_name=config["client"]["name"],
        theme_specific_instructions=THEME_SPECIFIC_INSTRUCTIONS.get(theme_id, ""),
        start_date=start_date,
        end_date=end_date,
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
