"""Public pages: open jobs anyone can browse without an account, written as plain HTML on the server so
search engines can read them.

    /jobs                         every open public job, with ?q= &page= (searches are noindex)
    /jobs/summer  /jobs/no-finnish  /jobs/remote
    /jobs/field/<id>  /jobs/level/<level>  /jobs/type/<type>  /jobs/town/<town>  /jobs/region/<region>
    and combinations in that order: /jobs/field/it/level/internship/town/tampere
    /job/<id>-<title>             one job, with schema.org JobPosting data
    /sitemap.xml  /robots.txt

What is public (is_public): open shared listings from the sources in sources.json (unless a source says
"public_pages": false; Työmarkkinatori's terms are being checked) and approved employer ads. Never: a
member's own saved jobs, jobs members shared, the administrator's own job types, closed listings, or any
contact detail. Ad text from feeds is shown as a short excerpt with a link to the original ad; an
employer's own ad is shown in full.

Every page sends X-Robots-Tag: pages with jobs are "index, follow"; empty pages, keyword searches and
closed jobs are "noindex, follow". Everything else on the site stays "noindex, nofollow" (server.py).
Standard library only; every value is escaped.
"""

import json
import re
import unicodedata
from datetime import date, datetime
from html import escape
from urllib.parse import urlencode

import config
import db
import scraper
import search
from core import jobmeta
from core import places as core_places

PAGE_SIZE = 20
EXCERPT_CHARS = 600
PUBLIC_EXTRA_SOURCES = {"Employer", "Demo"}       # not in sources.json; Demo only exists in development data
INDEX = "index, follow"
NOINDEX = "noindex, follow"

LEVEL_NOUN = {"thesis": "Thesis positions", "internship": "Internships", "trainee": "Trainee programmes",
              "entry": "Entry-level jobs", "experienced": "Jobs for experienced people"}
TYPE_NOUN = {"summer": "Summer jobs", "part_time": "Part-time jobs", "full_time": "Full-time jobs",
             "fixed_term": "Fixed-term jobs", "permanent": "Permanent jobs", "apprenticeship": "Apprenticeships",
             "gig": "Gig work"}
LABEL = {
    "level": {"thesis": "Thesis", "internship": "Internship", "trainee": "Trainee programme", "entry": "Entry level",
              "experienced": "Experienced"},
    "type": {"summer": "Summer job", "full_time": "Full-time", "part_time": "Part-time", "fixed_term": "Fixed-term",
             "permanent": "Permanent", "apprenticeship": "Apprenticeship", "gig": "Gig work"},
    "mode": {"onsite": "On site", "hybrid": "Hybrid", "remote": "Remote"},
    "permit": {"citizenship": "Finnish citizenship required", "security_clearance": "Security clearance",
               "eu_eea": "EU/EEA right to work", "right_to_work": "Needs the right to work in Finland",
               "sponsorship": "Visa or permit support offered"},
    "finnish": {"required": "Finnish required", "preferred": "Finnish an advantage", "not_needed": "Finnish not needed",
                "unclear": "Finnish not mentioned"},
    "period": {"hour": "/ hour", "month": "/ month", "year": "/ year"},
}
# schema.org JobPosting employmentType
SCHEMA_TYPE = {"full_time": "FULL_TIME", "part_time": "PART_TIME", "fixed_term": "TEMPORARY", "summer": "TEMPORARY",
               "gig": "PER_DIEM", "permanent": "FULL_TIME"}
SCHEMA_PERIOD = {"hour": "HOUR", "month": "MONTH", "year": "YEAR"}


# ---------------------------------------------------------------- slugs and visibility

def slugify(text):
    text = (text or "").lower().replace("ä", "a").replace("ö", "o").replace("å", "a")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


class Slugs:
    def __init__(self):
        places = core_places.load()
        self.town = {slugify(m["fi"]): m["code"] for m in places.municipalities}
        self.town_slug = {code: slug for slug, code in self.town.items()}
        self.region = {slugify(r["en"]): r["code"] for r in places.regions}
        self.region_slug = {code: slug for slug, code in self.region.items()}
        self.field = {f["id"].replace("_", "-"): f["id"] for f in scraper.TAXONOMY.fields}
        self.level = {code: code for code in jobmeta.LEVELS}
        self.type = {code.replace("_", "-"): code for code in jobmeta.EMPLOYMENT_TYPES}


_slugs = None


