"""RSS feed collector for trade press and industry sources."""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

log = logging.getLogger(__name__)

# Trade press and industry RSS feeds
RSS_FEEDS = [
    {"name": "Recharge News", "url": "https://www.rechargenews.com/rss"},
    {"name": "Windpower Monthly", "url": "https://www.windpowermonthly.com/rss"},
    {"name": "Current±", "url": "https://www.current-news.co.uk/feed/"},
    {"name": "Utility Week", "url": "https://utilityweek.co.uk/feed/"},
    {"name": "New Power", "url": "https://www.newpower.info/feed/"},
    {"name": "RenewableUK", "url": "https://www.renewableuk.com/news/rss.aspx"},
    {"name": "Energy UK", "url": "https://www.energy-uk.org.uk/feed/"},
    {"name": "Ofgem", "url": "https://www.ofgem.gov.uk/rss"},
    {"name": "CCC", "url": "https://www.theccc.org.uk/feed/"},
]


def _fingerprint(url: str, title: str) -> str:
    raw = f"{url}:{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def _parse_date(date_str: str) -> str | None:
    """Parse RSS date formats to YYYY-MM-DD."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    # Try ISO format
    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
        try:
            dt = datetime.strptime(date_str[:19], fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()


def _parse_rss_xml(xml_text: str, feed_name: str) -> list[dict]:
    """Parse RSS XML manually (avoid lxml dependency)."""
    items = []

    # Extract <item> blocks
    item_blocks = re.findall(r'<item>(.*?)</item>', xml_text, re.DOTALL)
    if not item_blocks:
        # Try Atom format: <entry>
        item_blocks = re.findall(r'<entry>(.*?)</entry>', xml_text, re.DOTALL)

    for block in item_blocks:
        # Extract fields
        title_match = re.search(r'<title[^>]*>(.*?)</title>', block, re.DOTALL)
        link_match = re.search(r'<link[^>]*>(.*?)</link>', block, re.DOTALL)
        if not link_match:
            link_match = re.search(r'<link[^>]*href=["\']([^"\']+)', block)
        desc_match = re.search(r'<description[^>]*>(.*?)</description>', block, re.DOTALL)
        if not desc_match:
            desc_match = re.search(r'<summary[^>]*>(.*?)</summary>', block, re.DOTALL)
        if not desc_match:
            desc_match = re.search(r'<content[^>]*>(.*?)</content>', block, re.DOTALL)
        date_match = re.search(r'<pubDate[^>]*>(.*?)</pubDate>', block, re.DOTALL)
        if not date_match:
            date_match = re.search(r'<published[^>]*>(.*?)</published>', block, re.DOTALL)
        if not date_match:
            date_match = re.search(r'<updated[^>]*>(.*?)</updated>', block, re.DOTALL)

        title = _strip_html(title_match.group(1)) if title_match else ""
        url = link_match.group(1).strip() if link_match else ""
        # Handle CDATA
        title = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', title)
        url = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', url)

        description = ""
        if desc_match:
            description = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', desc_match.group(1), flags=re.DOTALL)
            description = _strip_html(description)[:1000]

        date_str = date_match.group(1).strip() if date_match else ""
        parsed_date = _parse_date(date_str)

        if not title or not url:
            continue

        items.append({
            "title": title,
            "url": url,
            "content": description,
            "date": parsed_date or "",
            "source_name": feed_name,
        })

    return items


async def collect(
    client: httpx.AsyncClient,
    config: dict,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Collect items from RSS feeds, filtered to reporting window."""
    items = []
    cutoff = start - timedelta(days=3)  # Include items from a few days before reporting week

    for feed in RSS_FEEDS:
        try:
            resp = await client.get(feed["url"], follow_redirects=True, timeout=10)
            if resp.status_code != 200:
                log.warning(f"RSS {resp.status_code} for {feed['name']}")
                continue

            parsed = _parse_rss_xml(resp.text, feed["name"])

            for entry in parsed:
                # Date filter
                if entry["date"]:
                    try:
                        item_date = datetime.strptime(entry["date"], "%Y-%m-%d")
                        if item_date < cutoff:
                            continue
                    except ValueError:
                        pass

                items.append({
                    "source_type": "web",
                    "title": entry["title"],
                    "date": entry["date"],
                    "url": entry["url"],
                    "content": entry["content"],
                    "source_name": feed["name"],
                    "keywords_matched": [],  # Scored by keyword_scorer
                    "relevance_score": 0.0,
                    "verified": True,  # RSS = real published articles
                    "fingerprint": _fingerprint(entry["url"], entry["title"]),
                })

            log.debug(f"RSS '{feed['name']}': {len(parsed)} entries, {len([i for i in items if i['source_name'] == feed['name']])} in window")

        except httpx.TimeoutException:
            log.warning(f"RSS timeout for {feed['name']}")
        except Exception as e:
            log.warning(f"RSS error for {feed['name']}: {e}")

        await asyncio.sleep(0.2)

    log.info(f"RSS: collected {len(items)} items across {len(RSS_FEEDS)} feeds")
    return items
