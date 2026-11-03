"""What to study: the skills that the job ads ask for, compared with the member's own CVs.

Jobs are grouped into role types by title (Finnish and English). For each role type, every skill in
SKILLS is looked for in the ads (title + saved ad text) and in the member's CVs. Skills that the ads
ask for but no CV mentions are the ones to study next. This is transparent keyword matching, not an
AI judgement: each skill shows how many ads mention it, and the patterns are listed below.

A CV draft for a role type starts from the member's closest CV. Skills still to learn go on a
"Want to learn" row (the same convention as the original role CVs), never as skills already held.
"""

import re

import match
import scraper

# (id, English label, Finnish label, group, pattern matched in Finnish and English text, study hint)
_SKILLS = [
    ("gis", "GIS / spatial data", "Paikkatieto", "GIS & data",
     r"\bgis\b|paikkatie|geospatial|geoinformat|spatial data", "Practise with free QGIS and open map data."),
    ("qgis", "QGIS", "QGIS", "GIS & data", r"\bqgis", "Free to install; National Land Survey open data works well."),
    ("arcgis", "ArcGIS", "ArcGIS", "GIS & data", r"arcgis|\besri\b", "Student licences are often available."),
    ("remote_sensing", "Remote sensing / laser scanning", "Kaukokartoitus ja laserkeilaus", "GIS & data",
     r"kaukokartoit|remote sensing|laserkeil|lidar|satelliitti|satellite imag", ""),
    ("drones", "Drones (UAV)", "Droonit", "GIS & data", r"drooni|\bdrones?\b|\buav\b|lennokki|kauko-ohjattav\w* ilma",
     "Drone flying needs Traficom's operator registration and an online test."),
    ("python", "Python", "Python", "GIS & data", r"\bpython", ""),
    ("r_lang", "R", "R", "GIS & data", r"\br-(?:kiel|ohjelm)|\br (?:language|programming)|\brstudio|\bin r\b", ""),
    ("sql", "Databases / SQL", "Tietokannat / SQL", "GIS & data", r"\bsql\b|tietokan|database", ""),
    ("excel", "Excel / spreadsheets", "Excel / taulukkolaskenta", "GIS & data",
     r"\bexcel|taulukkolaskent|spreadsheet", ""),
    ("statistics", "Statistics / data analysis", "Tilastot ja data-analyysi", "GIS & data",
     r"tilastoll|tilastotiet|statistic|data-analy|data analy|analytiikka", ""),
    ("inventory", "Forest inventory & measurement", "Metsien inventointi ja mittaus", "Forest knowledge",
     r"inventoin|forest inventory|koeala|sample plot|puustotun|tree measurement|relaskoop|mittaustyö|field measurement", ""),
    ("planning", "Forest management planning", "Metsäsuunnittelu", "Forest knowledge",
     r"metsäsuunnit|metsänhoitosuunnit|forest (?:management )?plan", ""),
    ("silviculture", "Silviculture", "Metsänhoito", "Forest knowledge",
     r"metsänhoi|silvicult|taimikonhoi|metsänuudist|forest regeneration|ensiharvennu", ""),
    ("timber_trade", "Timber trade / wood procurement", "Puukauppa ja puunhankinta", "Forest knowledge",
     r"puukaup|puunhank|timber trade|wood procurement|wood sourcing|leimik|virkesköp|virkesinköp", ""),
    ("harvesting", "Harvesting & timber logistics", "Puunkorjuu ja logistiikka", "Forest knowledge",
     r"puunkorju|korjuun|harvesting|puutavaralogist|timber logistic|kuljetusten ohjau", ""),
    ("certification", "Forest certification (PEFC/FSC)", "Metsäsertifiointi (PEFC/FSC)", "Forest knowledge",
     r"\bpefc|\bfsc\b|metsäsertifi|forest certif", ""),
    ("biodiversity", "Biodiversity & nature surveys", "Luontoselvitykset ja monimuotoisuus", "Forest knowledge",
     r"luontoselvit|luontokartoit|monimuotoisuu|biodiversit|nature survey|habitat|luontotyyp|lajintunt|species identif", ""),
    ("ecology", "Forest ecology & soils", "Metsäekologia ja maaperä", "Forest knowledge",
     r"metsäekolog|forest ecolog|ecosystem|ekosystee|maaperä|\bsoils?\b", ""),
    ("carbon", "Climate & carbon", "Ilmasto ja hiili", "Forest knowledge",
     r"hiilinielu|hiilivarast|hiilijalanjälj|carbon|ilmastonmuut|climate change", ""),
    ("legislation", "Forest & environmental law", "Metsä- ja ympäristölainsäädäntö", "Forest knowledge",
     r"metsälak|luonnonsuojelulak|forest act|ympäristölainsää|environmental (?:law|legislation)|\bkemera|\bmetka\b", ""),
    ("esg", "Sustainability reporting (ESG)", "Vastuullisuusraportointi (ESG)", "Forest knowledge",
     r"\besg\b|\bcsrd\b|vastuullisuusrapor|sustainability report", ""),
    ("forest_owners", "Working with forest owners", "Metsänomistajien palvelu", "People & work",
     r"metsänomistaj|forest owner", ""),
    ("customer", "Customer service & sales", "Asiakaspalvelu ja myynti", "People & work",
     r"asiakaspalvel|customer service|\bmyyn|\bsales\b", ""),
    ("project", "Project management", "Projektinhallinta", "People & work",
     r"projektinhallin|project manag|projektien johta", ""),
    ("occupational_safety", "Occupational safety card", "Työturvallisuuskortti", "Cards & licences",
     r"työturvallisuuskort|occupational safety card", "A one-day course."),
    ("forest_machine", "Forest machines", "Metsäkoneet", "Cards & licences",
     r"metsäkone|forest machine|harvester|kuormatraktor|forwarder", ""),
    ("swedish", "Swedish", "Ruotsi", "Languages", r"ruotsi|swedish|svenska", ""),
    ("english", "English", "Englanti", "Languages", r"englan|\benglish\b", ""),
]

