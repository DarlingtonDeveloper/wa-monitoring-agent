"""Evaluation layer — template validation and LLM-as-judge."""

import logging

from opik import track

from .template_validator import validate_template_compliance
from .judge import run_factuality_check, run_specificity_check

log = logging.getLogger(__name__)


@track(name="full_evaluation")
def evaluate_report(
    analysis: dict,
    items_cache: list[dict],
    config: dict,
) -> dict:
    """
    Run all evaluation checks and return merged results.
    """
    # 1. Template validation
    log.info("Running template validation...")
    failures = validate_template_compliance(analysis)
    errors = [f for f in failures if f["severity"] == "error"]
    warnings = [f for f in failures if f["severity"] == "warning"]

    template_result = {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }

    # 2. Factuality check
    log.info("Running factuality check...")
    try:
        factuality = run_factuality_check(analysis, items_cache)
    except Exception as e:
        log.error(f"Factuality check failed: {e}")
        factuality = {"mean_score": 0.0, "flagged_items": [], "total_checked": 0}

    # Debug: print flagged factuality items for inspection
    for detail in factuality.get("item_details", []):
        if detail["score"] < 0.7:
            print(f"\n=== FLAGGED: {detail['reference']} (score: {detail['score']:.2f}) ===")
            print(f"REASON:  {detail.get('reason', 'N/A')}")
            print(f"SUMMARY: {detail['output'][:300]}")
            print(f"SOURCE:  {detail['input'][:300]}")
            print("===")

    # 3. Specificity check
    log.info("Running specificity check...")
    try:
        specificity = run_specificity_check(analysis, config)
    except Exception as e:
        log.error(f"Specificity check failed: {e}")
        specificity = {"mean_score": 0.0, "flagged_items": [], "total_checked": 0}

    # Overall pass/fail
    overall_pass = (
        template_result["passed"]
        and factuality.get("mean_score", 0) > 0.7
        and specificity.get("mean_score", 0) > 0.5
    )

    # Collect all flagged refs
    flagged_refs = list(set(
        factuality.get("flagged_items", []) +
        specificity.get("flagged_items", [])
    ))

    return {
        "template_validation": template_result,
        "factuality": factuality,
        "specificity": specificity,
        "overall_pass": overall_pass,
        "flagged_refs": flagged_refs,
    }
