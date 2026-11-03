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
  * When adding a source, check robots.txt. Duunitori disallows generic crawlers and Työmarkkinatori
    disallows /api/, so neither is expanded here.
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

import db

# Each job type -> Jobly category pages, https://www.jobly.fi/tyopaikat/<slug>
JOB_TYPES = {
    "Industrial": ["asentaja", "kokoonpanija", "tuotantotyontekija"],
    "Construction": ["rakennustyontekija", "rakennusmies"],
    "Warehouse": ["varastotyontekija", "logistiikkatyontekija"],
    # Finnish slugs only: Jobly has no English category slugs (see the module docstring).
    # harjoittelija and kesatyo are filtered by FORESTRY_WORDS in the title, like the others.
    "Forestry": ["metsuri", "metsatyontekija", "paikkatietoasiantuntija", "harjoittelija", "kesatyo"],
    "IT-Data centre": ["it"],
}
# The administrator's own job search from before Woodesk became a forestry portal. These categories
# are scraped only for the administrator, stored under their account and never shown to members.
PERSONAL_CATEGORIES = [t for t in JOB_TYPES if t != "Forestry"]
# Default CV for each job type (the Match column may suggest a better one)
CV_FOR_TYPE = {
    "Industrial": "industrial-master",
    "Construction": "industrial-master",     # construction-master was merged into it (cv repo, 2026-10-31)
    "Warehouse": "warehouse-master",
    "Forestry": "forestry-master",
    "IT-Data centre": "it-field-technician",
}
# Broad categories: keep only titles containing one of these words (lower-case)
FORESTRY_WORDS = [
    "metsä", "metsuri", "puunhankin", "taimikon", "istutus", "raivaus", "metsätalous",
    "metsänhoito", "metsätalou", "metsävarat", "metsätieto", "metsäekolog", "metsätiete",
    "paikkatieto", "geoinformati", "kaukokartoit", "maastokartoit", "kartoitus", "luonnonvara",
    "luonnonhoid",
    "ennallist", "biodiversiteet", "monimuotoisuus", "luontokato", "hiilinielu", "biotalous",
    "bioenergia", "forest", "forestry", "timber", "wood sourcing", "forest management",
    "forest inventory", "remote sensing", "geospatial", "geoinformatics", "bioeconomy",
    "biodiversity", "natural resources", "ecolog", "sustainable forestry",
    "puukaup", "timber trade", "wood procurement", "puutavara", "korjuusuunnit", "sawmill",
    "sahateollisuu", "luontoselvit", "luontokartoit", "nature survey", "luonnonsuojelu",
    "nature conservation", "peatland", "turvemaa", "suometsä",
]
FORESTRY_RELEVANCE_WORDS = [
    "metsuri", "metsäasiantunt", "metsäalan", "metsäinsin", "metsäkone", "metsätalou",
    "metsänhoid", "metsänkasvat", "metsävarat", "metsätieto", "metsäekolog", "metsätiete",
    "metsäteollisuus", "metsätuott", "puunhankin", "puunkorju", "taimikon", "istutus", "raivaus",
    "paikkatieto", "gis", "geoinformati", "kaukokartoit", "maastokartoit", "kartoitus",
    "luonnonvar", "luonnonhoid", "ennallist", "biodiversiteet", "monimuotoisuus",
    "luontokato", "hiilinielu", "biotalous", "bioenergia", "forest", "forestry", "timber",
    "wood sourcing", "forest management", "forest inventory", "remote sensing", "geospatial",
    "geoinformatics", "bioeconomy", "biodiversity", "natural resources", "ecolog", "skog",
    "sustainab", "vastuullisuus", "kestävyys", "ilmasto", "climate", "renewable material",
    "renewable fibre", "biomaterial",
    # Finnish / English pairs taken from the 2025 forestry internship job titles
    "metsänhoit", "metsien", "metsävastaav", "metsäneuvo", "metsätyönjoht", "metsäharjoitt",
    "metsäpalvel", "forest service", "metsänomist", "metsälannoit", "metsäsuunnit",
    "metsänjalost", "tree breeding", "taimitarh", "taimituotan", "seedling",
    "puukaup", "timber trade", "wood procurement", "puutavara", "puunkuljet", "timber transport",
    "korjuusuunnit", "timber harvesting", "sawmill", "sahateollisuu",
    "luontoselvit", "luontokartoit", "nature survey", "luonnonsuojelu", "nature conservation",
    "habitat", "peatland", "turvemaa", "suometsä", "hiilivarast", "carbon stock",
]
# Valtiolle and Kuntarekry feeds carry the whole ad, where words such as "ilmasto", "kestävyys",
# "monimuotoisuus" or "paikkatieto" appear in police, school and water-engineering ads alike. For
# these sources the title may match any word above, but the ad text must match one of these.
BROAD_AD_SOURCES = {"Valtiolle", "Kuntarekry"}
FORESTRY_CORE_WORDS = [
    "metsuri", "metsäasiantunt", "metsäalan", "metsäinsin", "metsäkone", "metsätalou",
    "metsänhoid", "metsänhoit", "metsänkasvat", "metsävarat", "metsätieto", "metsäekolog",
    "metsätiete", "metsäteollisuus", "metsätuott", "metsien", "metsäpalvel", "metsänomist",
    "metsäsuunnit", "metsänjalost", "puunhankin", "puunkorju", "puukaup", "puutavara", "taimikon",
    "luonnonhoid", "luonnonsuojelu", "ennallist", "luontoselvit", "luontokartoit", "suometsä",
    "biotalous", "forest", "timber", "wood procurement", "nature survey", "peatland", "bioeconomy",
]
# Organisation names that contain a forestry word but say nothing about the job itself
ORGANISATION_NAMES = re.compile(r"maa- ja metsätalousministeri\w*|ministry of agriculture and forestry")
# Boards that only list forestry-sector jobs: everything they publish is kept, even titles such as
# "Operaatioasiantuntija, tuotanto" that name no forestry word.
FORESTRY_ONLY_SOURCES = {"Metsälehti"}
TITLE_MUST_MATCH = {
    "it": ["tuki", "support", "asentaja", "kenttä", "field", "lähituki", "helpdesk", "service desk",
           "teknikko", "technician", "datakeskus", "data center", "data centre", "laite"],
    **{slug: FORESTRY_WORDS for slug in JOB_TYPES["Forestry"]},
}
# Words matched as whole words only ("gis" is inside "logistiikka")
WHOLE_WORDS = {"gis", "skog"}      # "skog" also ends place names such as Västerskog
DATA_CENTRE_WORDS = ["datakeskus", "data center", "data centre"]