def slugs():
    global _slugs
    if _slugs is None:
        _slugs = Slugs()
    return _slugs


def is_public(job, include_closed=False):
    """True for a shared listing anyone may see (see the module docstring). include_closed: also closed
    ones (a job page then says the ad has closed)."""
    if job.get("private") or job.get("user_id") != 1:
        return False
    if job.get("listing_status") == "expired" and not include_closed:
        return False
    if job.get("source") == "Personal" or job.get("category") in scraper.PERSONAL_CATEGORIES:
        return False
    if job.get("source") in PUBLIC_EXTRA_SOURCES:
        return True
    source = scraper.SOURCE_BY_NAME.get(job.get("source") or "")
    return bool(source) and source.get("public_pages", True) is True


def public_jobs():
    return [job for job in db.list_jobs(1) if is_public(job)]


def finnish_free(job):
    return jobmeta.finnish_not_required(job)


def job_path(job):
    return f"/job/{job['id']}-{slugify(job.get('title'))[:60] or 'job'}"


# ---------------------------------------------------------------- landing paths <-> filters

def filters_for_path(path):
    """The search filters for a /jobs/... path, or None when the path names something that doesn't exist."""
    f = search.parse_filters("")
    f["field"] = []
    parts = [p for p in path.split("/")[2:] if p]
    s = slugs()
    i = 0
    while i < len(parts):
        part = parts[i]
        if part == "summer":
            f["type"] = sorted(set(f["type"]) | {"summer"})
        elif part == "no-finnish":
            f["no_finnish"] = True
        elif part == "remote":
            f["mode"] = ["remote"]
        elif part in ("field", "level", "type", "town", "region") and i + 1 < len(parts):
            value = getattr(s, part).get(parts[i + 1])
            if not value:
                return None
            key = {"town": "municipality"}.get(part, part)
            if key in ("field", "level", "type"):
                f[key] = sorted(set(f[key]) | {value})
            else:
                f[key] = value
            i += 1
        else:
            return None
        i += 1
    return f


def path_for(f):
    """The canonical landing path for filters (field, level, type, place, then the flags)."""
    s = slugs()
    parts = ["/jobs"]
    for value in f.get("field") or []:
        parts += ["field", value.replace("_", "-")]
    for value in f.get("level") or []:
        parts += ["level", value]
    for value in f.get("type") or []:
        if value != "summer":
            parts += ["type", value.replace("_", "-")]
    if f.get("municipality"):
        parts += ["town", s.town_slug[f["municipality"]]]
    elif f.get("region"):
        parts += ["region", s.region_slug[f["region"]]]
    if "summer" in (f.get("type") or []):
        parts.append("summer")
    if f.get("mode") == ["remote"]:
        parts.append("remote")
    if f.get("no_finnish"):
        parts.append("no-finnish")
    return "/".join(parts)


def describe(f):
    """(h1, title, one-sentence description) for a landing page."""
    places = core_places.load()
    noun = "Jobs"
    if f["level"]:
        noun = LEVEL_NOUN[f["level"][0]]
    elif f["type"]:
        noun = TYPE_NOUN[f["type"][0]]
    if f["mode"] == ["remote"]:
        noun = f"Remote {noun[0].lower()}{noun[1:]}"
    place = places.name(f["municipality"]) if f["municipality"] else (
        places.name(f["region"], "en") if f["region"] else "Finland")
    field = scraper.TAXONOMY.name(f["field"][0]) if f["field"] else ""
    h1 = f"{field}: {noun[0].lower()}{noun[1:]} in {place}" if field else f"{noun} in {place}"
    if f["no_finnish"]:
        h1 += " where Finnish isn't required"
    title = f"{h1} · JobDesk"
    description = (f"Open {noun.lower()} in {place}" + (f" in {field.lower()}" if field else "")
                   + (", where Finnish isn't required" if f["no_finnish"] else "")
                   + ", for students, graduates and early-career people. Updated twice a day; every ad links to the original.")
    return h1, title, description


# ---------------------------------------------------------------- HTML

def _date(iso):
    try:
        d = date.fromisoformat((iso or "")[:10])
    except ValueError:
        return ""
    return f"{d.day}.{d.month}.{d.year}"


def _salary(job):
    if job.get("salary_min") is None:
        return ""
    fmt = lambda n: f"{n:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
    low, high = job["salary_min"], job.get("salary_max") or job["salary_min"]
    amount = f"€{fmt(low)}" + (f"–{fmt(high)}" if high != low else "")
    return f"{amount} {LABEL['period'].get(job.get('salary_period'), '')}".strip()


