"""Forestry job scraper. Reads Jobly's public, Finland-wide category pages (10 s apart, as Jobly's
robots.txt asks), the state and municipal job portals, forestry-sector boards and employer career
sites, and stores jobs in SQLite via db.py. A job is NEW when the latest check is the first one
that saw it.

Sources follow the 2025 forestry internship overview (Metsälehti, Valtiolle, Kuntarekry, Duunitori,
TE/Työmarkkinatori, Luke, Metsähallitus, Metsäkeskus, MHYs, Metsä Group, UPM, Stora Enso ...).

LANGUAGE CHECK - every source has Finnish and English variants, and they are not always the same:
  * URL slugs differ (valtiolle.fi/fi/tyopaikat/ vs /en/jobs/, uef.varbi.com/fi/ vs /en/,
    Workday fi-FI vs en-US). English-only postings (e.g. research assistant and summer-trainee ads)
    can be missing from the Finnish listing, so read both and deduplicate by the posting's number.
  * Search keywords and category/tag slugs must be given in both languages (metsä + forest,
    harjoittelija + intern/trainee, kesätyö + summer job). Swedish (skog) catches bilingual ads.
  * Jobly has no English category slugs: unknown slugs such as /en/jobs/forestry silently fall back
    to the generic all-jobs list, so check that a new slug returns its own jobs before adding it.
  * When adding a source, check robots.txt and the site's terms. Duunitori disallows generic
    crawlers, so its search pages are read only when JOBDESK_ENABLE_DUUNITORI=1 (default off), and
    even then only if robots.txt allows it. Työmarkkinatori disallows /api/, so it is not read.

ROBOTS.TXT - every automatic request (listing pages, feeds, the Workday API, single ad pages) is
checked first with core.robots.RobotsCache. Disallowed URLs are skipped and logged, never fetched.
"""

import html
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit
from xml.etree import ElementTree

import config
import db
from core import fetch as core_fetch
from core import fields as core_fields
from core.fetch import PublicRedirectHandler, TextExtractor, is_public_http_url  # noqa: F401 (re-exported)
from core.robots import RobotsCache

# Field profiles (fields/*.json) and job sources (sources.json) are configuration, not code.
PROFILES = core_fields.load_profiles(config.FIELDS_DIR)
FORESTRY = PROFILES["forestry"]
with open(config.SOURCES_FILE, encoding="utf-8") as _file:
    SOURCE_CONFIG = json.load(_file)
SOURCES = {source["id"]: source for source in SOURCE_CONFIG["sources"]}
SOURCE_BY_NAME = {source["name"]: source for source in SOURCES.values()}

# The administrator's own Jobly searches from before JobDesk covered several fields. These categories
# are scraped only for the administrator, stored under their account and never shown to members.
PERSONAL_JOB_TYPES = {
    "Industrial": ["asentaja", "kokoonpanija", "tuotantotyontekija"],
    "Construction": ["rakennustyontekija", "rakennusmies"],
    "Warehouse": ["varastotyontekija", "logistiikkatyontekija"],
    "IT-Data centre": ["it"],
}
PERSONAL_CATEGORIES = list(PERSONAL_JOB_TYPES)
# Each job type -> Jobly category pages, https://www.jobly.fi/tyopaikat/<slug>. Finnish slugs only:
# Jobly has no English category slugs (see the module docstring).
JOB_TYPES = {"Forestry": FORESTRY["jobly"]["slugs"], **PERSONAL_JOB_TYPES}
# Default CV for each job type (the Match column may suggest a better one)
CV_FOR_TYPE = {
    "Industrial": "industrial-master",
    "Construction": "industrial-master",     # construction-master was merged into it (cv repo, 2026-10-31)
    "Warehouse": "warehouse-master",
    "Forestry": "forestry-master",
    "IT-Data centre": "it-field-technician",
}
# The forestry word lists now live in fields/forestry.json; these names stay for older code
FORESTRY_WORDS = FORESTRY["jobly"]["title_words"]
FORESTRY_RELEVANCE_WORDS = FORESTRY["relevance"]["words"]
FORESTRY_CORE_WORDS = FORESTRY["relevance"]["core_words"]
WHOLE_WORDS = set(FORESTRY["relevance"]["whole_words"])
# Sources by kind (sources.json): field boards list only their fields' jobs; broad portals list
# every public-sector job, so they get the stricter core-word rule (core/fields.py).
FORESTRY_ONLY_SOURCES = {s["name"] for s in SOURCES.values() if s["kind"] == "field_board"}
BROAD_AD_SOURCES = {s["name"] for s in SOURCES.values() if s["kind"] == "broad_portal"}
# Personal Jobly categories: a title must contain one of these words
TITLE_MUST_MATCH = {
    "it": ["tuki", "support", "asentaja", "kenttä", "field", "lähituki", "helpdesk", "service desk",
           "teknikko", "technician", "datakeskus", "data center", "data centre", "laite"],
}
DATA_CENTRE_WORDS = ["datakeskus", "data center", "data centre"]