MAX_PAGES = 3          # about 20 jobs per page
DELAY_SECONDS = 10     # Jobly robots.txt asks for 10 s between requests
BASE = "https://www.jobly.fi"
METSALEHTI_FEED = "https://www.metsalehti.fi/tyopaikat/feed/"
METSALEHTI_JOBS = "https://www.metsalehti.fi/tyopaikat/"      # read when the feed is empty
METSALEHTI_JOB_LINK = r"metsalehti\.fi/tyopaikat/(?!feed/?$|page/)[a-z0-9-]+/?$"
METSAHALLITUS_FEED = "https://metsa.rekrytointi.com/paikat/?o=A_RSS&jgid=2"
METSAKESKUS_JOBS = (
    "https://www.metsakeskus.fi/fi/tietoa-meista/toihin-metsakeskukseen/avoimet-tyopaikat"
)
DUUNITORI_JOBS = "https://duunitori.fi/tyopaikat?haku=mets%C3%A4ala"
DUUNITORI_JOENSUU_JOBS = (
    "https://duunitori.fi/tyopaikat/alue/joensuu?haku=mets%C3%A4ala"
)
UEF_JOBS = "https://www.uef.fi/fi/avoimet-tyopaikat"
UEF_JOBS_EN = "https://www.uef.fi/en/open-positions"
VARBI_JOB_LINK = r"uef\.varbi\.com/(?:fi|en)/what:job/jobID:(\d+)"
# Valtiolle.fi: every state agency (Luke, Metsähallitus, MMM, SYKE, ELY, Maanmittauslaitos ...).
# The whole feed is only a few hundred items, so read all of it in both languages: the English
# feed carries English-only postings that the Finnish one leaves out. (The old Luke-only feed,
# organisation=28, returns no items any more.)
VALTIOLLE_FEEDS = [
    "https://valtiolle.fi/fi/tyopaikat/?sort=-changetime&limit=1000&format=rss",
    "https://valtiolle.fi/en/jobs/?sort=-changetime&limit=1000&format=rss",
]
# Kuntarekry.fi: municipalities, joint authorities and their companies. The full feed stops at the
# newest 500 of several thousand jobs, so use its free-text search (desc=) with Finnish, English
# and Swedish keywords; results are filtered with is_forestry_related like every other source.
KUNTAREKRY_KEYWORDS = ["metsä", "forest", "skogs", "luonto", "luonnonvara", "paikkatieto"]
KUNTAREKRY_FEED = "https://kuntarekry.fi/fi/tyopaikat/?desc={}&sort=-changetime&limit=500&format=rss"
# Valtiolle and Kuntarekry run on the same platform; a posting keeps its number across languages
PORTAL_POSTING_ID = r"-(\d+)/?$"
WORKDAY_SOURCES = [
    ("Metsä Group", "https://metsagroup.wd103.myworkdayjobs.com/wday/cxs/metsagroup/MetsaGroup_Careers/jobs",
     "https://metsagroup.wd103.myworkdayjobs.com/fi-FI/MetsaGroup_Careers"),
    ("UPM", "https://upm.wd103.myworkdayjobs.com/wday/cxs/upm/Careers/jobs",
     "https://upm.wd103.myworkdayjobs.com/fi-FI/Careers"),
    ("Stora Enso", "https://storaenso.wd502.myworkdayjobs.com/wday/cxs/storaenso/"
     "Stora_Enso_site_opportunities/jobs",
     "https://storaenso.wd502.myworkdayjobs.com/fi-FI/Stora_Enso_site_opportunities"),
]
USER_AGENT = "Mozilla/5.0 (personal job check; low volume)"

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