def _tags(job):
    tags = db.tags_of(job)
    out = [LABEL["type"][t] for t in tags["employment_types"] if t == "summer"]
    out += [LABEL["level"][t] for t in tags["levels"]]
    out += [LABEL["type"][t] for t in tags["employment_types"] if t != "summer"]
    if job.get("work_mode"):
        out.append(LABEL["mode"][job["work_mode"]])
    level = job.get("lang_fi") or "unclear"
    out.append("No Finnish mentioned (English ad)" if level == "unclear" and finnish_free(job) else LABEL["finnish"][level])
    if _salary(job):
        out.append(_salary(job))
    return out


def _place(job):
    places = core_places.load()
    return places.name(job.get("municipality_code") or "") or job.get("location") or (
        "Remote" if job.get("work_mode") == "remote" else "")


def card(job):
    meta = " · ".join(escape(x) for x in [job.get("company") or "", _place(job),
                                           f"closes {_date(job['deadline'])}" if job.get("deadline") else ""] if x)
    tags = "".join(f'<span class="tag">{escape(t)}</span>' for t in _tags(job))
    return (f'<article class="job-card public-card"><div class="job-main">'
            f'<h3><a href="{job_path(job)}">{escape(job["title"])}</a></h3>'
            f'<p class="job-meta muted">{meta}</p><p class="job-tags">{tags}</p></div></article>')


def layout(title, description, body, canonical, robots=INDEX, extra_head=""):
    url = config.PUBLIC_URL.rstrip("/") + canonical
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{escape(title)}</title>
  <meta name="description" content="{escape(description)}">
  <meta name="robots" content="{robots}">
  <link rel="canonical" href="{escape(url)}">
  <meta property="og:title" content="{escape(title)}">
  <meta property="og:description" content="{escape(description)}">
  <meta property="og:url" content="{escape(url)}">
  <meta name="theme-color" content="#FBF7EF" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#12110D" media="(prefers-color-scheme: dark)">
  <link rel="icon" href="/static/favicon.svg" sizes="any" type="image/svg+xml">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Instrument+Sans:ital,wght@0,400;0,500;0,600;1,400&family=Instrument+Serif:ital@0;1&display=swap">
  <link rel="stylesheet" href="/static/style.css">{extra_head}
</head>
<body class="public-page">
  <a class="skip-link" href="#page">Skip to content</a>
  <header class="top">
    <a class="brand" href="/jobs" aria-label="JobDesk: find jobs">
      <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true"><rect width="34" height="34" rx="10" fill="#2340D8"/><circle cx="17" cy="17" r="8" fill="#FFE28A"/></svg>
      <span>jobdesk</span>
    </a>
    <nav class="public-nav" aria-label="Main">
      <a href="/jobs">Find jobs</a><a href="/jobs/summer">Summer jobs</a><a href="/jobs/no-finnish">Finnish not required</a>
      <a href="/employers.html">For employers</a>
    </nav>
    <div class="top-actions"><a class="btn secondary small" href="/#/jobs">Sign in</a></div>
  </header>
  <main id="page" tabindex="-1" class="public-main">
{body}
  </main>
  <footer class="public-footer muted small">
    <p>JobDesk lists open jobs, internships, summer jobs and thesis positions in Finland from public job feeds
      (Valtiolle, Kuntarekry and others) and from employers. Every ad links to the original; apply there.</p>
    <p><a href="/jobs">All jobs</a> · <a href="/employers.html">Post a job</a> · <a href="/#/jobs">Sign in to save jobs and track applications</a></p>
  </footer>
