#!/usr/bin/env python3
"""
Test all GOV.UK RSS/Atom feeds. For each feed:
- Fetch it
- Count total entries
- Show entries from w/c 23 March 2026 (23-28 March)
- Search for the 6 specific items Angus flagged
"""
import httpx
import feedparser
import asyncio
from datetime import datetime

FEEDS = [
    "https://www.gov.uk/government/organisations/department-for-energy-security-and-net-zero.atom",
    "https://www.gov.uk/government/organisations/ofgem.atom",
    "https://www.gov.uk/government/organisations/planning-inspectorate.atom",
    "https://www.gov.uk/government/organisations/competition-and-markets-authority.atom",
    "https://www.gov.uk/search/policy-papers-and-consultations.atom?organisations%5B%5D=department-for-energy-security-and-net-zero",
    "https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=department-for-energy-security-and-net-zero",
    "https://www.gov.uk/search/policy-papers-and-consultations.atom?topics%5B%5D=energy",
    "https://www.gov.uk/search/news-and-communications.atom?topics%5B%5D=energy",
    "https://www.gov.uk/search/policy-papers-and-consultations.atom?organisations%5B%5D=department-for-levelling-up-housing-and-communities&topics%5B%5D=planning-and-building",
    "https://www.gov.uk/search/news-and-communications.atom?organisations%5B%5D=hm-treasury&topics%5B%5D=energy",
]

# The 6 GOV.UK items Angus flagged as missing
ANGUS_ITEMS = [
    "energy digitalisation framework",
    "planning reform",
    "planning application fees",
    "cyber resilience",
    "energy code reform",
    "code manager licence",
    "carbon storage",
    "bill discount",
    "transmission network infrastructure",
]

async def main():
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for feed_url in FEEDS:
            print(f"\n{'='*80}")
            print(f"FEED: {feed_url[:80]}")
            print(f"{'='*80}")

            try:
                resp = await client.get(feed_url)
                print(f"HTTP {resp.status_code} | Content-Type: {resp.headers.get('content-type', '?')[:50]}")

                if resp.status_code != 200:
                    print(f"FAILED: {resp.text[:200]}")
                    continue

                feed = feedparser.parse(resp.text)
                print(f"Total entries: {len(feed.entries)}")

                if len(feed.entries) == 0:
                    print("NO ENTRIES — feed may be empty or URL may be wrong")
                    continue

                # Show date range
                dates = []
                for entry in feed.entries:
                    pub = entry.get("published", entry.get("updated", ""))
                    if pub:
                        dates.append(pub[:10])
                if dates:
                    print(f"Date range: {min(dates)} to {max(dates)}")

                # Filter to w/c 23 March
                week_entries = []
                for entry in feed.entries:
                    pub = entry.get("published", entry.get("updated", ""))
                    if pub and "2026-03-2" in pub[:10]:  # rough match for 20-29 March
                        week_entries.append(entry)

                print(f"Entries from w/c 23 March: {len(week_entries)}")
                for entry in week_entries[:10]:
                    title = entry.get("title", "no title")
                    pub = entry.get("published", entry.get("updated", ""))[:10]
                    print(f"  {pub} | {title[:80]}")

                # Search for Angus's items
                print(f"\nSearching for Angus's missing items:")
                all_text = " ".join(
                    f"{e.get('title', '')} {e.get('summary', '')}"
                    for e in feed.entries
                ).lower()

                for search_term in ANGUS_ITEMS:
                    if search_term in all_text:
                        # Find which entry
                        for e in feed.entries:
                            entry_text = f"{e.get('title', '')} {e.get('summary', '')}".lower()
                            if search_term in entry_text:
                                print(f"  FOUND '{search_term}': {e.get('title', '')[:70]} ({e.get('published', '')[:10]})")
                                break
                    else:
                        print(f"  MISSING '{search_term}'")

            except Exception as e:
                print(f"ERROR: {e}")

            await asyncio.sleep(0.5)

asyncio.run(main())