# Blockers already used on the Jobs page (licences, cards, Finnish) are skills too.
# Years of experience can't be studied, so it is left out.
_FROM_BLOCKERS = {
    "B licence": ("b_licence", "B driving licence", "B-ajokortti", "Cards & licences", ""),
    "C licence": ("c_licence", "C driving licence", "C-ajokortti", "Cards & licences", ""),
    "fluent Finnish": ("finnish", "Fluent Finnish", "Sujuva suomi", "Languages",
                       "The YKI test documents your level."),
    "first aid card": ("first_aid", "First aid card (EA1)", "Ensiapukortti (EA1)", "Cards & licences",
                       "A two-day EA1 course."),
    "chainsaw": ("chainsaw", "Chainsaw", "Moottorisaha", "Cards & licences", ""),
    "brush saw experience": ("brush_saw", "Brush saw", "Raivaussaha", "Cards & licences", ""),
    "forest machine operator qualification": ("forest_machine_operator", "Forest machine operator qualification",
                                              "Metsäkoneenkuljettajan tutkinto", "Cards & licences", ""),
    "forestry degree": ("forestry_degree", "Forestry degree", "Metsäalan tutkinto", "Education", ""),
    "vocational qualification": ("vocational", "Vocational qualification", "Ammatillinen tutkinto", "Education", ""),
    "welding": ("welding", "Welding", "Hitsaus", "Cards & licences", ""),
    "welding certificate": ("welding_certificate", "Welding certificate", "Hitsauspätevyys", "Cards & licences", ""),
    "hot-work card": ("hot_work", "Hot-work card", "Tulityökortti", "Cards & licences", "A one-day course."),
    "forklift card": ("forklift", "Forklift card", "Trukkikortti", "Cards & licences", ""),
    "reading drawings": ("drawings", "Reading drawings", "Piirustusten lukeminen", "People & work", ""),
    "electrician qualification": ("electrician", "Electrician qualification", "Sähköalan pätevyys", "Education", ""),
    "electrical safety card": ("electrical_safety", "Electrical safety card", "Sähkötyöturvallisuuskortti",
                               "Cards & licences", "A one-day course."),
}

