"""Job feed reader. Reads the job feeds in sources.json and stores the jobs in SQLite via db.py, each
tagged with its career fields (core/taxonomy.py). A job is NEW when the latest check is the first one
that saw it.

SOURCE POLICY - by default only feeds published for reuse (RSS) whose robots.txt allows reading are
read: the state and municipal portals (Valtiolle, Kuntarekry) and a few sector feeds. Page readers and
internal APIs (employer career sites, Workday) are off; JOBDESK_ENABLE_SOURCES turns one on only once its
owner has given permission. There are no readers for job boards (Jobly, Duunitori, LinkedIn ...): their
terms or robots.txt forbid it. See sources.json.

LANGUAGE CHECK - every source has Finnish and English variants, and they are not always the same:
  * URL slugs differ (valtiolle.fi/fi/tyopaikat/ vs /en/jobs/, uef.varbi.com/fi/ vs /en/,
    Workday fi-FI vs en-US). English-only postings (e.g. research assistant and summer-trainee ads)
    can be missing from the Finnish listing, so read both and deduplicate by the posting's number.
  * Search keywords and category/tag slugs must be given in both languages (metsä + forest,
    harjoittelija + intern/trainee, kesätyö + summer job). Swedish (skog) catches bilingual ads.
  * When adding a source, check robots.txt and the site's terms, and note both in sources.json.
    Työmarkkinatori's public pages are not read; its search API needs credentials (see sources.json).

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
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit
from xml.etree import ElementTree

import config
import db
from core import fetch as core_fetch
from core import fields as core_fields
from core import importers as core_importers
from core import jobmeta as core_jobmeta
from core import taxonomy as core_taxonomy
from core.fetch import PublicRedirectHandler, TextExtractor, is_public_http_url  # noqa: F401 (re-exported)
from core.robots import RobotsCache

# Field profiles (fields/*.json) and job sources (sources.json) are configuration, not code.
PROFILES = core_fields.load_profiles(config.FIELDS_DIR)       # keyword profiles of some fields (fields/*.json)
TAXONOMY = core_taxonomy.load(config.TAXONOMY_DIR)            # every career field and its roles (taxonomy/)
FORESTRY = PROFILES["forestry"]
with open(config.SOURCES_FILE, encoding="utf-8") as _file:
    SOURCE_CONFIG = json.load(_file)
SOURCES = {source["id"]: source for source in SOURCE_CONFIG["sources"]}
SOURCE_BY_NAME = {source["name"]: source for source in SOURCES.values()}

# The administrator's own job types from before JobDesk covered several fields (they came from Jobly
# searches, which are no longer read). Jobs stored with these categories stay in the administrator's
# account and are never shown to members.
PERSONAL_CATEGORIES = ["Industrial", "Construction", "Warehouse", "IT-Data centre"]
# Default CV for each job type (the Match column may suggest a better one)
CV_FOR_TYPE = {
    "Industrial": "industrial-master",
    "Construction": "industrial-master",     # construction-master was merged into it (cv repo, 2026-10-31)
    "Warehouse": "warehouse-master",
    "Forestry": "forestry-master",
    "IT-Data centre": "it-field-technician",
}
# The forestry word lists now live in fields/forestry.json; these names stay for older code
FORESTRY_RELEVANCE_WORDS = FORESTRY["relevance"]["words"]
FORESTRY_CORE_WORDS = FORESTRY["relevance"]["core_words"]
WHOLE_WORDS = set(FORESTRY["relevance"]["whole_words"])
# Sources by kind (sources.json): field boards list only their fields' jobs; broad portals list
# every public-sector job, so they get the stricter core-word rule (core/fields.py).
FORESTRY_ONLY_SOURCES = {s["name"] for s in SOURCES.values() if s["kind"] == "field_board"}
BROAD_AD_SOURCES = {s["name"] for s in SOURCES.values() if s["kind"] == "broad_portal"}
# The administrator's IT-Data centre type (jobs added by hand): a title must contain one of these words
TITLE_MUST_MATCH = {
    "it": ["tuki", "support", "asentaja", "kenttä", "field", "lähituki", "helpdesk", "service desk",
           "teknikko", "technician", "datakeskus", "data center", "data centre", "laite"],
}
DATA_CENTRE_WORDS = ["datakeskus", "data center", "data centre"]

DELAY_SECONDS = 10     # Metsälehti's robots.txt asks for 10 s between requests
# URLs come from sources.json; the names stay because the readers and tests use them
METSALEHTI_FEED = SOURCES["metsalehti"]["urls"]["feed"]
METSALEHTI_JOBS = SOURCES["metsalehti"]["urls"]["jobs"]      # read when the feed is empty
METSALEHTI_JOB_LINK = SOURCES["metsalehti"]["link_pattern"]
METSAHALLITUS_FEED = SOURCES["metsahallitus"]["urls"]["feed"]
METSAKESKUS_JOBS = SOURCES["metsakeskus"]["urls"]["jobs"]
UEF_JOBS = SOURCES["uef"]["urls"]["fi"]
UEF_JOBS_EN = SOURCES["uef"]["urls"]["en"]
VARBI_JOB_LINK = SOURCES["uef"]["id_pattern"]
# Valtiolle.fi: every state agency. The whole feed is only a few hundred items, so read all of it in
# both languages: the English feed carries English-only postings that the Finnish one leaves out.
VALTIOLLE_FEEDS = [SOURCES["valtiolle"]["urls"]["fi"], SOURCES["valtiolle"]["urls"]["en"]]
# Kuntarekry.fi: the full feed stops at the newest 500 of several thousand jobs, so use its free-text
# search (desc=) with each active field's search_terms; results are filtered like every other source.
KUNTAREKRY_FEEDS = list(SOURCES["kuntarekry"]["urls"].values())
# Valtiolle and Kuntarekry run on the same platform; a posting keeps its number across languages
PORTAL_POSTING_ID = r"-(\d+)/?$"
WORKDAY_SOURCES = [(s["name"], s["urls"]["api"], s["urls"]["jobs"])
                   for s in SOURCES.values() if s["reader"] == "workday"]
# Names JobDesk instead of pretending to be a browser; robots.txt rules are matched on "JobDesk"
USER_AGENT = core_fetch.user_agent()

# A Jobly ad address a member pastes in (never fetched by the job check): used to recognise the same ad
JOB_PATH = re.compile(r"/(?:en/job|tyopaikka)/([a-z0-9-]+-(\d+))/?$")


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


def classify_job(job, kind=None, source_fields=None):
    """Career field ids for a job (core/taxonomy.py): its title's roles, the keyword profiles of the fields
    that have one (fields/*.json, judged with the source's kind), and its old category."""
    if kind is None:
        kind, source_fields = source_kind(job)
    profile_hits = [f["id"] for f in TAXONOMY.fields if f.get("profile") in PROFILES
                    and core_fields.is_relevant(job, PROFILES[f["profile"]], kind, source_fields)]
    return TAXONOMY.classify(job, profile_hits)


def job_meta(job):
    """What the ad says about the job (core/jobmeta.py): level, type, place, dates, pay, languages ...
    A source's "sector" in sources.json (e.g. the state and municipal portals: public) is used for its jobs."""
    source = SOURCE_BY_NAME.get(job.get("source") or "") or {}
    return core_jobmeta.extract(job, source.get("sector", ""))


def stored_fields(job):
    """The job's field ids as saved in job_fields (db rows carry them as "it,health"), or None when the
    row doesn't say (then callers classify)."""
    value = job.get("field_ids")
    if value is None:
        return None
    return [f for f in (value.split(",") if isinstance(value, str) else value) if f]


def relevant_fields(job, field_ids=None):
    """Ids of the fields (all, or the given ones) this job belongs to, in display order: the saved ones
    when the job has them, otherwise worked out now."""
    found = stored_fields(job)
    if found is None:
        found = classify_job(job)
    return [f for f in TAXONOMY.field_ids() if f in found and (field_ids is None or f in field_ids)]


def category_for(field_ids):
    """The job "Type" shown in lists: the first field's old category where it has a keyword profile
    (so "Forestry" stays "Forestry"), otherwise the field's English name; "Other" for none."""
    if not field_ids:
        return "Other"
    field = TAXONOMY.by_id[field_ids[0]]
    profile = PROFILES.get(field.get("profile") or "")
    return profile["category"] if profile else field["en"]


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


def default_field_ids():
    """config.DEFAULT_FIELDS with "all" expanded to every taxonomy field."""
    if "all" in config.DEFAULT_FIELDS:
        return TAXONOMY.field_ids()
    return [i for i in TAXONOMY.field_ids() if i in config.DEFAULT_FIELDS]


def active_field_ids(field_ids=None):
    """The fields to read: the given ones, or every field some member has chosen (db), in display order."""
    wanted = set(field_ids if field_ids is not None else db.active_field_ids(default_field_ids()))
    return [i for i in TAXONOMY.field_ids() if i in wanted]


def _covers(source, field_ids):
    return source["fields"] in ("all", "per-profile") or bool(set(source["fields"]) & set(field_ids))


def _enabled(source):
    """A source is read when sources.json has it on, or when this copy lists it in JOBDESK_ENABLE_SOURCES
    (for a source switched off over its terms, once the site has given permission)."""
    if source["id"] in config.ENABLE_SOURCES:
        return True
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
        words = list(dict.fromkeys(w for i in field_ids if i in PROFILES for w in PROFILES[i]["search_terms"]))
        return lambda: read_portal_feeds([source["url_template"].format(quote(word)) for word in words])
    if kind == "links":
        return lambda: read_links(list(urls.values()), source["base_url"], source["link_pattern"],
                                  source.get("id_pattern"))
    if kind == "workday":
        return lambda: fetch_workday_jobs(urls["api"], urls["jobs"])
    raise ValueError(f"Unknown reader {kind!r} in sources.json")


def sources(field_ids=None):
    """(source name, reader) for every enabled feed source that covers one of the fields
    (default: every field members have chosen). API adapters are read separately."""
    field_ids = active_field_ids(field_ids)
    return [(s["name"], _reader(s, field_ids)) for s in SOURCES.values()
            if s["reader"] != "adapter" and _enabled(s) and _covers(s, field_ids)]


CHECK_BUSY = "Another job check is already running."


def run_exclusive(*args, **kwargs):
    """run(), but never two at once, even across processes: the "Check for new jobs" button (inside the
    server) and the scheduled check (server.py --check-jobs, from a systemd timer) share data/job-check.lock.
    When a check is already running this returns at once with error CHECK_BUSY."""
    import fcntl
    db.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(db.DATA_DIR / "job-check.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"found": 0, "new": 0, "error": CHECK_BUSY}
        return run(*args, **kwargs)


def run(progress=None, user_id=1, field_ids=None):
    """One full check of the feeds and API adapters. progress(message, done, total) is called as sources
    are read. field_ids: the fields to read (default: every field some member has chosen)."""
    field_ids = active_field_ids(field_ids)
    readers = sources(field_ids)
    adapters = [a for a in core_importers.enabled_adapters() if _enabled(SOURCES[a.id])]
    total = len(readers) + len(adapters)
    check_id = db.start_check(user_id)
    found = new = 0
    seen_now = set()
    answered = set()       # feed sources that returned at least one posting
    error = None
    try:
        def store(source, job):
            """Save one posting from a feed or an adapter. Returns 1 when it was new."""
            nonlocal found
            answered.add(source)
            kind, source_fields = SOURCE_BY_NAME[source]["kind"], SOURCE_BY_NAME[source]["fields"]
            # Every career field counts; a job no field recognises (no role in its title, no field word
            # where the source's kind requires one) is left out, as before.
            matched = [f for f in classify_job({**job, "source": source}, kind, source_fields) if f in field_ids]
            key = (source, job["id"])
            if not matched or key in seen_now:
                return 0
            seen_now.add(key)
            item = {"source": source, "external_id": job["id"], "url": job["url"],
                    "title": job["title"], "company": job["company"], "location": job["location"],
                    "posted": job["posted"], "category": category_for(matched),
                    "description": job.get("description", ""), "deadline": job.get("deadline", "")}
            meta = job_meta(item)
            if item["deadline"] and not meta.get("deadline"):
                meta["deadline"] = item["deadline"]
            found += 1
            return int(db.upsert_scraped(item, check_id, user_id=user_id, fields=matched, meta=meta))

        for source_index, (source, read) in enumerate(readers):
            if progress:
                progress(f"Reading {source} jobs", source_index, total)
            for job in read():
                new += store(source, job)
        # APIs that need credentials (core/importers.py); each is off until its credentials are set
        for adapter in adapters:
            if progress:
                progress(f"Reading {adapter.name} jobs", total, total)
            try:
                for job in adapter.read():
                    new += store(adapter.name, job)
            except core_importers.ImporterError as e:
                error = str(e)
                answered.discard(adapter.name)
    except Exception as e:      # keep what was saved; report the error in the dashboard
        error = f"{type(e).__name__}: {e}"
    # Close listings that are over. Absence from a feed counts only for sources that answered with postings
    # in this check (a failed fetch returns nothing, and must not close every job), and only when every
    # field was read (otherwise jobs of the fields left out weren't refreshed).
    complete = set(field_ids) >= set(TAXONOMY.field_ids())
    today = date.today().isoformat()
    # Listings from sources that are no longer read at all (removed or switched off) close after a week unseen
    read_now = [name for name, _ in readers] + [a.name for a in adapters] if complete else None
    db.expire_jobs(today, sorted(answered) if complete and not error else (), read_now=read_now)
    for adapter in adapters:            # an API's terms may ask for deleted ads to go sooner
        if complete and adapter.name in answered:
            db.expire_jobs(today, [adapter.name], adapter.remove_missing_after_days)
    db.finish_check(check_id, found, new, error, user_id=user_id)
    if progress:
        progress(f"Done: {found} jobs, {new} new" + (f" (error: {error})" if error else ""),
                 total, total)
    return {"found": found, "new": new, "error": error}