</body>
</html>
"""


def _ad_slot(name):
    """A reserved place for an advert (AdSense is not switched on; JOBDESK_AD_SLOTS=1 shows the space)."""
    return f'<aside class="ad-slot" data-ad-slot="{name}" aria-label="Advertisement"></aside>' if config.AD_SLOTS else ""


def _links(title, items):
    if not items:
        return ""
    lis = "".join(f'<li><a href="{escape(href)}">{escape(text)}</a> <span class="muted">{n}</span></li>'
                  for text, href, n in items)
    return f'<section class="public-links"><h2>{escape(title)}</h2><ul>{lis}</ul></section>'


def landing(path, query=""):
    """(status, html, robots) for /jobs and its landing paths; status 404 when the path is unknown."""
    f = filters_for_path(path)
    if f is None:
        return 404, layout("Page not found · JobDesk", "", '<h1>Page not found</h1><p><a href="/jobs">See all open jobs</a></p>',
                           "/jobs", NOINDEX), NOINDEX
    asked = search.parse_filters(query)
    f["q"], f["page"], f["sort"] = asked["q"], asked["page"], asked["sort"]
    results, facets = search.run(public_jobs(), f, finnish_free)
    shown, page, pages = search.page_of(results, f["page"], PAGE_SIZE)
    h1, title, description = describe(f)
    canonical = path_for(f) + (f"?page={page}" if page > 1 else "")
    robots = INDEX if results and not f["q"] and f["sort"] == "newest" else NOINDEX
    places = core_places.load()

    # Our own words about what is listed (not only the ads themselves)
    total = len(results)
    towns = sorted(facets["municipality"].items(), key=lambda kv: -kv[1])
    summary = [f"{total} open {('ad' if total == 1 else 'ads')}."]
    if towns:
        summary.append("Most are in " + ", ".join(places.name(c) for c, _ in towns[:3]) + ".")
    if total and not f["no_finnish"]:
        summary.append(f"{facets['no_finnish']} of them can be applied to without Finnish.")
    if facets["summer"] and "summer" not in f["type"]:
        summary.append(f"{facets['summer']} are summer jobs.")

    def nearby(values, make):
        items = []
        for value, n in sorted(values.items(), key=lambda kv: -kv[1]):
            g = dict(f, page=1, q="")
            g = make(g, value)
            if g is not None and path_for(g) != path_for(f):
                items.append((value, path_for(g), n))
        return items[:10]

    town_links = [(places.name(c), p, n) for c, p, n in nearby(
        facets["municipality"], lambda g, c: {**g, "municipality": c, "region": ""})]
    field_links = [(scraper.TAXONOMY.name(x), p, n) for x, p, n in nearby(facets["field"], lambda g, x: {**g, "field": [x]})]
    level_links = [(LEVEL_NOUN[x], p, n) for x, p, n in nearby(facets["level"], lambda g, x: {**g, "level": [x]})]
    quick = []
    if "summer" not in f["type"] and facets["summer"]:
        quick.append(("Summer jobs", path_for({**f, "type": sorted(set(f["type"]) | {"summer"})}), facets["summer"]))
    if not f["no_finnish"] and facets["no_finnish"]:
        quick.append(("Finnish not required", path_for({**f, "no_finnish": True}), facets["no_finnish"]))

    search_form = (f'<form class="discover-search" role="search" action="{escape(path_for(f))}" method="get">'
                   f'<input type="search" name="q" value="{escape(f["q"])}" aria-label="Search these jobs" '
                   f'placeholder="Job title, skill or employer, in English or Finnish">'
                   f'<button type="submit">Search</button></form>')
    cards = [card(job) for job in shown]
    if len(cards) > 5:
        cards.insert(5, _ad_slot("results"))
    listing = ('<div class="job-list">' + "".join(cards) + "</div>") if shown else (
        '<div class="empty-state"><p class="empty-title">No open ads here right now</p>'
        '<p><a href="/jobs">See all open jobs</a>, or sign in to get new ads as they come.</p></div>')
    pager = ""
    if pages > 1:
        def page_link(n):
            params = {k: v for k, v in (("q", f["q"]), ("page", n if n > 1 else "")) if v}
            return escape(path_for(f) + (f"?{urlencode(params)}" if params else ""))
        prev_link = f'<a class="btn secondary small" rel="prev" href="{page_link(page - 1)}">Previous</a>' if page > 1 else ""
        next_link = f'<a class="btn secondary small" rel="next" href="{page_link(page + 1)}">Next</a>' if page < pages else ""
        pager = f'<nav class="row pager" aria-label="Pages">{prev_link}<span class="muted small">Page {page} of {pages}</span>{next_link}</nav>'
    body = (f'<p class="eyebrow">Open jobs in Finland</p><h1>{escape(h1)}</h1>'
            f'<p class="muted lede">{escape(" ".join(summary))}</p>{search_form}'
            + (f'<p class="row chip-row">' + "".join(
                f'<a class="chip" href="{escape(href)}">{escape(text)} <span class="toggle-count">{n}</span></a>'
                for text, href, n in quick) + "</p>" if quick else "")
            + listing + pager
            + '<div class="public-related">'
            + _links("By town", town_links) + _links("By field", field_links) + _links("By level", level_links)
            + "</div>")
    return 200, layout(title, description, body, canonical, robots), robots


def _json_ld(job):
    places = core_places.load()
    tags = db.tags_of(job)
    data = {
        "@context": "https://schema.org/", "@type": "JobPosting",
        "title": job["title"],
        "description": escape(_description(job)[0]).replace("\n", "<br>"),
        "datePosted": (job.get("posted") or job.get("first_seen") or "")[:10],
        "hiringOrganization": {"@type": "Organization", "name": job.get("company") or "Not named in the ad"},
        "directApply": False,
    }
    if job.get("deadline"):
        data["validThrough"] = f"{job['deadline'][:10]}T23:59:59+02:00"
    types = list(dict.fromkeys(SCHEMA_TYPE[t] for t in tags["employment_types"] if t in SCHEMA_TYPE))
    if "internship" in tags["levels"] or "thesis" in tags["levels"]:
        types.insert(0, "INTERN")
    if types:
        data["employmentType"] = types if len(types) > 1 else types[0]
    if job.get("municipality_code"):
        data["jobLocation"] = {"@type": "Place", "address": {
            "@type": "PostalAddress", "addressLocality": places.name(job["municipality_code"]),
            "addressRegion": places.name(job.get("region_code") or "", "fi"), "addressCountry": "FI"}}
    if job.get("work_mode") == "remote":
        data["jobLocationType"] = "TELECOMMUTE"
        data["applicantLocationRequirements"] = {"@type": "Country", "name": "Finland"}
    if job.get("salary_min") is not None and job.get("salary_period") in SCHEMA_PERIOD:
        value = {"@type": "QuantitativeValue", "unitText": SCHEMA_PERIOD[job["salary_period"]]}
        if job.get("salary_max") and job["salary_max"] != job["salary_min"]:
            value.update(minValue=job["salary_min"], maxValue=job["salary_max"])
        else:
            value["value"] = job["salary_min"]
        data["baseSalary"] = {"@type": "MonetaryAmount", "currency": "EUR", "value": value}
    # "</" can't appear inside a script element; JSON allows the escaped form
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _description(job):
    """(text shown, is_excerpt). Feed ads are excerpted (the original is one click away); employer ads are theirs."""
    text = (job.get("ad_text") or "").strip()
    if job.get("source") in PUBLIC_EXTRA_SOURCES or len(text) <= EXCERPT_CHARS:
        return text, False
    cut = text[:EXCERPT_CHARS].rsplit(" ", 1)[0]
    return cut + " …", True


def job_page(job_id):
    """(status, html, robots) for /job/<id>-<slug>."""
    job = db.get_job(job_id)
    if not job or not is_public(job, include_closed=True):
        return 404, layout("Job not found · JobDesk", "", '<h1>This job isn\'t listed</h1><p><a href="/jobs">See all open jobs</a></p>',
                           "/jobs", NOINDEX), NOINDEX
    closed = job.get("listing_status") == "expired"
    places = core_places.load()
    tags = db.tags_of(job)
    text, excerpt = _description(job)
    source = scraper.SOURCE_BY_NAME.get(job.get("source") or "") or {}
    attribution = source.get("attribution", "")
    rows = [("Employer", job.get("company") or ""), ("Where", _place(job) + (
                f", {places.name(job.get('region_code') or '', 'en')}" if job.get("region_code") else "")),
            ("Apply by", _date(job.get("deadline"))),
            ("Starts", "As soon as possible" if job.get("start_date") == "asap" else _date(job.get("start_date"))),
            ("Pay", _salary(job)), ("Collective agreement", job.get("tes") or ""),
            ("Finnish", LABEL["finnish"][job.get("lang_fi") or "unclear"]),
            ("Work permit", ", ".join(LABEL["permit"][p] for p in tags["permits"])),
            ("Study credits", f"{job['internship_credits']} op / ECTS" if job.get("internship_credits") else ""),
            ("For students", "Can be done alongside studies" if job.get("combinable_with_studies") else "")]
    details = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in rows if v)
    apply = (f'<a class="btn" href="{escape(job["url"])}" rel="noopener nofollow" target="_blank">Open the original ad</a>'
             if job.get("url") else "")
    crumbs = []
    for fid in (scraper.stored_fields(job) or [])[:1]:
        crumbs.append((scraper.TAXONOMY.name(fid), path_for({"field": [fid]})))
    if job.get("municipality_code"):
        crumbs.append((places.name(job["municipality_code"]), path_for({"municipality": job["municipality_code"]})))
    crumb_html = " › ".join(f'<a href="{escape(h)}">{escape(t)}</a>' for t, h in [("Jobs", "/jobs")] + crumbs)
    paragraphs = "".join(f"<p>{escape(p)}</p>" for p in text.split("\n") if p.strip())
    body = (f'<nav class="muted small" aria-label="Breadcrumb">{crumb_html}</nav>'
            + ('<p class="msg err" role="status">This ad has closed. <a href="/jobs">See open jobs</a>.</p>' if closed else "")
            + f'<h1>{escape(job["title"])}</h1>'
            f'<p class="job-tags">{"".join(f"<span class=tag>{escape(t)}</span>" for t in _tags(job))}</p>'
            f'<div class="public-job"><dl class="public-details">{details}</dl>'
            f'<div class="row">{apply}<a class="btn secondary" href="/#/jobs">Sign in to save it</a></div></div>'
            f'<section class="public-ad"><h2>About the job</h2>{paragraphs or "<p class=muted>The ad text is on the original page.</p>"}'
            + (f'<p class="muted small">This is the start of the ad. Read all of it, and apply, on the original page.</p>' if excerpt else "")
            + f'</section>{_ad_slot("job")}'
            f'<p class="muted small">From {escape("the employer" if job.get("source") == "Employer" else job.get("source") or "")}'
            + (f' {escape(attribution)}' if attribution else "") + "</p>")
    robots = NOINDEX if closed else INDEX
    head = "" if closed else f'\n  <script type="application/ld+json">{_json_ld(job)}</script>'
    description = " · ".join(x for x in [job.get("company") or "", _place(job), ", ".join(_tags(job)[:3])] if x)
    return 200, layout(f"{job['title']} · {job.get('company') or 'JobDesk'}", description, body, job_path(job),
                       robots, head), robots


# ---------------------------------------------------------------- crawlers

def sitemap_urls():
    """Landing pages with open ads (combinations need a few) and every open public job."""
    jobs = public_jobs()
    base = config.PUBLIC_URL.rstrip("/")
    results, facets = search.run(jobs, {**search.parse_filters(""), "field": []}, finnish_free)
    today = date.today().isoformat()
    urls = [("/jobs", today)]
    if facets["summer"]:
        urls.append(("/jobs/summer", today))
    if facets["no_finnish"]:
        urls.append(("/jobs/no-finnish", today))
    for group, key, make in (("field", "field", lambda v: {"field": [v]}), ("level", "level", lambda v: {"level": [v]}),
                             ("municipality", "municipality", lambda v: {"municipality": v}),
                             ("region", "region", lambda v: {"region": v})):
        for value, n in facets[group].items():
            urls.append((path_for(make(value)), today))
    # field x town and summer x town when they hold a few ads
    pairs = {}
    for job in results:
        town = job.get("municipality_code")
        if not town:
            continue
        for fid in scraper.stored_fields(job) or []:
            pairs[("field", fid, town)] = pairs.get(("field", fid, town), 0) + 1
        if "summer" in db.tags_of(job)["employment_types"]:
            pairs[("summer", "", town)] = pairs.get(("summer", "", town), 0) + 1
    for (kind, fid, town), n in sorted(pairs.items()):
        if n >= 3:
            urls.append((path_for({"field": [fid], "municipality": town} if kind == "field"
                                  else {"type": ["summer"], "municipality": town}), today))
    urls += [(job_path(job), (job.get("last_seen") or today)[:10]) for job in results]
    return [(base + path, lastmod) for path, lastmod in dict.fromkeys(urls)]


def sitemap_xml():
    entries = "".join(f"<url><loc>{escape(loc)}</loc><lastmod>{lastmod}</lastmod></url>" for loc, lastmod in sitemap_urls())
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + entries + "</urlset>\n")


def robots_txt():
    base = config.PUBLIC_URL.rstrip("/")
    return ("User-agent: *\nAllow: /jobs\nAllow: /job/\nAllow: /employers.html\nAllow: /static/\n"
            "Disallow: /api/\nDisallow: /\n"
            f"\nSitemap: {base}/sitemap.xml\n")