SKILLS = [dict(zip(("id", "en", "fi", "group", "pattern", "hint"), s)) for s in _SKILLS] + [
    dict(zip(("id", "en", "fi", "group", "hint"), _FROM_BLOCKERS[label]), pattern=pattern)
    for label, _fact, pattern in match.BLOCKERS if label in _FROM_BLOCKERS
]
for _skill in SKILLS:
    _skill["regex"] = re.compile(_skill["pattern"], re.I)

# Role types by job title, first match wins. Finnish and English stems.
ROLE_TYPES = [
    ("forest_specialist", "Forest specialist", "Metsäasiantuntija",
     r"metsäasiantunt|metsäneuvo|metsänhoitaj|metsätalousinsin|metsäsuunnittelij|forestry professional|"
     r"forest specialist|forest officer|\bforester\b|metsävastaav|metsäpalvel|forest service"),
    ("procurement", "Wood procurement & timber trade", "Puunhankinta ja puukauppa",
     r"puunhank|puukaup|wood procurement|timber trade|wood buyer|virkesköp|sourcing|hankinta"),
    ("harvesting", "Harvesting & logistics", "Korjuu ja logistiikka",
     r"korjuu|logist|kuljetu|harvest|terminaal|terminal|transport"),
    ("research", "Research", "Tutkimus",
     r"tutki|research|doctoral|väitöskirja|professor|post-?doc|tohtori"),
    ("gis_data", "GIS & forest data", "Paikkatieto ja metsätieto",
     r"paikkatie|\bgis\b|geospatial|kaukokart|remote sensing|\bdata\b|metsävarat|kartoit|laserkeil|drone|drooni"),
    ("nature", "Nature & environment", "Luonto ja ympäristö",
     r"luonto|luonnon|nature|biolog|ympäristö|environment|monimuotois|ecolog|ekolog|biotoop"),
    ("teaching", "Teaching & advisory", "Opetus ja neuvonta",
     r"opettaja|ohjaaja|lehtori|teacher|instructor|kouluttaja"),
    ("field_work", "Forest & field work", "Metsä- ja maastotyö",
     r"metsuri|metsätyö|forest worker|metsäkone|taimi|istutu|raivaa|maasto|field work|ulkoalue"),
]
ROLE_TYPES = [{"id": i, "en": en, "fi": fi, "regex": re.compile(p, re.I)} for i, en, fi, p in ROLE_TYPES]
OTHER = {"id": "other", "en": "Other forestry roles", "fi": "Muut metsäalan tehtävät"}
INTERNSHIP = re.compile(r"harjoittel|kesätyö|kesäty|intern|trainee|summer job|summer employee|kesä 20", re.I)

MIN_JOBS = 2          # a skill must appear in at least this many of a role type's ads to be suggested
STUDY_LIMIT = 8       # suggestions shown per role type


def role_type(job):
    """The role type for one job: personal (non-forestry) jobs keep their category."""
    if job.get("personal"):
        category = job.get("category") or "Other"
        return {"id": "personal-" + re.sub(r"\W+", "-", category.lower()), "en": category, "fi": category}
    title = job.get("title") or ""
    return next((rt for rt in ROLE_TYPES if rt["regex"].search(title)), OTHER)


def skills_in(text):
    """Ids of the skills mentioned in a text."""
    return {skill["id"] for skill in SKILLS if skill["regex"].search(text or "")}


LEARN_ROW = re.compile(r"^\s*(?:haluan oppia|want to learn)\s*:.*$", re.I | re.M)


def cv_text(cv):
    """A CV's text without its "Want to learn" rows: wanting a skill is not having it."""
    content = cv.get("content") or {}
    return LEARN_ROW.sub(" ", " ".join([cv.get("title") or ""] + [str(v) for v in content.values()]))


def _title_stems(text):
    return {match.stem(w) for w in match.tokens(text) if len(w) > 3 and w not in match.STOPWORDS}


