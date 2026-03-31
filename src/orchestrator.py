#!/usr/bin/env python3
"""
WA Monitoring Agent — Main Pipeline

Usage:
  python src/orchestrator.py                              # Full run, current week
  python src/orchestrator.py --week 2026-03-24            # Specific week
  python src/orchestrator.py --from-cache output/items_2026-03-24.json  # Skip collection
  python src/orchestrator.py --config src/config/rwe_client.json        # Specific client
  python src/orchestrator.py --collect-only               # Collection only
  python src/orchestrator.py --skip-eval                  # Skip evaluation (faster dev)
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import httpx
import opik
from opik import track

from collect import collect_all
from collect.content_enricher import enrich_items
from score import score_and_filter
from analyse import analyse
from evaluate import evaluate_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("orchestrator")


async def _enrich_thin(items: list[dict]) -> list[dict]:
    """Enrich items with thin content before scoring."""
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": "WA-Monitoring/1.0"},
    ) as client:
        return await enrich_items(items, client)


@track(name="full_pipeline")
def run_pipeline(args):
    """
    Full pipeline execution. Traced as a single Opik span
    with child spans for each stage.
    """
    # ── Load config ──
    config_path = args.config or "src/config/rwe_client.json"
    with open(config_path) as f:
        config = json.load(f)
    log.info(f"Client: {config['client']['name']}")

    # ── Determine reporting period ──
    if args.week:
        week_start = datetime.strptime(args.week, "%Y-%m-%d")
    else:
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=4)
    log.info(f"Period: {week_start:%d %b %Y} – {week_end:%d %b %Y}")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set")
        sys.exit(1)

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    # ── Stage 1: COLLECT ──
    if args.from_cache:
        log.info(f"Loading cached items: {args.from_cache}")
        with open(args.from_cache) as f:
            scored_items = json.load(f)
    else:
        log.info("=" * 50)
        log.info("STAGE 1: COLLECT")
        log.info("=" * 50)
        raw_items = asyncio.run(collect_all(config, week_start, api_key))
        log.info(f"Collected: {len(raw_items)} raw items")

        # Save raw items before enrichment for diagnostics
        raw_path = output_dir / f"raw_items_{week_start:%Y-%m-%d}.json"
        with open(raw_path, "w") as f:
            json.dump(
                [item.__dict__ if hasattr(item, "__dict__") else item for item in raw_items],
                f, indent=2, default=str,
            )
        log.info(f"Saved {len(raw_items)} raw items to {raw_path}")

        # ── Stage 1b: ENRICH thin items BEFORE scoring ──
        log.info("=" * 50)
        log.info("STAGE 1b: ENRICH THIN ITEMS")
        log.info("=" * 50)
        raw_items = asyncio.run(_enrich_thin(raw_items))

        # ── Stage 2: SCORE & FILTER ──
        log.info("=" * 50)
        log.info("STAGE 2: SCORE & FILTER")
        log.info("=" * 50)
        scored_items = asyncio.run(score_and_filter(raw_items, config, week_start))
        log.info(f"After scoring: {len(scored_items)} items")

        # Cache
        items_path = output_dir / f"items_{week_start:%Y-%m-%d}.json"
        with open(items_path, "w") as f:
            json.dump(scored_items, f, indent=2, default=str)
        log.info(f"Cached to {items_path}")

    if args.collect_only:
        log.info("--collect-only: stopping here")
        return

    # ── Stage 3: ANALYSE ──
    log.info("=" * 50)
    log.info("STAGE 3: ANALYSE")
    log.info("=" * 50)
    analysis = asyncio.run(
        analyse(scored_items, config, api_key, week_start)
    )

    analysis_path = output_dir / f"analysis_{week_start:%Y-%m-%d}.json"
    with open(analysis_path, "w") as f:
        json.dump(analysis, f, indent=2, default=str)
    log.info(f"Analysis saved to {analysis_path}")

    # ── Stage 4: EVALUATE (pre-generation) ──
    eval_results = None
    if not args.skip_eval:
        log.info("=" * 50)
        log.info("STAGE 4: EVALUATE")
        log.info("=" * 50)
        eval_results = evaluate_report(analysis, scored_items, config)

        eval_path = output_dir / f"eval_{week_start:%Y-%m-%d}.json"
        with open(eval_path, "w") as f:
            json.dump(eval_results, f, indent=2, default=str)

        # Log summary
        tv = eval_results["template_validation"]
        log.info(
            f"Template: {'PASS' if tv['passed'] else 'FAIL'} "
            f"({len(tv['errors'])} errors, {len(tv['warnings'])} warnings)"
        )
        log.info(
            f"Factuality: {eval_results['factuality']['mean_score']:.2f} "
            f"({len(eval_results['factuality']['flagged_items'])} flagged)"
        )
        log.info(
            f"Specificity: {eval_results['specificity']['mean_score']:.2f} "
            f"({len(eval_results['specificity']['flagged_items'])} flagged)"
        )
        log.info(f"Overall: {'PASS' if eval_results['overall_pass'] else 'REVIEW NEEDED'}")

        # Update analysis with flagged items for DOCX rendering
        all_flagged = set(eval_results.get("flagged_refs", []))
        for theme_data in analysis["sections"].values():
            for item in theme_data.get("items", []):
                if item.get("ref") in all_flagged:
                    item["confidence"] = min(item.get("confidence", 1.0), 0.5)
            for item in theme_data.get("significant_items", []):
                if item.get("ref") in all_flagged:
                    item["confidence"] = min(item.get("confidence", 1.0), 0.5)

        # Re-save analysis with updated confidence
        with open(analysis_path, "w") as f:
            json.dump(analysis, f, indent=2, default=str)

    # ── Stage 5: GENERATE DOCX ──
    log.info("=" * 50)
    log.info("STAGE 5: GENERATE DOCX")
    log.info("=" * 50)

    display_name = config["client"].get("report_display_name", config["client"]["name"])
    client_name_slug = display_name.replace(" ", "_")
    report_filename = f"{client_name_slug}_Weekly_Report_{week_start:%Y-%m-%d}.docx"
    report_path = output_dir / report_filename

    result = subprocess.run(
        [
            "node", str(Path(__file__).resolve().parent / "generate" / "generate-report.js"),
            "--analysis", str(analysis_path),
            "--config", config_path,
            "--output", str(report_path),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        log.error(f"DOCX generation failed: {result.stderr}")
        sys.exit(1)

    log.info(f"Report generated: {report_path}")

    # ── DONE ──
    log.info("=" * 50)
    log.info("PIPELINE COMPLETE")
    log.info("=" * 50)
    log.info(f"Report: {report_path}")
    if eval_results:
        log.info(
            f"Quality: factuality={eval_results['factuality']['mean_score']:.2f}, "
            f"specificity={eval_results['specificity']['mean_score']:.2f}"
        )
        if eval_results["flagged_refs"]:
            log.info(f"Flagged for review: {', '.join(eval_results['flagged_refs'])}")
    log.info("Opik dashboard: http://localhost:5173")


def main():
    parser = argparse.ArgumentParser(description="WA Monitoring Agent")
    parser.add_argument("--week", type=str, help="Week start date YYYY-MM-DD")
    parser.add_argument("--config", type=str, help="Client config JSON path")
    parser.add_argument("--from-cache", type=str, help="Load items from cached JSON")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--skip-eval", action="store_true")
    args = parser.parse_args()

    # Init Opik
    try:
        opik.configure(use_local=True)
    except Exception as e:
        log.warning(f"Opik init failed (dashboard may not be running): {e}")

    run_pipeline(args)


if __name__ == "__main__":
    main()
