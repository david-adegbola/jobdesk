"""Finnish forestry and forest-bioeconomy news feeds for the News page."""

import html
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import db
import scraper

USER_AGENT = "Mozilla/5.0 (personal forestry news reader; low volume)"

SOURCES = [
    {
        "id": "luke",
        "name": "Luke",
        "url": "https://www.luke.fi/fi/feed",
        "category": "Tutkimus ja innovaatiot",
        "region": "Suomi",
        "interval_minutes": 60,
    },
    {
        "id": "metsateollisuus",
        "name": "Metsäteollisuus ry",
        "url": "https://metsateollisuus.fi/feed/",
        "category": "Metsätalous",
        "region": "Suomi",
        "interval_minutes": 60,
    },
    {
        "id": "tornator",
        "name": "Tornator",
        "url": "https://www.tornator.fi/feed/",
        "category": "Metsätalous",
        "region": "Suomi",
        "interval_minutes": 60,
    },
    {
        "id": "finland-forest",
        "name": "Suomen metsäala · uutishaku",
        "url": (
            "https://news.google.com/rss/search?q=mets%C3%A4biotalous+OR+mets%C3%A4talous"
            "+OR+mets%C3%A4teollisuus+OR+mets%C3%A4nhoito&hl=fi-FI&gl=FI&ceid=FI:fi"
        ),
        "category": "Metsätalous",
        "region": "Suomi",
        "interval_minutes": 30,
    },
    {
        "id": "north-karelia",
        "name": "Joensuu & Pohjois-Karjala · uutishaku",
        "url": (
            "https://news.google.com/rss/search?q=Joensuu+OR+%22Pohjois-Karjala%22"
            "+%28mets%C3%A4ala+OR+biotalous+OR+forest%29&hl=fi-FI&gl=FI&ceid=FI:fi"
        ),
        "category": "Metsätalous",
        "region": "Pohjois-Karjala",
        "interval_minutes": 30,
    },
    {
        "id": "eu-forest-policy",
        "name": "EU:n metsäpolitiikka · uutishaku",
        "url": (
            "https://news.google.com/rss/search?q=EUDR+OR+LULUCF+OR+%22EU+forest+strategy%22"
            "&hl=en-GB&gl=GB&ceid=GB:en"
        ),
        "category": "Politiikka ja markkinat",
        "region": "Eurooppa",
        "interval_minutes": 60,
    },
    {
        "id": "forest-tech",
        "name": "Metsäteknologia · uutishaku",
        "url": (
            "https://news.google.com/rss/search?q=%22forest+tech%22+OR+%22forestry+startup%22"
            "+funding&hl=en-US&gl=US&ceid=US:en"
        ),
        "category": "Data ja teknologia",
        "region": "Kansainvälinen",
        "interval_minutes": 60,
    },
    {
        "id": "forest-research",
        "name": "European Forest Institute · uutishaku",
        "url": (
            "https://news.google.com/rss/search?q=%22European+Forest+Institute%22"
            "&hl=en-GB&gl=GB&ceid=GB:en"
        ),
        "category": "Tutkimus ja innovaatiot",
        "region": "Eurooppa",
        "interval_minutes": 60,
    },
]

TOPICS = {
    "Biotalous ja materiaalit": (
        "biotalous", "bioeconomy", "biomaterial", "biomateriaali", "puupohj",
        "wood-based", "renewable material", "sellu", "sahatavara",
    ),
    "Tutkimus ja innovaatiot": (
        "research", "tutkimus", "science", "study", "innovation", "innovaatio",
        "yliopisto", "university", "european forest institute",
    ),
    "Luonto ja ilmasto": (
        "biodiversiteet", "monimuotoisuus", "luontokato", "ennallist", "restoration",
        "climate", "ilmasto", "hiilinielu", "carbon sink", "nature",
    ),
    "Data ja teknologia": (
        "paikkatieto", "kaukokartoit", "geospatial", "remote sensing", "forest tech",
        "digital", "data", "startup", "teknologia",
    ),
    "Politiikka ja markkinat": (
        "eudr", "lulucf", "policy", "politiikka", "regulation", "sääntely",
        "market", "markkina", "hinta", "funding", "investointi",
    ),
    "Metsätalous": ("metsä", "forest", "forestry", "timber", "puunkorju", "metsänhoito"),
}

FOREST_ANCHORS = (
    "metsä", "forest", "forestry", "timber", "wood", "puu", "paper", "pulp",
    "bioeconomy", "biotalous", "eudr", "lulucf",
)

WHY_IT_MATTERS = {
    "Metsätalous": "Forest management and wood supply shape day-to-day work across the sector.",
    "Biotalous ja materiaalit": "New materials and investment can change which skills Finnish employers need.",
    "Tutkimus ja innovaatiot": "Research can point to emerging methods, projects and specialist skills in the forest sector.",
    "Luonto ja ilmasto": "Nature and climate policy increasingly affect sustainable forest management.",
    "Data ja teknologia": "Digital forestry creates opportunities in GIS, remote sensing and forest data.",
    "Politiikka ja markkinat": "Policy and market shifts can affect projects, employers and hiring plans.",
}

