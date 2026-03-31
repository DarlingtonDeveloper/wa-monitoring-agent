#!/usr/bin/env python3
"""
Trace each of Angus's 13 missed items through the collection.
For each item: is it in raw collection? What source? What score?
Did it survive scoring? Did it survive the 150 cap?
"""
import json

# Load raw items (before scoring)
with open("output/raw_items_2026-03-23.json") as f:
    raw = json.load(f)

# Load scored items (after scoring, the 150)
with open("output/items_2026-03-23.json") as f:
    scored = json.load(f)

ANGUS_ITEMS = [
    {
        "name": "Chancellor's statement to Parliament",
        "search": ["chancellor", "reeves", "energy bailout", "profiteering"],
        "url_fragment": "chancellor",
    },
    {
        "name": "Energy profit cap (Politico)",
        "search": ["profit cap", "energy profits", "cap energy"],
        "url_fragment": "politico",
    },
    {
        "name": "Decoupling gas/electricity (Sky News)",
        "search": ["decoupling", "decouple", "gas prices electricity"],
        "url_fragment": "sky",
    },
    {
        "name": "North Sea drilling debate",
        "search": ["north sea drilling", "drilling the north sea"],
        "url_fragment": None,
    },
    {
        "name": "Ofgem locational charges call for evidence",
        "search": ["locational", "locational charges", "siting levers"],
        "url_fragment": "ofgem",
    },
    {
        "name": "Guardian Iran delays offshore wind",
        "search": ["iran", "iran war", "delay offshore wind"],
        "url_fragment": "guardian",
    },
    {
        "name": "Energy digitalisation framework",
        "search": ["digitalisation", "digitalization", "digital framework"],
        "url_fragment": "digitalisation",
    },
    {
        "name": "Planning reform proposals",
        "search": ["planning application fees", "streamlining infrastructure planning"],
        "url_fragment": "planning",
    },
    {
        "name": "Cyber security consultation",
        "search": ["cyber", "cyber resilience", "whole energy cyber"],
        "url_fragment": "cyber",
    },
    {
        "name": "Energy code reform",
        "search": ["code reform", "code manager", "code modification"],
        "url_fragment": "code-reform",
    },
    {
        "name": "Carbon storage licensing",
        "search": ["carbon storage", "north sea acres"],
        "url_fragment": "carbon-storage",
    },
    {
        "name": "Select committee energy resilience (25 March)",
        "search": ["energy resilience", "oral evidence", "25 march"],
        "url_fragment": "committees.parliament",
    },
    {
        "name": "Energy UK reports Scotland/Wales",
        "search": ["bold vision", "energy uk scotland", "energy uk wales"],
        "url_fragment": "energy-uk",
    },
]

def search_items(items, search_terms, url_fragment=None):
    """Search a list of items for any matching term."""
    matches = []
    for item in items:
        text = f"{item.get('title', '')} {item.get('content', '')}".lower()
        url = item.get("url", "").lower()

        term_match = any(term in text for term in search_terms)
        url_match = url_fragment and url_fragment in url

        if term_match or url_match:
            matches.append(item)
    return matches

print(f"Raw items: {len(raw)}")
print(f"Scored items: {len(scored)}")
print()

for angus_item in ANGUS_ITEMS:
    print(f"{'='*70}")
    print(f"TRACING: {angus_item['name']}")
    print(f"{'='*70}")

    # Search raw collection
    raw_matches = search_items(raw, angus_item["search"], angus_item.get("url_fragment"))
    if raw_matches:
        print(f"  IN RAW COLLECTION: YES ({len(raw_matches)} matches)")
        for m in raw_matches[:3]:
            print(f"    source: {m.get('source_type', '?')} / {m.get('source_name', '?')}")
            print(f"    title: {m.get('title', '')[:80]}")
            print(f"    score: {m.get('relevance_score', 'not scored yet')}")
            print(f"    url: {m.get('url', '')[:80]}")
            print(f"    content length: {len(m.get('content', ''))}")
            print()
    else:
        print(f"  IN RAW COLLECTION: NO — never collected")
        print(f"    Searched for: {angus_item['search']}")
        print()
        continue

    # Search scored 150
    scored_matches = search_items(scored, angus_item["search"], angus_item.get("url_fragment"))
    if scored_matches:
        print(f"  IN SCORED 150: YES ({len(scored_matches)} matches)")
        for m in scored_matches[:2]:
            print(f"    score: {m.get('relevance_score', '?')}")
            print(f"    title: {m.get('title', '')[:80]}")
    else:
        print(f"  IN SCORED 150: NO — collected but filtered out")
        # Show why
        if raw_matches:
            raw_scores = [m.get("relevance_score", 0) for m in raw_matches if m.get("relevance_score")]
            if raw_scores:
                print(f"    Raw scores: {raw_scores}")
                print(f"    150th item score threshold: check items_2026-03-23.json")
            else:
                print(f"    Items not scored — may have been dropped by date/geo filter")
    print()

print("="*70)
print("SUMMARY")
print("="*70)
collected = sum(1 for a in ANGUS_ITEMS
    if search_items(raw, a["search"], a.get("url_fragment")))
survived = sum(1 for a in ANGUS_ITEMS
    if search_items(scored, a["search"], a.get("url_fragment")))
print(f"In raw collection: {collected}/13")
print(f"In scored 150: {survived}/13")
print(f"Lost in scoring: {collected - survived}/13")
print(f"Never collected: {13 - collected}/13")