MAX_PAGES = 3          # about 20 jobs per page
DELAY_SECONDS = 10     # Jobly robots.txt asks for 10 s between requests
BASE = SOURCES["jobly"]["base_url"]
# URLs come from sources.json; the names stay because the readers and tests use them
METSALEHTI_FEED = SOURCES["metsalehti"]["urls"]["feed"]
METSALEHTI_JOBS = SOURCES["metsalehti"]["urls"]["jobs"]      # read when the feed is empty
METSALEHTI_JOB_LINK = SOURCES["metsalehti"]["link_pattern"]
METSAHALLITUS_FEED = SOURCES["metsahallitus"]["urls"]["feed"]
METSAKESKUS_JOBS = SOURCES["metsakeskus"]["urls"]["jobs"]
DUUNITORI_JOBS = SOURCES["duunitori"]["urls"]["search"]
DUUNITORI_JOENSUU_JOBS = SOURCES["duunitori"]["urls"]["joensuu"]
UEF_JOBS = SOURCES["uef"]["urls"]["fi"]
UEF_JOBS_EN = SOURCES["uef"]["urls"]["en"]
VARBI_JOB_LINK = SOURCES["uef"]["id_pattern"]
# Valtiolle.fi: every state agency. The whole feed is only a few hundred items, so read all of it in
# both languages: the English feed carries English-only postings that the Finnish one leaves out.
VALTIOLLE_FEEDS = [SOURCES["valtiolle"]["urls"]["fi"], SOURCES["valtiolle"]["urls"]["en"]]
# Kuntarekry.fi: the full feed stops at the newest 500 of several thousand jobs, so use its free-text
# search (desc=) with each active field's search_terms; results are filtered like every other source.
KUNTAREKRY_KEYWORDS = FORESTRY["search_terms"]
KUNTAREKRY_FEED = SOURCES["kuntarekry"]["url_template"]
# Valtiolle and Kuntarekry run on the same platform; a posting keeps its number across languages
PORTAL_POSTING_ID = r"-(\d+)/?$"
WORKDAY_SOURCES = [(s["name"], s["urls"]["api"], s["urls"]["jobs"])
                   for s in SOURCES.values() if s["reader"] == "workday"]
# Names JobDesk instead of pretending to be a browser; robots.txt rules are matched on "JobDesk"
USER_AGENT = core_fetch.user_agent()

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
    if sys.platform == "darwin":
        system_roots = subprocess.run(
            ["security", "find-certificate", "-a", "-p",
             "/System/Library/Keychains/SystemRootCertificates.keychain"],
            check=True, capture_output=True, text=True,
        ).stdout
        if system_roots:
            ctx.load_verify_locations(cadata=system_roots)
    return ctx


SSL_CONTEXT = ssl_context()


def _fetch_robots(url):
    """(status, text) of a robots.txt file for RobotsCache; status None when the site can't be reached."""
    return core_fetch.fetch_status_text(url, context=SSL_CONTEXT, agent=USER_AGENT)


ROBOTS = RobotsCache(_fetch_robots)


def robots_allowed(url):
    """True when robots.txt lets JobDesk read url; logs and returns False otherwise."""
    if ROBOTS.allowed(url):
        return True
    print(f"  - skipped (robots.txt): {url}")
    return False


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


def to_iso(text):
    """'30.10.2026' -> '2026-10-30'; anything else -> ''."""
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text or "")
    if not m:
        return ""
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date().isoformat()
    except ValueError:
        return ""