CAREER_ANGLES = {
    "Metsätalous": "Watch for forest planning, silviculture, fieldwork and forest-inventory roles.",
    "Biotalous ja materiaalit": "Note employers investing in new materials and the process skills they need.",
    "Tutkimus ja innovaatiot": "Look for projects and roles involving research, GIS, remote sensing or forest data.",
    "Luonto ja ilmasto": "Track restoration, biodiversity and climate-data work across public and private employers.",
    "Data ja teknologia": "Watch for GIS, remote-sensing, automation and forest-data positions.",
    "Politiikka ja markkinat": "Notice changing standards, employer investment and skills that may surface in job ads.",
}


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def clean_text(value):
    parser = PlainText()
    parser.feed(html.unescape(value or ""))
    return " ".join(" ".join(parser.parts).split())


def canonical_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    tracking = {"fbclid", "gclid", "mc_cid", "mc_eid"}
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in tracking]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, urlencode(query), ""))


def parse_date(value):
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).astimezone().isoformat(timespec="minutes")
    except (TypeError, ValueError, OverflowError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().isoformat(timespec="minutes")
        except (TypeError, ValueError, OverflowError):
            return ""


def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def entry_fields(entry):
    fields = {}
    links = []
    for child in entry:
        name = local_name(child.tag)
        if name == "link":
            href = child.attrib.get("href") or "".join(child.itertext()).strip()
            if href:
                links.append((child.attrib.get("rel", "alternate"), href))
        elif name in {"title", "summary", "description", "content", "encoded", "pubdate",
                      "published", "updated", "date"}:
            value = "".join(child.itertext()).strip()
            if value and (name not in fields or name in {"summary", "description", "content", "encoded"}):
                fields[name] = value
    fields["link"] = next((url for rel, url in links if rel == "alternate"), links[0][1] if links else "")
    return fields


def classify(text, fallback, region):
    lowered = text.lower()
    matched = [topic for topic, terms in TOPICS.items()
               if any(term in lowered for term in terms)]
    if not matched:
        return fallback, [], 15 if region == "Pohjois-Karjala" else 0
    score = min(100, 20 + len(matched) * 15 + (15 if region == "Pohjois-Karjala" else 0))
    return matched[0], matched, score


def parse_feed(body, source):
    root = ElementTree.fromstring(body)
    items = []
    for entry in root.iter():
        if local_name(entry.tag) not in {"item", "entry"}:
            continue
        fields = entry_fields(entry)
        title = clean_text(fields.get("title", ""))
        url = canonical_url(fields.get("link", ""))
        if not title or not url:
            continue
        summary = clean_text(next(
            (fields[key] for key in ("encoded", "content", "description", "summary") if fields.get(key)),
            "",
        ))[:1200]
        text = f"{title} {summary}"
        if not any(term in text.lower() for term in FOREST_ANCHORS):
            continue
        category, topics, relevance = classify(text, source["category"], source["region"])
        items.append({
            "source_id": source["id"],
            "source": source["name"],
            "external_id": url,
            "url": url,
            "title": title,
            "summary": summary,
            "published_at": parse_date(next(
                (fields[key] for key in ("pubdate", "published", "updated", "date") if fields.get(key)),
                "",
            )),
            "category": category,
            "region": source["region"],
            "relevance": relevance,
            "matched_topics": ", ".join(topics),
        })
    return items


def fetch_source(source):
    request = urllib.request.Request(
        source["url"],
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20, context=scraper.SSL_CONTEXT) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        reason = getattr(error, "reason", error)
        return [], f"{getattr(error, 'code', 'network error')}: {reason}"
    try:
        return parse_feed(body, source), ""
    except ElementTree.ParseError as error:
        return [], f"Invalid RSS/Atom response: {error}"


def refresh(user_id=1, force=False):
    """Fetch due feeds, retaining source-level errors and reader state."""
    found = new = 0
    errors = []
    states = {state["source_id"]: state for state in db.list_news_source_state(user_id)}
    now = datetime.now().astimezone()
    due = []
    skipped = 0
    for source in SOURCES:
        state = states.get(source["id"])
        if not force and state:
            try:
                checked_at = datetime.fromisoformat(state["checked_at"]).astimezone()
                interval = min(source["interval_minutes"], 5) if state["error"] else source["interval_minutes"]
                if now - checked_at < timedelta(minutes=interval):
                    skipped += 1
                    continue
            except ValueError:
                pass
        due.append(source)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(fetch_source, due))
    for source, (items, error) in zip(due, results):
        source_new = 0
        if not error:
            for item in items:
                is_new = db.upsert_news_item(item, user_id)
                found += 1
                source_new += int(is_new)
                new += int(is_new)
        db.record_news_source_check(source["id"], source["name"], len(items), source_new, error, user_id)
        if error:
            errors.append(f"{source['name']}: {error}")
    return {"found": found, "new": new, "errors": errors, "checked": len(due), "skipped": skipped}


def story_context(category):
    return WHY_IT_MATTERS.get(category, "This story may affect employers, skills or opportunities in the forest sector.")


def career_context(category):
    return CAREER_ANGLES.get(category, "Look for employers and skills mentioned in the story that connect to forest-sector work.")
