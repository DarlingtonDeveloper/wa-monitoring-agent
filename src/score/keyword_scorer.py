"""Keyword-based relevance scorer for collected items."""

import re
from datetime import datetime, timedelta


# ── Geographic filtering (Section 5.3 of monitoring briefing) ──

NON_UK_COUNTRIES = [
    "germany", "german", "deutschland", "bundestag", "bundesrat",
    "lignite", "lützerath", "lutzerath", "hambach", "rheinland",
    "north rhine", "westphalia", "nordseecluster",
    "poland", "polish", "baltic ii", "pge",
    "united states", "u.s.", "american", "congress",
    "australia", "australian",
    "netherlands", "dutch",
    "denmark", "danish",
    "japan", "japanese", "taiwan", "taiwanese",
    "india", "indian", "china", "chinese",
    "france", "french", "spain", "spanish",
    "italy", "italian", "portugal", "portuguese",
    "norway", "norwegian", "sweden", "swedish",
]

UK_MARKERS = [
    "uk", "united kingdom", "britain", "british", "england",
    "scotland", "scottish", "wales", "welsh", "northern ireland",
    "westminster", "parliament", "hansard", "commons", "lords",
    "desnz", "ofgem", "neso", "crown estate", "great british energy",
    "london", "grimsby", "teesside", "norfolk", "swindon",
    "dogger bank", "port of tyne", "lackenby", "humber",
    "suffolk", "lincolnshire", "north wales", "irish sea",
]


def flatten_keywords(keyword_list: list[str]) -> list[str]:
    """Clean a keyword list: lowercase, strip quotes, split on AND/OR, skip short terms."""
    cleaned = []
    for kw in keyword_list:
        kw = kw.strip('"').strip("'")
        parts = re.split(r'\s+(?:AND|OR)\s+', kw)
        for part in parts:
            part = part.strip().lower()
            if len(part) >= 3:
                cleaned.append(part)
    return list(set(cleaned))


def flatten_all_keywords(config: dict) -> list[str]:
    """Extract all keywords across all groups from config."""
    all_kw = []
    for group in config.get("keywords", {}).values():
        all_kw.extend(flatten_keywords(group))
    return list(set(all_kw))


def _parse_date(date_str: str) -> datetime | None:
    """Try to parse a date string in common formats."""
    if not date_str:
        return None
    for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d %B %Y"]:
        try:
            return datetime.strptime(date_str[:19], fmt)
        except ValueError:
            continue
    return None


def is_within_reporting_window(
    item_date_str: str, week_start: datetime, buffer_days: int = 1
) -> bool:
    """
    Returns True if the item falls within the reporting week +/- buffer.
    Buffer of 1 day allows Sunday before and Saturday after the Mon-Fri week.
    Items without a parseable date pass through (filtered later by analysis).
    """
    if not item_date_str:
        return True  # no date = can't filter, let analysis decide
    item_date = _parse_date(item_date_str)
    if item_date is None:
        return True
    window_start = week_start - timedelta(days=buffer_days)
    window_end = week_start + timedelta(days=6 + buffer_days)
    return window_start <= item_date <= window_end


def is_uk_relevant(item: dict) -> bool:
    """
    Returns False if the item is clearly about a non-UK country
    with no UK connection. Implements Section 5.3 of monitoring briefing.
    """
    text = f"{item.get('title', '')} {item.get('content', '')}".lower()

    non_uk = any(term in text for term in NON_UK_COUNTRIES)
    uk = any(term in text for term in UK_MARKERS)

    if non_uk and not uk:
        return False
    return True


def apply_false_positive_rules(item: dict) -> bool:
    """
    Implements Section 5.3 of the monitoring briefing.
    Returns False if the item is a false positive.
    """
    text = f"{item.get('title', '')} {item.get('content', '')}".lower()

    # "RWE" in pharma context = false positive
    if "rwe" in text and "real-world evidence" in text:
        if not any(kw in text for kw in ["energy", "wind", "power", "renewable", "electricity"]):
            return False

    # Ambiguous project names without qualifiers
    AMBIGUOUS = {
        "sofia": ["wind", "rwe", "offshore", "dogger bank", "turbine"],
        "raspberry": ["wind", "rwe", "solar", "energy", "cfd"],
        "belvoir": ["wind", "rwe", "solar", "energy", "cfd"],
    }
    for name, qualifiers in AMBIGUOUS.items():
        if name in text and not any(q in text for q in qualifiers):
            return False

    return True


# Priority sources — Section 6 of monitoring briefing. Always relevant.
PRIORITY_SOURCES = [
    "ofgem", "neso", "crown estate", "energy uk",
    "renewableuk", "ore catapult", "climate change committee",
    "great british energy", "planning inspectorate",
    "north sea transition authority", "national infrastructure commission",
]

ACTIONABLE_SIGNALS = [
    "consultation", "decision", "announcement", "legislation",
    "regulation", "reform", "published", "launches", "confirms",
    "deadline", "application", "licence", "consent", "allocation",
    "contract", "investment", "acquisition", "ban", "restriction",
]

# Known RWE project names for tier 1 bonus
PROJECT_NAMES = [
    "norfolk vanguard", "dogger bank", "sofia",
    "triton knoll", "awel y mor", "greater gabbard",
]


def score_item(item: dict, config: dict) -> float:
    """Two-tier scoring. Returns 0-1 float.

    Tier 1: Client named → always relevant, score 0.5+
    Tier 2: Sector keywords → only relevant if actionable, score capped at 0.45
    """
    text = f"{item.get('title', '')} {item.get('content', '')}".lower()

    # TIER 1: Client-specific mentions (always relevant)
    client_terms = flatten_keywords(config.get("keywords", {}).get("rwe_corporate", []))
    client_match = any(term in text for term in client_terms)

    if client_match:
        score = 0.5
        project_matches = sum(1 for p in PROJECT_NAMES if p in text)
        score += project_matches * 0.1
        return min(score, 1.0)

    # TIER 2: Sector keywords (only relevant if actionable)
    sector_keywords = []
    for group_name, group_terms in config.get("keywords", {}).items():
        if group_name != "rwe_corporate":
            sector_keywords.extend(flatten_keywords(group_terms))

    sector_matches = sum(1 for kw in sector_keywords if kw in text)
    actionable = any(signal in text for signal in ACTIONABLE_SIGNALS)

    if sector_matches >= 2 and actionable:
        score = 0.1 + (sector_matches * 0.04)
        return min(score, 0.45)

    if sector_matches >= 4:
        score = 0.1 + (sector_matches * 0.03)
        return min(score, 0.35)

    # Below tier thresholds — start at base score
    score = 0.05

    # Floor for parliamentary items — Hansard is always worth keeping
    if item.get("source_type") == "hansard":
        score = max(score, 0.12)

    # Priority source floor — Section 6 of monitoring briefing
    source_lower = item.get("source_name", "").lower()
    if any(ps in source_lower for ps in PRIORITY_SOURCES):
        score = max(score, 0.20)

    return score