def analyse(jobs, cvs):
    """Role types with the skills their ads ask for, split into have / study next."""
    have_any = set()
    cv_skills = {}
    for cv in cvs:
        cv_skills[cv["id"]] = skills_in(cv_text(cv))
        have_any |= cv_skills[cv["id"]]
    by_id = {skill["id"]: skill for skill in SKILLS}
    groups = {}
    for job in jobs:
        rt = role_type(job)
        group = groups.setdefault(rt["id"], {"id": rt["id"], "label": rt["en"], "label_fi": rt["fi"],
                                             "personal": rt["id"].startswith("personal-"),
                                             "jobs": 0, "with_ad_text": 0, "internships": 0,
                                             "counts": {}, "examples": [], "title_words": {}})
        group["jobs"] += 1
        group["with_ad_text"] += bool(job.get("ad_text"))
        group["internships"] += bool(INTERNSHIP.search(job.get("title") or ""))
        for word in _title_stems(job.get("title")):
            group["title_words"][word] = group["title_words"].get(word, 0) + 1
        if len(group["examples"]) < 3:
            group["examples"].append({"id": job.get("id"), "title": job.get("title"), "url": job.get("url") or ""})
        for skill_id in skills_in(" ".join([job.get("title") or "", job.get("ad_text") or ""])):
            group["counts"][skill_id] = group["counts"].get(skill_id, 0) + 1

    result = []
    for group in groups.values():
        asked = sorted(group.pop("counts").items(), key=lambda item: (-item[1], by_id[item[0]]["en"]))

        def row(skill_id, n):
            skill = by_id[skill_id]
            return {"id": skill_id, "label": skill["en"], "label_fi": skill["fi"], "group": skill["group"],
                    "hint": skill["hint"], "jobs": n, "percent": round(100 * n / group["jobs"])}

        group["study"] = [row(s, n) for s, n in asked if s not in have_any and n >= MIN_JOBS][:STUDY_LIMIT]
        group["have"] = [row(s, n) for s, n in asked if s in have_any]
        title_words = group.pop("title_words")
        wanted = {s for s, _ in asked}

        def closeness(cv):
            """Shared skills, then words shared by the CV's title/target role and the job titles,
            then (for forestry roles) a CV aimed at forestry. Highest wins."""
            content = cv.get("content") or {}
            heading = f"{cv.get('title') or ''} {content.get('target_role') or ''}"
            return (len(cv_skills[cv["id"]] & wanted),
                    sum(title_words.get(word, 0) for word in _title_stems(heading)),
                    not group["personal"] and scraper.is_forestry_related({"title": heading}),
                    -cv["id"])
        best = max(cvs, key=closeness, default=None)
        group["closest_cv"] = {"id": best["id"], "title": best["title"]} if best else None
        result.append(group)
    result.sort(key=lambda g: (g["personal"], -g["jobs"], g["label"]))
    return {"role_types": result, "cv_count": len(cvs), "total_jobs": len(jobs),
            "jobs_with_ad_text": sum(1 for job in jobs if job.get("ad_text"))}


def draft_cv(role, cvs, study, language=None):
    """An unsaved CV for a role type: the closest CV's content, the role as target, and the skills
    still to learn on a "Want to learn" row. study is the role type's study list from analyse()."""
    base = role.get("closest_cv") and next((cv for cv in cvs if cv["id"] == role["closest_cv"]["id"]), None)
    language = language or (base["language"] if base else "en")
    content = dict(base["content"]) if base else {}
    label = role["label_fi"] if language == "fi" else role["label"]
    content["target_role"] = label
    learn = ", ".join(s["label_fi"] if language == "fi" else s["label"] for s in study)
    if learn:
        row = f"{'Haluan oppia' if language == 'fi' else 'Want to learn'}: {learn}"
        lines = [line for line in (content.get("skills") or "").splitlines() if not LEARN_ROW.match(line)]
        content["skills"] = "\n".join(lines + [row]).strip()
    return {"title": f"{label} CV", "language": language, "content": content,
            "based_on": base["title"] if base else ""}
