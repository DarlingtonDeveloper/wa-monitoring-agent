"""Analysis layer — Claude-powered theme analysis and synthesis."""

import json
import logging
from datetime import datetime
from pathlib import Path

import anthropic
from opik import track

from .theme_analyser import analyse_theme, route_items_to_themes, build_client_context
from .synthesiser import synthesise

log = logging.getLogger(__name__)


@track(name="full_analysis")
async def analyse(
    items: list[dict],
    config: dict,
    anthropic_api_key: str,
    week_start: datetime,
) -> dict:
    """
    1. Build client context
    2. Route items to themes
    3. Run theme analyses
    4. Separate forward scan items
    5. Run synthesis
    6. Merge into analysis.json schema
    7. Validate and return
    """
    ant_client = anthropic.Anthropic(api_key=anthropic_api_key)
    client_context = build_client_context(config)

    # Separate forward scan items
    forward_items = [i for i in items if i.get("source_type") == "forward_scan"]
    monitor_items = [i for i in items if i.get("source_type") != "forward_scan"]

    # Route items to themes
    theme_items = route_items_to_themes(monitor_items, config)

    # Run theme analyses
    theme_results = {}
    for theme in config["monitoring_themes"]:
        theme_id = theme["id"]
        routed = theme_items.get(theme_id, [])
        log.info(f"Analysing theme '{theme_id}': {len(routed)} items")

        result = analyse_theme(
            theme_id=theme_id,
            theme_config=theme,
            items=routed,
            client_context=client_context,
            config=config,
            anthropic_client=ant_client,
        )
        theme_results[theme_id] = result

    # Run synthesis
    log.info("Running synthesis...")
    week_end = week_start + __import__("datetime").timedelta(days=4)
    reporting_period = f"w/c {week_start.strftime('%-d %B %Y')}"

    synthesis = synthesise(
        theme_results=theme_results,
        forward_items=forward_items,
        config=config,
        anthropic_client=ant_client,
    )

    # Merge into full analysis output
    analysis = {
        "metadata": {
            "client_name": config["client"]["name"],
            "reporting_period": reporting_period,
            "report_date": datetime.now().strftime("%-d %B %Y"),
            "generated_at": datetime.now().isoformat(),
            "items_collected": len(items),
            "items_scored": len(monitor_items),
            "items_analysed": sum(
                len(v.get("items", []))
                for v in theme_results.values()
            ),
            "sources_unavailable": [],
        },
        "executive_summary": synthesis.get("executive_summary", {
            "top_line": "",
            "key_developments": [],
        }),
        "sections": theme_results,
        "forward_look": synthesis.get("forward_look", []),
        "emerging_themes": synthesis.get("emerging_themes", []),
        "actions_tracker": synthesis.get("actions_tracker", []),
        "coverage_summary": synthesis.get("coverage_summary", []),
    }

    # Ensure all sections have required structure
    _ensure_section_structure(analysis["sections"])

    # Validate
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from schemas import validate_analysis
    errors = validate_analysis(analysis)
    if errors:
        log.warning(f"Analysis validation: {len(errors)} errors")
        for e in errors[:5]:
            log.warning(f"  - {e}")
    else:
        log.info("Analysis validates against schema")

    return analysis


def _ensure_section_structure(sections: dict):
    """Ensure all theme sections have their required keys."""
    defaults = {
        "policy_government": {"items": []},
        "parliamentary": {"items": [], "routine_mentions": []},
        "regulatory_legal": {"items": []},
        "media_coverage": {"coverage_table": [], "significant_items": []},
        "social_media": {
            "summary": "",
            "metrics": {
                "total_mentions": "N/A",
                "sentiment_breakdown": "N/A",
                "top_engagement_post": "N/A",
                "trend_vs_previous": "N/A",
            },
            "notable_posts": [],
        },
        "competitor_industry": {"table": []},
        "stakeholder_third_party": {"items": [], "no_developments": True},
    }

    for theme_id, default_data in defaults.items():
        if theme_id not in sections:
            sections[theme_id] = default_data
        else:
            for key, default_val in default_data.items():
                if key not in sections[theme_id]:
                    sections[theme_id][key] = default_val