def is_forestry_related(job):
    if job.get("source") in FORESTRY_ONLY_SOURCES:
        return True
    if job.get("source") in BROAD_AD_SOURCES:
        ad = " ".join((job.get(field) or "") for field in ("description", "ad_text"))
        ad = ORGANISATION_NAMES.sub(" ", ad.lower())
        return (any(title_has(job.get("title") or "", word) for word in FORESTRY_RELEVANCE_WORDS)
                or any(title_has(ad, word) for word in FORESTRY_CORE_WORDS))
    text = " ".join((job.get(field) or "") for field in ("title", "description", "ad_text", "location"))
    return any(title_has(text, word) for word in FORESTRY_RELEVANCE_WORDS)


def title_has(title, word):
    t = title.lower()
    return re.search(rf"\b{re.escape(word)}\b", t) is not None if word in WHOLE_WORDS else word in t


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
    if not is_public_http_url(url):
        return ""
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=SSL_CONTEXT),
        PublicRedirectHandler(),
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "fi,en"})
    try:
        with opener.open(req, timeout=15) as response:
            body = response.read(2_000_000).decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as error:
        print(f"  ! {url} -> {getattr(error, 'code', '')} {getattr(error, 'reason', error)}")
        return ""
    p = TextExtractor()
    p.feed(body)
    return "\n".join(p.parts)[:20000]


def is_public_http_url(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = {ipaddress.ip_address(parsed.hostname)}
        except ValueError:
            addresses = {
                ipaddress.ip_address(result[4][0])
                for result in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
            }
        return bool(addresses) and all(address.is_global for address in addresses)
    except (OSError, ValueError, TypeError):
        return False


class PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if not is_public_http_url(new_url):
            raise urllib.error.HTTPError(request.full_url, code, "Redirect to a non-public address refused.", headers, response)
        return super().redirect_request(request, response, code, message, headers, new_url)


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


def run(progress=None, user_id=1, personal=False):
    """One full check. progress(message, done, total) is called as pages are read.
    personal=True also reads the administrator's own PERSONAL_CATEGORIES from Jobly."""
    pages = [(category, slug) for category in ["Forestry"] + (PERSONAL_CATEGORIES if personal else [])
             for slug in JOB_TYPES[category]]
    # (source name, reader). Each reader returns job dicts; is_forestry_related filters them.
    sources = [
        ("Metsälehti", read_metsalehti),
        ("Metsähallitus", lambda: parse_rss_jobs(fetch(METSAHALLITUS_FEED) or "<rss/>",
                                                  "https://metsa.rekrytointi.com/")),
        ("Valtiolle", lambda: read_portal_feeds(VALTIOLLE_FEEDS)),
        ("Kuntarekry", lambda: read_portal_feeds(
            [KUNTAREKRY_FEED.format(quote(word)) for word in KUNTAREKRY_KEYWORDS])),
        ("Metsäkeskus", lambda: read_links([METSAKESKUS_JOBS], "https://www.metsakeskus.fi/",
                                           r"ats\.talentadore\.com/apply/")),
        ("Duunitori", lambda: read_links([DUUNITORI_JOBS, DUUNITORI_JOENSUU_JOBS],
                                         "https://duunitori.fi/", r"duunitori\.fi/tyopaikat/tyo/")),
        ("UEF", lambda: read_links([UEF_JOBS, UEF_JOBS_EN], "https://www.uef.fi/",
                                   VARBI_JOB_LINK, VARBI_JOB_LINK)),
    ] + [(name, lambda endpoint=endpoint, job_base=job_base: fetch_workday_jobs(endpoint, job_base))
         for name, endpoint, job_base in WORKDAY_SOURCES]
    total = len(pages) + len(sources)
    check_id = db.start_check(user_id)
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
                    words = TITLE_MUST_MATCH.get(slug)
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

        for source_index, (source, read) in enumerate(sources, start=len(pages)):
            if progress:
                progress(f"Reading {source} jobs", source_index, total)
            for job in read():
                if not is_forestry_related({**job, "source": source}):
                    continue
                key = (source, job["id"])
                if key in seen_now:
                    continue
                seen_now.add(key)
                is_new = db.upsert_scraped(
                    {"source": source, "external_id": job["id"], "url": job["url"],
                     "title": job["title"], "company": job["company"], "location": job["location"],
                     "posted": job["posted"], "category": "Forestry",
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
