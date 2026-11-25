"""Job search shared by Discover (GET /api/search, for members) and the public pages (public.py).

parse_filters(query_string)  the filters in an address (?q=nurse&level=internship&no_finnish=1&page=2);
                             unknown values are dropped, so an old or edited link still works
run(jobs, f, finnish_free)   (matching jobs sorted, facet counts); finnish_free(job) says whether a member
                             without Finnish can apply (the caller knows about AI Finnish checks)

Keywords match word starts in the title, employer, place and ad text (db.search_text, FTS5) and also the
roles named in the other language (core/taxonomy.py: "nurse" finds Sairaanhoitaja).
"""

from urllib.parse import parse_qs

import db
import scraper
from core import jobmeta
from core import places as core_places

SORTS = ("newest", "deadline")


def parse_filters(query_string):
    raw = parse_qs(query_string or "", keep_blank_values=False)
    one = lambda key: (raw.get(key) or [""])[0].strip()
    many = lambda key, allowed: [v for v in dict.fromkeys(",".join(raw.get(key) or []).split(",")) if v in allowed]
    places = core_places.load()
    try:
        page = max(1, min(int(one("page") or 1), 1000))
    except ValueError:
        page = 1
    return {
        "q": one("q")[:100],
        # None: no field in the address (Discover then uses the member's own fields); [] for field=all
        "field": None if "field" not in raw else ([] if one("field") == "all" else many("field", scraper.TAXONOMY.by_id)),
        "level": many("level", jobmeta.LEVELS),
        "type": many("type", jobmeta.EMPLOYMENT_TYPES),
        "mode": many("mode", jobmeta.WORK_MODES),
        "sector": many("sector", jobmeta.SECTORS),
        "region": one("region") if one("region") in places.region_by_code else "",
        "municipality": one("municipality") if one("municipality") in places.municipality_by_code else "",
        "no_finnish": one("no_finnish") == "1",
        "paid": one("paid") == "1",
        "with_studies": one("with_studies") == "1",
        "sort": one("sort") if one("sort") in SORTS else "newest",
        "page": page,
    }


def to_query(f):
    """The filters written one way (page left out), so the same search saved twice is recognised."""
    from urllib.parse import urlencode
    params = []
    if f.get("q"):
        params.append(("q", f["q"]))
    if f.get("field") is not None:
        params.append(("field", ",".join(f["field"]) if f["field"] else "all"))
    for key in ("level", "type", "mode", "sector"):
        if f.get(key):
            params.append((key, ",".join(sorted(f[key]))))
    for key in ("region", "municipality"):
        if f.get(key):
            params.append((key, f[key]))
    for key in ("no_finnish", "paid", "with_studies"):
        if f.get(key):
            params.append((key, "1"))
    if f.get("sort") and f["sort"] != "newest":
        params.append(("sort", f["sort"]))
    return urlencode(params)


def _matches(job, f, tags, finnish_free, text_ids, roles):
    if f["q"] and job["id"] not in text_ids and not scraper.TAXONOMY.title_matches_roles(job.get("title"), roles):
        return False
    if f["field"] and not set(f["field"]) & set(scraper.stored_fields(job) or []):
        return False
    for key, column in (("level", "levels"), ("type", "employment_types")):
        if f[key] and not set(f[key]) & set(tags[column]):
            return False
    if f["mode"] and job.get("work_mode") not in f["mode"]:
        return False
    if f["sector"] and job.get("employer_sector") not in f["sector"]:
        return False
    if f["municipality"] and job.get("municipality_code") != f["municipality"]:
        return False
    if f["region"] and job.get("region_code") != f["region"]:
        return False
    if f["no_finnish"] and not finnish_free:
        return False
    if f["paid"] and job.get("paid") != 1:
        return False
    if f["with_studies"] and job.get("combinable_with_studies") != 1:
        return False
    return True


def sort_key(sort):
    if sort == "deadline":      # soonest open deadline first; jobs without one at the end
        return lambda job: (not job.get("deadline"), job.get("deadline") or "", -job["id"])
    return lambda job: (job.get("posted") or job.get("first_seen") or "", job["id"])


def empty_facets():
    return {"level": {}, "type": {}, "mode": {}, "region": {}, "municipality": {}, "field": {},
            "no_finnish": 0, "summer": 0}


def run(jobs, f, finnish_free):
    """The jobs that pass f, sorted as f["sort"] asks, and counts of what they contain."""
    text_ids = (db.search_text(f["q"]) or set()) if f["q"] else set()
    roles = scraper.TAXONOMY.roles_for_query(f["q"]) if f["q"] else []
    results, facets = [], empty_facets()

    def count(group, value):
        facets[group][value] = facets[group].get(value, 0) + 1

    for job in jobs:
        tags = db.tags_of(job)
        free = finnish_free(job)
        if not _matches(job, f, tags, free, text_ids, roles):
            continue
        results.append(job)
        for value in tags["levels"]:
            count("level", value)
        for value in tags["employment_types"]:
            count("type", value)
        for group, column in (("mode", "work_mode"), ("region", "region_code"), ("municipality", "municipality_code")):
            if job.get(column):
                count(group, job[column])
        for value in scraper.stored_fields(job) or []:
            count("field", value)
        facets["no_finnish"] += bool(free)
        facets["summer"] += "summer" in tags["employment_types"]
    results.sort(key=sort_key(f["sort"]), reverse=f["sort"] == "newest")
    return results, facets


def page_of(results, page, size):
    """(the jobs on page, page number actually shown, number of pages)."""
    pages = max(1, -(-len(results) // size))
    page = min(max(1, page), pages)
    return results[(page - 1) * size: page * size], page, pages
