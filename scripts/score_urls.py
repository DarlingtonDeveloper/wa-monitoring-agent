#!/usr/bin/env python3
"""
Fetch 5 URLs, extract content with BeautifulSoup, run through two-tier scorer.
Show score and which keywords matched.
"""
import json
import sys

sys.path.insert(0, "src")

import httpx
from bs4 import BeautifulSoup
from score.keyword_scorer import (
    score_item,
    flatten_keywords,
    ACTIONABLE_SIGNALS,
    PROJECT_NAMES,
)

# Load config for scorer
with open("src/config/rwe_client.json") as f:
    config = json.load(f)

URLS = [
    "https://www.gov.uk/government/publications/energy-digitalisation-framework-a-vision-for-a-coordinated-and-connected-energy-system",
    "https://www.gov.uk/government/consultations/whole-energy-cyber-resilience-requirements-reshaping-cyber-regulation-in-downstream-gas-and-electricity",
    "https://www.gov.uk/government/consultations/energy-code-reform-code-manager-licence-conditions-and-code-modification-appeals-to-the-cma",
    "https://www.ofgem.gov.uk/energy-regulation/how-we-regulate/energy-network-price-controls",
    "https://www.ofgem.gov.uk/consultations/consultations-and-calls-input",
]


def fetch_and_extract(url: str, client: httpx.Client) -> str:
    """Fetch URL and extract main text with BeautifulSoup."""
    resp = client.get(url, follow_redirects=True, timeout=15)
    if resp.status_code != 200:
        return f"[HTTP {resp.status_code}]"
    if "html" not in resp.headers.get("content-type", "").lower():
        return "[not HTML]"

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup.find_all(["nav", "footer", "script", "style", "header", "aside"]):
        tag.decompose()
    main = soup.find("article") or soup.find("main") or soup.find("body")
    if main:
        text = main.get_text(separator=" ", strip=True)
        text = " ".join(text.split())
        return text[:8000]
    return "[no content found]"


def analyse_score(item: dict, config: dict):
    """Show detailed scoring breakdown."""
    text = f"{item.get('title', '')} {item.get('content', '')}".lower()

    # Tier 1: Client terms
    client_terms = flatten_keywords(config.get("keywords", {}).get("rwe_corporate", []))
    client_matches = [t for t in client_terms if t in text]

    # Tier 2: Sector keywords
    sector_keywords = []
    for group_name, group_terms in config.get("keywords", {}).items():
        if group_name != "rwe_corporate":
            sector_keywords.extend(flatten_keywords(group_terms))
    sector_matches = [kw for kw in sector_keywords if kw in text]

    # Actionable signals
    actionable_matches = [s for s in ACTIONABLE_SIGNALS if s in text]

    # Project names
    project_matches = [p for p in PROJECT_NAMES if p in text]

    # Get actual score
    score = score_item(item, config)

    return {
        "score": score,
        "client_matches": client_matches,
        "sector_matches": sector_matches,
        "actionable_matches": actionable_matches,
        "project_matches": project_matches,
        "sector_count": len(sector_matches),
        "has_actionable": len(actionable_matches) > 0,
    }


with httpx.Client(headers={"User-Agent": "WA-Monitoring/1.0"}) as client:
    for url in URLS:
        print(f"\n{'='*80}")
        print(f"URL: {url}")
        print(f"{'='*80}")

        content = fetch_and_extract(url, client)
        content_len = len(content)
        print(f"Extracted content: {content_len} chars")
        print(f"First 300 chars: {content[:300]}")
        print()

        # Build item dict
        item = {
            "title": url.split("/")[-1].replace("-", " "),
            "content": content,
            "source_type": "govuk",
            "source_name": "GOV.UK",
            "url": url,
        }

        result = analyse_score(item, config)

        print(f"SCORE: {result['score']}")
        print(f"  Tier 1 (client terms matched): {result['client_matches'] or 'NONE'}")
        print(f"  Tier 2 sector keywords ({result['sector_count']}): {result['sector_matches'][:15]}")
        if result["sector_count"] > 15:
            print(f"    ... and {result['sector_count'] - 15} more")
        print(f"  Actionable signals: {result['actionable_matches'] or 'NONE'}")
        print(f"  Project names: {result['project_matches'] or 'NONE'}")
        print()

        # Explain scoring decision
        if result["client_matches"]:
            print(f"  TIER 1 HIT: Client named → score 0.5+")
        elif result["sector_count"] >= 2 and result["has_actionable"]:
            print(f"  TIER 2 HIT: {result['sector_count']} sector keywords + actionable → score capped at 0.45")
        elif result["sector_count"] >= 4:
            print(f"  TIER 2 HIT: {result['sector_count']} sector keywords (high density) → score capped at 0.35")
        else:
            print(f"  BELOW THRESHOLD: {result['sector_count']} sector keywords, actionable={result['has_actionable']}")
            print(f"  Needs: (>=2 sector + actionable) OR (>=4 sector)")
