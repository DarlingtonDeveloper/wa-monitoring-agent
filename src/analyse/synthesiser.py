"""Cross-theme synthesis — executive summary, forward look, emerging themes.

Uses Opus with extended thinking for the highest-quality cross-cutting analysis.
"""

import json
import logging
import re

import anthropic
from opik import track

from utils.retry import retry_api_call

log = logging.getLogger(__name__)

MODEL_SYNTHESIS = "claude-opus-4-6"

SYNTHESIS_PROMPT = """You are a senior public affairs analyst at {consultancy_name}.

CLIENT: {client_name}
REPORTING PERIOD: {reporting_period}

THEME ANALYSIS RESULTS:
{theme_results_json}

FORWARD-LOOKING ITEMS:
{forward_items_text}

CROSS-THEME DEDUPLICATION: Check whether the same development appears in
multiple theme sections. If the Crown Estate Leasing Round 6 appears in
both policy_government and regulatory_legal, keep it in the most relevant
section only and cross-reference from the other. Do not duplicate item cards
across sections.

NARRATIVE CONNECTION: Where multiple items relate to the same narrative
(e.g. a new turbine factory + a ban on a competing manufacturer + a turbine
order for a specific project), note the connection explicitly in the
emerging_themes section.

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
   Array of metrics: total media mentions (client), national media mentions, trade/specialist mentions, social media mentions (client), parliamentary mentions (client + key issues), competitor share of voice (top 3). Each: metric, this_week (string), previous_week ("[Baseline TBC]"), trend.
   IMPORTANT: Use arrow unicode characters in trend values: \\u2191 for increase, \\u2193 for decrease, \\u2194 for stable. Example: "\\u2191 Significant increase" or "\\u2194 Stable".
   IMPORTANT: All values in this_week and previous_week MUST be strings, even if they are numbers. E.g. "12" not 12.

Return ONLY a JSON object with keys: executive_summary, forward_look, emerging_themes, actions_tracker, coverage_summary."""


@track(name="synthesis")
def synthesise(
    theme_results: dict[str, dict],
    forward_items: list[dict],
    config: dict,
    anthropic_client: anthropic.Anthropic,
) -> dict:
    """Synthesise theme results into cross-cutting sections (Opus + extended thinking)."""
    client_name = config["client"]["name"]
    consultancy = config.get("report", {}).get("consultancy_name", "WA Communications")

    # Build forward items text
    forward_text = ""
    if forward_items:
        for i, item in enumerate(forward_items[:20], 1):
            forward_text += (
                f"[{i}] {item.get('title', '')} | {item.get('date', '')} | "
                f"{item.get('content', '')}\n"
            )
    else:
        forward_text = "No forward-looking items collected."

    # Build reporting period from current date context
    from datetime import datetime, timedelta
    now = datetime.now()
    week_start = now - timedelta(days=now.weekday())
    reporting_period = f"w/c {week_start.strftime('%-d %B %Y')}"

    prompt = SYNTHESIS_PROMPT.format(
        consultancy_name=consultancy,
        client_name=client_name,
        reporting_period=reporting_period,
        theme_results_json=json.dumps(theme_results, indent=2, default=str),
        forward_items_text=forward_text,
    )

    try:
        response = retry_api_call(
            anthropic_client.messages.create,
            model=MODEL_SYNTHESIS,
            max_tokens=20000,
            thinking={"type": "enabled", "budget_tokens": 16000},
            messages=[{"role": "user", "content": prompt}],
        )

        # Extract text (skip thinking blocks)
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        result = json.loads(text.strip())

        # Validate expected keys
        expected = ["executive_summary", "forward_look", "emerging_themes",
                     "actions_tracker", "coverage_summary"]
        for key in expected:
            if key not in result:
                log.warning(f"Synthesis missing key: {key}")
                result[key] = _default_for(key, reporting_period)

        return result

    except Exception as e:
        log.error(f"Synthesis failed: {e}")
        return _fallback_synthesis(reporting_period)


def _default_for(key: str, reporting_period: str):
    """Return a safe default for a missing synthesis key."""
    defaults = {
        "executive_summary": {
            "top_line": "Analysis synthesis was incomplete. Manual review required.",
            "key_developments": [],
        },
        "forward_look": [],
        "emerging_themes": ["No emerging themes identified in this reporting period."],
        "actions_tracker": [],
        "coverage_summary": [],
    }
    return defaults.get(key, [])


def _fallback_synthesis(reporting_period: str) -> dict:
    """Return a complete fallback synthesis on failure."""
    return {
        "executive_summary": {
            "top_line": "Automated synthesis was unavailable. Manual review of theme analyses required.",
            "key_developments": [],
        },
        "forward_look": [],
        "emerging_themes": [
            "Automated synthesis was unavailable for this reporting period.",
            "Please review individual theme analyses for detailed findings.",
        ],
        "actions_tracker": [],
        "coverage_summary": [],
    }