def parse_rss_jobs(body, base_url):
    """Read job entries from an RSS feed."""
    root = ElementTree.fromstring(body)
    jobs = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        fields = {}
        for child in item:
            name = child.tag.rsplit("}", 1)[-1]
            if name in {"title", "link", "guid", "pubDate", "description"}:
                fields[name] = "".join(child.itertext()).strip()
        title = fields.get("title", "")
        link = fields.get("link", "")
        if not title or not link:
            continue
        url = urljoin(base_url, link)
        parsed_url = urlsplit(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            continue
        posted = ""
        if fields.get("pubDate"):
            try:
                posted = parsedate_to_datetime(fields["pubDate"]).date().isoformat()
            except (TypeError, ValueError, OverflowError):
                posted = to_iso(fields["pubDate"])
        jobs.append({
            "id": fields.get("guid") or url,
            "title": title,
            "url": url,
            "company": "",
            "location": "",
            "posted": posted,
            "description": html.unescape(fields.get("description", "")),
        })
    return jobs


def parse_metsalehti_feed(body):
    """Read job entries from Metsälehti's RSS feed."""
    return parse_rss_jobs(body, "https://www.metsalehti.fi/")


class JobLinkParser(HTMLParser):
    """Collect linked job titles from a known recruitment listing page."""

    def __init__(self, base_url, href_pattern):
        super().__init__()
        self.base_url = base_url
        self.href_pattern = re.compile(href_pattern, re.IGNORECASE)
        self.jobs = []
        self._link = None

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href", "")
        url = urljoin(self.base_url, href)
        if self.href_pattern.search(url):
            self._link = {"url": url, "title": []}

    def handle_endtag(self, tag):
        if tag != "a" or not self._link:
            return
        title = " ".join(" ".join(self._link["title"]).split())
        if title:
            self.jobs.append({
                "id": self._link["url"],
                "title": title,
                "url": self._link["url"],
                "company": "",
                "location": "",
                "posted": "",
                "description": "",
            })
        self._link = None

    def handle_data(self, data):
        if self._link:
            self._link["title"].append(data)


def parse_job_links(body, base_url, href_pattern):
    parser = JobLinkParser(base_url, href_pattern)
    parser.feed(body)
    return parser.jobs


def posting_id(url, pattern, fallback):
    """The posting's own number from its URL, so the Finnish and English pages of one ad match."""
    m = re.search(pattern, url or "")
    return m.group(1) if m else fallback


def parse_workday_jobs(payload, job_base):
    """Normalize a page of postings returned by Workday's public CXS endpoint."""
    jobs = []
    for posting in payload.get("jobPostings", []):
        external_path = posting.get("externalPath", "")
        title = posting.get("title", "").strip()
        if not title or not external_path.startswith("/job/"):
            continue
        bullet_fields = posting.get("bulletFields") or []
        jobs.append({
            "id": str(bullet_fields[0]) if bullet_fields else external_path.rsplit("/", 1)[-1],
            "title": title,
            "url": job_base.rstrip("/") + external_path,
            "company": "",
            "location": posting.get("locationsText", ""),
            "posted": "",
            "description": "",
        })
    return jobs


def fetch_workday_jobs(endpoint, job_base):
    jobs = []
    offset = 0
    page_size = 20
    total = None
    if not robots_allowed(endpoint):
        return jobs
    while total is None or offset < total:
        body = json.dumps({
            "appliedFacets": {},
            "limit": page_size,
            "offset": offset,
            "searchText": "",
        }).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "locale": "fi-FI",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            print(f"  ! {endpoint} -> {getattr(e, 'code', '')} {getattr(e, 'reason', e)}")
            return jobs
        postings = payload.get("jobPostings")
        if not isinstance(postings, list):
            raise ValueError(f"Unexpected Workday response from {endpoint}")
        if total is None:     # Workday reports the total on the first page only; later pages say 0
            total = int(payload.get("total") or len(postings))
        jobs.extend(parse_workday_jobs(payload, job_base))
        if not postings:
            break
        offset += len(postings)
    return jobs


def source_kind(job):
    """(kind, fields) of the source a job came from; jobs from unknown sources (Community,
    Manual, Personal) are 'general' and belong to no field by default."""
    source = SOURCE_BY_NAME.get(job.get("source") or "")
    if not source:
        return "general", ()
    return source["kind"], source["fields"]


def is_relevant_to(job, profile):
    kind, source_fields = source_kind(job)
    return core_fields.is_relevant(job, profile, kind, source_fields)


def relevant_fields(job, field_ids=None):
    """Ids of the fields (all, or the given ones) this job belongs to, in profile order."""
    wanted = PROFILES if field_ids is None else [i for i in PROFILES if i in field_ids]
    return [i for i in wanted if is_relevant_to(job, PROFILES[i])]


def is_forestry_related(job):
    return is_relevant_to(job, FORESTRY)


def title_has(title, word):
    return core_fields.has_word(title, word, WHOLE_WORDS)


def jobly_id(url):
    m = JOB_PATH.search((url or "").split("?")[0].replace("https://www.jobly.fi", ""))
    return m.group(2) if m else None


def fetch(url):
    """Body of a listing page or feed, or None when it can't be read or robots.txt disallows it."""
    if not robots_allowed(url):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "fi,en"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        print(f"  ! {url} -> {getattr(e, 'code', '')} {getattr(e, 'reason', e)}")
        return None


def fetch_page(url):
    """HTML of a single public page, or '' if it can't be read or robots.txt disallows it (core/fetch.py)."""
    return core_fetch.fetch_page(url, robots_allowed, context=SSL_CONTEXT, agent=USER_AGENT)


def fetch_ad_text(url):
    """Text of a single ad page, or '' if it can't be read or robots.txt disallows it (core/fetch.py)."""
    return core_fetch.fetch_ad_text(url, robots_allowed, context=SSL_CONTEXT, agent=USER_AGENT)


def read_metsalehti():
    """Metsälehti's jobs feed, or the links on its jobs page when the feed comes back empty."""
    body = fetch(METSALEHTI_FEED)
    jobs = parse_metsalehti_feed(body) if body else []
    if not jobs:
        time.sleep(DELAY_SECONDS)       # Metsälehti's robots.txt asks for 10 s between requests
        body = fetch(METSALEHTI_JOBS)
        jobs = parse_job_links(body, METSALEHTI_JOBS, METSALEHTI_JOB_LINK) if body else []
    return jobs


def read_portal_feeds(urls):
    """Valtiolle/Kuntarekry RSS feeds, one job per posting number across languages and searches."""
    jobs = {}
    for url in urls:
        body = fetch(url)
        if not body:
            continue
        for job in parse_rss_jobs(body, url):
            job["id"] = posting_id(job["url"], PORTAL_POSTING_ID, job["id"])
            jobs.setdefault(job["id"], job)
    return list(jobs.values())


def read_links(pages, base_url, href_pattern, id_pattern=None):
    """Job links from listing pages (e.g. a site's Finnish and English pages), deduplicated."""
    jobs = {}
    for url in pages:
        body = fetch(url)
        if not body:
            continue
        for job in parse_job_links(body, base_url, href_pattern):
            if id_pattern:
                job["id"] = posting_id(job["url"], id_pattern, job["id"])
            jobs.setdefault(job["id"], job)
    return list(jobs.values())


def guess_category(text):
    """Job type for an administrator's own non-forestry job added by hand."""
    t = (text or "").lower()
    if any(w in t for w in DATA_CENTRE_WORDS) or any(title_has(t, w) for w in TITLE_MUST_MATCH["it"]):
        return "IT-Data centre"
    if any(w in t for w in ("varasto", "logisti", "warehouse", "keräily", "trukki")):
        return "Warehouse"
    if any(w in t for w in ("rakennus", "rakentaj", "kirvesmies", "construction", "raudoittaj")):
        return "Construction"
    return "Industrial"


def active_field_ids(field_ids=None):
    """The fields to scrape: the given ones, or every field some member has chosen (db), in profile order."""
    wanted = set(field_ids if field_ids is not None else db.active_field_ids(config.DEFAULT_FIELDS))
    return [i for i in PROFILES if i in wanted]


def _covers(source, field_ids):
    return source["fields"] in ("all", "per-profile") or bool(set(source["fields"]) & set(field_ids))


def _enabled(source):
    if source.get("enable_env") == "JOBDESK_ENABLE_DUUNITORI":
        return config.ENABLE_DUUNITORI
    return source.get("enabled", True)


def _reader(source, field_ids):
    """A function returning the job dicts of one non-Jobly source (sources.json "reader")."""
    kind, urls = source["reader"], source.get("urls", {})
    if kind == "metsalehti":
        return read_metsalehti
    if kind == "rss":
        return lambda: parse_rss_jobs(fetch(urls["feed"]) or "<rss/>", source["base_url"])
    if kind == "portal_feeds":
        return lambda: read_portal_feeds(list(urls.values()))
    if kind == "keyword_feeds":       # one search per keyword of every active field
        words = list(dict.fromkeys(w for i in field_ids for w in PROFILES[i]["search_terms"]))
        return lambda: read_portal_feeds([source["url_template"].format(quote(word)) for word in words])
    if kind == "links":
        return lambda: read_links(list(urls.values()), source["base_url"], source["link_pattern"],
                                  source.get("id_pattern"))
    if kind == "workday":
        return lambda: fetch_workday_jobs(urls["api"], urls["jobs"])
    raise ValueError(f"Unknown reader {kind!r} in sources.json")


def sources(field_ids=None):
    """(source name, reader) for every enabled non-Jobly source that covers one of the fields
    (default: every field members have chosen). Duunitori only when JOBDESK_ENABLE_DUUNITORI=1."""
    field_ids = active_field_ids(field_ids)
    return [(s["name"], _reader(s, field_ids)) for s in SOURCES.values()
            if s["reader"] != "jobly" and _enabled(s) and _covers(s, field_ids)]


def jobly_pages(field_ids, personal=False):
    """(category, slug, title words) for each Jobly category page to read."""
    pages = [(PROFILES[i]["category"], slug, PROFILES[i]["jobly"]["title_words"])
             for i in field_ids for slug in PROFILES[i]["jobly"]["slugs"]]
    if personal:
        pages += [(category, slug, TITLE_MUST_MATCH.get(slug))
                  for category, slugs in PERSONAL_JOB_TYPES.items() for slug in slugs]
    return pages


def run(progress=None, user_id=1, personal=False, field_ids=None):
    """One full check. progress(message, done, total) is called as pages are read.
    field_ids: the fields to read (default: every field some member has chosen).
    personal=True also reads the administrator's own PERSONAL_CATEGORIES from Jobly."""
    field_ids = active_field_ids(field_ids)
    profiles = [PROFILES[i] for i in field_ids]
    pages = jobly_pages(field_ids, personal)
    readers = sources(field_ids)
    total = len(pages) + len(readers)
    check_id = db.start_check(user_id)
    found = new = 0
    seen_now = set()
    error = None
    try:
        first = True
        for n, (category, slug, words) in enumerate(pages):
            for page in range(MAX_PAGES):
                url = f"{BASE}/tyopaikat/{slug}" + (f"?page={page}" if page else "")
                if not first:      # Jobly asks for 10 s; a longer Crawl-delay in robots.txt wins
                    time.sleep(max(DELAY_SECONDS, ROBOTS.crawl_delay(url) or 0))
                first = False
                if progress:
                    progress(f"Reading {slug} page {page + 1}", n, total)
                body = fetch(url)
                if not body:
                    break
                parser = JoblyParser()
                parser.feed(body)
                fresh = [j for j in parser.jobs if ("Jobly", j["id"]) not in seen_now]
                if not fresh:
                    break
                for j in fresh:
                    seen_now.add(("Jobly", j["id"]))
                    if words and not any(title_has(j["title"], w) for w in words):
                        continue
                    cat = "IT-Data centre" if any(w in j["title"].lower() for w in DATA_CENTRE_WORDS) else category
                    is_new = db.upsert_scraped(
                        {"source": "Jobly", "external_id": j["id"], "url": j["url"], "title": j["title"],
                         "company": j["company"], "location": j["location"], "posted": j["posted"],
                         "category": cat},
                        check_id, user_id=user_id)
                    found += 1
                    new += is_new

        for source_index, (source, read) in enumerate(readers, start=len(pages)):
            if progress:
                progress(f"Reading {source} jobs", source_index, total)
            kind, source_fields = SOURCE_BY_NAME[source]["kind"], SOURCE_BY_NAME[source]["fields"]
            covered = [p for p in profiles if source_fields == "all" or p["id"] in source_fields]
            for job in read():
                matched = [p for p in covered
                           if core_fields.is_relevant({**job, "source": source}, p, kind, source_fields)]
                if not matched:
                    continue
                key = (source, job["id"])
                if key in seen_now:
                    continue
                seen_now.add(key)
                is_new = db.upsert_scraped(
                    {"source": source, "external_id": job["id"], "url": job["url"],
                     "title": job["title"], "company": job["company"], "location": job["location"],
                     "posted": job["posted"], "category": matched[0]["category"],
                     "description": job.get("description", "")},
                    check_id, user_id=user_id)
                found += 1
                new += is_new
    except Exception as e:      # keep what was saved; report the error in the dashboard
        error = f"{type(e).__name__}: {e}"
    db.finish_check(check_id, found, new, error, user_id=user_id)
    if progress:
        progress(f"Done: {found} jobs, {new} new" + (f" (error: {error})" if error else ""),
                 total, total)
    return {"found": found, "new": new, "error": error}
