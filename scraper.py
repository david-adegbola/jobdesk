"""Jobly scraper (from the old job_check.py). Reads Jobly's public, Finland-wide category pages,
waits 10 s between requests as Jobly's robots.txt asks, and stores jobs in SQLite via db.py.
A job is NEW when the latest check is the first one that saw it.
"""

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import db

# Each job type -> Jobly category pages, https://www.jobly.fi/tyopaikat/<slug>
JOB_TYPES = {
    "Industrial": ["asentaja", "kokoonpanija", "tuotantotyontekija"],
    "Construction": ["rakennustyontekija", "rakennusmies"],
    "Warehouse": ["varastotyontekija", "logistiikkatyontekija"],
    "IT-Data centre": ["it"],
}
# Default CV for each job type (the Match column may suggest a better one)
CV_FOR_TYPE = {
    "Industrial": "industrial-master",
    "Construction": "construction-master",
    "Warehouse": "warehouse-master",
    "IT-Data centre": "it-field-technician",
}
# Broad categories: keep only titles containing one of these words (lower-case)
TITLE_MUST_MATCH = {
    "it": ["tuki", "support", "asentaja", "kenttä", "field", "lähituki", "helpdesk", "service desk",
           "teknikko", "technician", "datakeskus", "data center", "data centre", "laite"],
}
DATA_CENTRE_WORDS = ["datakeskus", "data center", "data centre"]

MAX_PAGES = 3          # about 20 jobs per page
DELAY_SECONDS = 10     # Jobly robots.txt asks for 10 s between requests
BASE = "https://www.jobly.fi"
USER_AGENT = "Mozilla/5.0 (personal job check; low volume)"
OLD_SEEN_FILE = Path(__file__).resolve().parent.parent / "jobs_seen.json"   # from the old job_check.py

JOB_PATH = re.compile(r"/(?:en/job|tyopaikka)/([a-z0-9-]+-(\d+))/?$")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
             "track", "wbr"}
FIELD_CLASSES = {
    "node__title": "title",
    "date": "date",
    "recruiter-company-profile-job-organization": "company",
    "location": "location",
}


def ssl_context():
    """Verified HTTPS. python.org Python on macOS has no CA certificates until its
    'Install Certificates' step runs, so fall back to macOS's own store."""
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs() and os.path.exists("/etc/ssl/cert.pem"):
        ctx.load_verify_locations("/etc/ssl/cert.pem")
    return ctx


SSL_CONTEXT = ssl_context()


class JoblyParser(HTMLParser):
    """Reads Jobly job cards: <article about="/tyopaikka/<slug>"> with the title (h2.node__title),
    date (span.date), company (span.recruiter-company-profile-job-organization), location (div.location)."""

    def __init__(self):
        super().__init__()
        self.jobs = []
        self._job = None
        self._depth = 0
        self._field = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "article":
            m = JOB_PATH.search(a.get("about") or "")
            if m:
                self._job = {"id": m.group(2), "url": f"{BASE}/tyopaikka/{m.group(1)}",
                             "title": [], "date": [], "company": [], "location": []}
                self._depth, self._field = 0, None
                return
        if not self._job or tag in VOID_TAGS:
            return
        self._depth += 1
        if self._field is None:
            classes = (a.get("class") or "").split()
            for cls, field in FIELD_CLASSES.items():
                if cls in classes:
                    self._field = (field, self._depth)
                    break

    def handle_endtag(self, tag):
        if not self._job:
            return
        if tag == "article":
            self._finish()
            return
        if tag in VOID_TAGS:
            return
        if self._field and self._depth <= self._field[1]:
            self._field = None
        self._depth -= 1

    def handle_data(self, data):
        if self._job and self._field:
            text = " ".join(data.split()).strip(" ,")
            if text:
                self._job[self._field[0]].append(text)

    def _finish(self):
        j, self._job = self._job, None
        title = " ".join(j["title"])
        if title:
            self.jobs.append({"id": j["id"], "title": title, "url": j["url"],
                              "company": " ".join(j["company"]),
                              "location": ", ".join(dict.fromkeys(j["location"])),
                              "posted": to_iso(" ".join(j["date"]))})


class TextExtractor(HTMLParser):
    """Visible text of one ad page (for Match and Blockers), without scripts, styles and menus."""
    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "svg", "form"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            t = " ".join(data.split())
            if t:
                self.parts.append(t)


def to_iso(text):
    """'30.10.2026' -> '2026-10-30'; anything else -> ''."""
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text or "")
    if not m:
        return ""
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date().isoformat()
    except ValueError:
        return ""


def jobly_id(url):
    m = JOB_PATH.search((url or "").split("?")[0].replace("https://www.jobly.fi", ""))
    return m.group(2) if m else None


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "fi,en"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        print(f"  ! {url} -> {getattr(e, 'code', '')} {getattr(e, 'reason', e)}")
        return None


def fetch_ad_text(url):
    """Text of a single ad page, or '' if it can't be read."""
    body = fetch(url)
    if not body:
        return ""
    p = TextExtractor()
    p.feed(body)
    return "\n".join(p.parts)[:20000]


def _old_seen_ids():
    try:
        return set(json.loads(OLD_SEEN_FILE.read_text()))
    except (OSError, json.JSONDecodeError):
        return set()


def run(progress=None, user_id=1):
    """One full check. progress(message, done, total) is called as pages are read."""
    pages = [(cat, slug) for cat, slugs in JOB_TYPES.items() for slug in slugs]
    check_id = db.start_check(user_id)
    old_seen = _old_seen_ids()
    found = new = 0
    seen_now = set()
    error = None
    try:
        first = True
        for n, (category, slug) in enumerate(pages):
            for page in range(MAX_PAGES):
                if not first:
                    time.sleep(DELAY_SECONDS)
                first = False
                url = f"{BASE}/tyopaikat/{slug}" + (f"?page={page}" if page else "")
                if progress:
                    progress(f"Reading {slug} page {page + 1}", n, len(pages))
                body = fetch(url)
                if not body:
                    break
                parser = JoblyParser()
                parser.feed(body)
                fresh = [j for j in parser.jobs if j["id"] not in seen_now]
                if not fresh:
                    break
                for j in fresh:
                    seen_now.add(j["id"])
                    words = TITLE_MUST_MATCH.get(slug)
                    if words and not any(w in j["title"].lower() for w in words):
                        continue
                    cat = "IT-Data centre" if any(w in j["title"].lower() for w in DATA_CENTRE_WORDS) else category
                    is_new = db.upsert_scraped(
                        {"source": "Jobly", "external_id": j["id"], "url": j["url"], "title": j["title"],
                         "company": j["company"], "location": j["location"], "posted": j["posted"],
                         "category": cat},
                        check_id, already_seen=j["id"] in old_seen, user_id=user_id)
                    found += 1
                    new += is_new
    except Exception as e:      # keep what was saved; report the error in the dashboard
        error = f"{type(e).__name__}: {e}"
    db.finish_check(check_id, found, new, error, user_id=user_id)
    if progress:
        progress(f"Done: {found} jobs, {new} new" + (f" (error: {error})" if error else ""),
                 len(pages), len(pages))
    return {"found": found, "new": new, "error": error}
