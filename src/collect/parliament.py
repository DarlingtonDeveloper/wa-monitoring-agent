"""UK Parliament structured APIs — Written Questions, EDMs, Bills, Committee evidence."""

import asyncio
import hashlib
import logging
from datetime import datetime

import httpx

log = logging.getLogger(__name__)

WQ_URL = "https://questions-statements-api.parliament.uk/api/writtenquestions/questions"
EDM_URL = "https://oralquestionsandmotions-api.parliament.uk/EarlyDayMotions/list"
BILLS_URL = "https://bills-api.parliament.uk/api/v1/Bills"
COMMITTEES_URL = "https://committees-api.parliament.uk/api/Events"

# Energy-related committee IDs
ENERGY_COMMITTEE_ID = 664  # Energy Security and Net Zero Committee

SEARCH_TERMS = [
    "offshore wind", "RWE", "energy security", "CfD",
    "clean power", "wind farm", "renewable energy", "CCUS",
    "net zero", "grid connection",
]


def _fingerprint(url: str, title: str) -> str:
    raw = f"{url}:{title}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


async def _collect_written_questions(
    client: httpx.AsyncClient, start: datetime, end: datetime
) -> list[dict]:
    """Collect written parliamentary questions."""
    items = []

    for term in SEARCH_TERMS:
        try:
            params = {
                "searchTerm": term,
                "tabledWhenFrom": start.strftime("%Y-%m-%d"),
                "tabledWhenTo": end.strftime("%Y-%m-%d"),
                "expandMember": "true",
                "take": 20,
            }
            resp = await client.get(WQ_URL, params=params)
            if resp.status_code != 200:
                continue

            data = resp.json()
            results = data.get("results", [])

            for r in results:
                val = r.get("value", {})
                question_text = val.get("questionText", "")
                answer_text = val.get("answerText", "")
                heading = val.get("heading", "")
                uin = val.get("uin", "")
                member = val.get("askingMember", {})
                member_name = member.get("name", "") if isinstance(member, dict) else ""
                answering_body = val.get("answeringBodyName", "")

                date_str = val.get("dateTabled", "")
                if date_str and "T" in date_str:
                    date_str = date_str.split("T")[0]

                title = f"Written Question: {heading}" if heading else f"Written Question {uin}"
                content = question_text[:500]
                if answer_text:
                    content += f"\n\nAnswer: {answer_text[:450]}"

                url = f"https://questions-statements.parliament.uk/written-questions/detail/{date_str}/{uin}" if uin else ""

                items.append({
                    "source_type": "hansard",
                    "title": title,
                    "date": date_str,
                    "url": url,
                    "content": content[:1000],
                    "source_name": f"Parliament, Written Question to {answering_body}",
                    "keywords_matched": [term],
                    "relevance_score": 0.0,
                    "verified": True,
                    "fingerprint": _fingerprint(url or uin, title),
                })

            await asyncio.sleep(0.3)

        except Exception as e:
            log.warning(f"Written questions error for '{term}': {e}")

    log.info(f"Written questions: {len(items)} items")
    return items


async def _collect_edms(
    client: httpx.AsyncClient, start: datetime, end: datetime
) -> list[dict]:
    """Collect Early Day Motions."""
    items = []

    for term in SEARCH_TERMS[:5]:  # Fewer terms for EDMs — they're less frequent
        try:
            params = {
                "searchTerm": term,
                "parameters.tabledStartDate": start.strftime("%Y-%m-%d"),
                "parameters.tabledEndDate": end.strftime("%Y-%m-%d"),
                "take": 10,
            }
            resp = await client.get(EDM_URL, params=params)
            if resp.status_code != 200:
                continue

            data = resp.json()
            results = data.get("Response", [])

            for r in results:
                title = r.get("Title", "")
                uin = r.get("UIN", "")
                motion_text = r.get("MotionText", "")
                sponsor = r.get("PrimarySponsor", {})
                sponsor_name = sponsor.get("Name", "") if isinstance(sponsor, dict) else ""
                sponsors_count = r.get("SponsorsCount", 0)

                date_str = r.get("DateTabled", "")
                if date_str and "T" in date_str:
                    date_str = date_str.split("T")[0]

                url = f"https://edm.parliament.uk/early-day-motion/{r.get('Id', '')}" if r.get("Id") else ""

                content = f"EDM {uin}: {motion_text[:800]}"
                if sponsor_name:
                    content += f"\n\nPrimary sponsor: {sponsor_name}. {sponsors_count} total sponsors."

                items.append({
                    "source_type": "hansard",
                    "title": f"EDM {uin}: {title}",
                    "date": date_str,
                    "url": url,
                    "content": content[:1000],
                    "source_name": "Parliament, Early Day Motion",
                    "keywords_matched": [term],
                    "relevance_score": 0.0,
                    "verified": True,
                    "fingerprint": _fingerprint(url or str(uin), title),
                })

            await asyncio.sleep(0.3)

        except Exception as e:
            log.warning(f"EDM error for '{term}': {e}")

    log.info(f"EDMs: {len(items)} items")
    return items


async def _collect_committee_events(
    client: httpx.AsyncClient, start: datetime, end: datetime
) -> list[dict]:
    """Collect upcoming committee evidence sessions."""
    items = []

    try:
        params = {
            "CommitteeId": ENERGY_COMMITTEE_ID,
            "startDateFrom": start.strftime("%Y-%m-%d"),
            "startDateTo": (end + __import__("datetime").timedelta(days=28)).strftime("%Y-%m-%d"),
            "take": 20,
        }
        resp = await client.get(COMMITTEES_URL, params=params)
        if resp.status_code != 200:
            return items

        data = resp.json()
        results = data.get("items", [])

        for r in results:
            title = ""
            businesses = r.get("committeeBusinesses", [])
            if businesses:
                title = businesses[0].get("title", "") if isinstance(businesses[0], dict) else ""

            event_type = r.get("eventType", "")
            committees = r.get("committees", [])
            committee_name = committees[0].get("name", "") if committees and isinstance(committees[0], dict) else ""

            date_str = r.get("startDate", "")
            if date_str and "T" in date_str:
                date_str = date_str.split("T")[0]

            location = r.get("location", "")
            content = f"Committee: {committee_name}. Event: {event_type}."
            if title:
                content += f" Inquiry: {title}."
            if location:
                content += f" Location: {location}."

            items.append({
                "source_type": "hansard",
                "title": f"Committee: {title or event_type}",
                "date": date_str,
                "url": f"https://committees.parliament.uk/event/{r.get('id', '')}/" if r.get("id") else "",
                "content": content[:1000],
                "source_name": f"Parliament, {committee_name or 'Select Committee'}",
                "keywords_matched": ["committee", "energy"],
                "relevance_score": 0.0,
                "verified": True,
                "fingerprint": _fingerprint(str(r.get("id", "")), title or event_type),
            })

    except Exception as e:
        log.warning(f"Committee events error: {e}")

    log.info(f"Committee events: {len(items)} items")
    return items


async def collect(
    client: httpx.AsyncClient,
    config: dict,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Collect from all Parliament structured APIs."""
    wq, edms, committees = await asyncio.gather(
        _collect_written_questions(client, start, end),
        _collect_edms(client, start, end),
        _collect_committee_events(client, start, end),
        return_exceptions=True,
    )

    items = []
    for result in [wq, edms, committees]:
        if isinstance(result, Exception):
            log.error(f"Parliament collector failed: {result}")
        elif isinstance(result, list):
            items.extend(result)

    log.info(f"Parliament APIs: {len(items)} total items")
    return items
