"""Template compliance validator — deterministic checks on analysis.json structure."""

import re


def validate_template_compliance(analysis: dict) -> list[dict]:
    """
    Returns a list of validation failures.
    Each: {"check": str, "severity": "error"|"warning", "detail": str}
    Empty list = all checks passed.
    """
    failures = []

    def error(check: str, detail: str):
        failures.append({"check": check, "severity": "error", "detail": detail})

    def warning(check: str, detail: str):
        failures.append({"check": check, "severity": "warning", "detail": detail})

    # ── Executive summary ──
    es = analysis.get("executive_summary")
    if not es:
        error("exec_summary_exists", "executive_summary is missing")
    else:
        if not es.get("top_line"):
            error("exec_summary_topline", "executive_summary.top_line is empty")

        kd = es.get("key_developments", [])
        if len(kd) < 4:
            error("exec_summary_kd_count", f"key_developments has {len(kd)} items, expected 4-6")
        elif len(kd) > 6:
            warning("exec_summary_kd_count", f"key_developments has {len(kd)} items, expected 4-6")

        # Key developments fields
        for i, dev in enumerate(kd):
            for field in ["rag", "development", "relevance", "recommended_action", "section_ref"]:
                if not dev.get(field):
                    error("kd_field_missing", f"key_developments[{i}] missing '{field}'")

            if dev.get("rag") not in ("RED", "AMBER", "GREEN"):
                error("kd_rag_invalid", f"key_developments[{i}] rag='{dev.get('rag')}' invalid")

            # Cross-reference check
            ref = dev.get("section_ref", "")
            if ref and not _ref_exists_in_sections(ref, analysis.get("sections", {})):
                error("kd_xref_invalid", f"key_developments[{i}] section_ref '{ref}' not found in sections")

    # ── Theme sections ──
    required_themes = [
        "policy_government", "parliamentary", "regulatory_legal",
        "media_coverage", "social_media", "competitor_industry",
        "stakeholder_third_party",
    ]
    sections = analysis.get("sections", {})
    for theme in required_themes:
        if theme not in sections:
            error("section_missing", f"sections.{theme} is missing")

    # ── Item cards ──
    for theme_id, theme_data in sections.items():
        items_list = theme_data.get("items", [])
        if theme_id == "media_coverage":
            items_list = theme_data.get("significant_items", [])

        for i, item in enumerate(items_list):
            prefix = f"sections.{theme_id}.items[{i}]"

            for field in ["ref", "headline", "date", "source", "summary",
                          "client_relevance", "recommended_action"]:
                if not item.get(field):
                    error("item_field_missing", f"{prefix} missing '{field}'")

            # Summary sentence count (2-4 sentences)
            summary = item.get("summary", "")
            sentence_count = len(re.findall(r'[.!?]+', summary))
            if sentence_count < 2:
                warning("item_summary_short", f"{prefix} summary has ~{sentence_count} sentences, expected 2-4")
            elif sentence_count > 6:
                warning("item_summary_long", f"{prefix} summary has ~{sentence_count} sentences, expected 2-4")

            # Client relevance sentence count (2-3 sentences)
            cr = item.get("client_relevance", "")
            cr_count = len(re.findall(r'[.!?]+', cr))
            if cr_count < 2:
                warning("item_cr_short", f"{prefix} client_relevance has ~{cr_count} sentences, expected 2-3")

            # Escalation
            if item.get("escalation") not in ("IMMEDIATE", "HIGH", "STANDARD"):
                error("item_escalation_invalid", f"{prefix} escalation='{item.get('escalation')}' invalid")

            # Source provenance
            if not item.get("source_items"):
                error("item_no_provenance", f"{prefix} has empty source_items")

            # Confidence
            conf = item.get("confidence")
            if conf is None:
                warning("item_no_confidence", f"{prefix} has no confidence score")
            elif conf == 1.0:
                warning("item_confidence_1", f"{prefix} confidence is exactly 1.0 (uncalibrated)")
            elif conf == 0.0:
                warning("item_confidence_0", f"{prefix} confidence is exactly 0.0")

    # ── Parliamentary section ──
    parl = sections.get("parliamentary", {})
    for i, rm in enumerate(parl.get("routine_mentions", [])):
        for field in ["date", "type", "detail", "members", "significance"]:
            if not rm.get(field):
                warning("routine_mention_field", f"parliamentary.routine_mentions[{i}] missing '{field}'")

    # ── Media section ──
    media = sections.get("media_coverage", {})
    for i, row in enumerate(media.get("coverage_table", [])):
        for field in ["date", "outlet", "angle", "client_named", "action"]:
            if not row.get(field):
                warning("media_row_field", f"media_coverage.coverage_table[{i}] missing '{field}'")

    # ── Forward look ──
    fl = analysis.get("forward_look", [])
    if len(fl) < 1:
        error("forward_look_empty", "forward_look has no items")

    # ── Emerging themes ──
    et = analysis.get("emerging_themes", [])
    if len(et) < 2:
        error("emerging_themes_count", f"emerging_themes has {len(et)} items, expected 2-4")
    elif len(et) > 4:
        warning("emerging_themes_count", f"emerging_themes has {len(et)} items, expected 2-4")

    # ── Actions tracker ──
    if "actions_tracker" not in analysis:
        error("actions_tracker_missing", "actions_tracker is missing")

    # ── Coverage summary ──
    cs = analysis.get("coverage_summary", [])
    if "coverage_summary" not in analysis:
        error("coverage_summary_missing", "coverage_summary is missing")
    else:
        for i, row in enumerate(cs):
            for field in ["metric", "this_week", "previous_week", "trend"]:
                if not row.get(field):
                    warning("coverage_row_field", f"coverage_summary[{i}] missing '{field}'")

        # Required metrics
        metrics = {row.get("metric", "").lower() for row in cs}
        for required in ["total media mentions", "parliamentary mentions", "competitor share"]:
            if not any(required in m for m in metrics):
                warning("coverage_metric_missing", f"coverage_summary missing required metric containing '{required}'")

    # ── Empty section handling ──
    for theme_id, theme_data in sections.items():
        items_list = theme_data.get("items", [])
        if theme_id == "media_coverage":
            items_list = theme_data.get("significant_items", [])
        if not items_list and not theme_data.get("no_developments"):
            if theme_id not in ("media_coverage", "social_media", "competitor_industry"):
                warning("empty_section_no_flag", f"sections.{theme_id} has no items but no_developments is not set")

    return failures


def _ref_exists_in_sections(ref: str, sections: dict) -> bool:
    """Check if a section_ref exists in any theme's items."""
    for theme_data in sections.values():
        for item in theme_data.get("items", []):
            if item.get("ref") == ref:
                return True
        for item in theme_data.get("significant_items", []):
            if item.get("ref") == ref:
                return True
    return False
