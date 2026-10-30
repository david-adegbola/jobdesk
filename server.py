#!/usr/bin/env python3
"""JobDesk: David's private job dashboard. Run from the repo root:

    python3 app/server.py            # opens http://localhost:8765
    python3 app/server.py --no-browser

Local only: it listens on 127.0.0.1, keeps its data in app/data/jobdesk.db (git-ignored),
and nothing it stores is ever pushed or published.
"""

import json
import re
import shutil
import subprocess
import sys
import threading
import uuid
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.dont_write_bytecode = True      # no __pycache__ folders in the repo
APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))

import db       # noqa: E402
import facts    # noqa: E402
import ics      # noqa: E402
import prompt   # noqa: E402
import match    # noqa: E402
import scraper  # noqa: E402

HOST, PORT = "127.0.0.1", 8765
STATIC = APP / "static"
USER_ID = 1     # single user for now; every db call takes user_id so this can become a login later

# Which job type a role belongs to (for manual jobs, when no type is chosen)
ROLE_TYPE = {**{v: k for k, v in scraper.CV_FOR_TYPE.items()},
             "assembly-worker": "Industrial", "steel-installer": "Industrial", "salesperson": "Sales"}

ROUTES = []


def route(method, pattern):
    def register(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn))
        return fn
    return register


# ---------------------------------------------------------------- helpers

def context():
    f, warning = facts.load()
    return f, warning, match.load_roles()


def job_text(job):
    # Title and ad only: company and place names would add noise ("Worker Oy", "Teollisuuskatu")
    return " ".join(job.get(k) or "" for k in ("title", "ad_text"))


def enrich(job, roles, f):
    text = job_text(job)
    scores = match.match(text, roles)
    blocker_text = " ".join(job.get(k) or "" for k in ("title", "ad_text"))
    best = scores[0] if scores else {"slug": "", "score": 0, "words": []}
    default_cv = scraper.CV_FOR_TYPE.get(job.get("category") or "", "")
    use_cv = job.get("app_cv_role") or (best["slug"] if best["score"] >= 20 or not default_cv else default_cv)
    days_left = None
    if job.get("deadline"):
        try:
            days_left = (date.fromisoformat(job["deadline"]) - date.today()).days
        except ValueError:
            pass
    return {**job, "is_new": bool(job.get("is_new")), "match": best, "blockers": match.blockers(blocker_text, f),
            "use_cv": use_cv, "use_cv_link": match.employer_link(use_cv) if use_cv else "",
            "days_left": days_left, "has_ad_text": bool(job.get("ad_text"))}


# ---------------------------------------------------------------- state and jobs

@route("GET", "/api/state")
def api_state(h, m):
    f, warning, roles = context()
    return {"facts": f, "facts_warning": warning, "roles": [{"slug": r["slug"], "title": r["title"]} for r in roles],
            "statuses": db.STATUSES, "job_types": list(scraper.JOB_TYPES) + ["Sales", "Other"],
            "latest_check": db.latest_check(USER_ID), "scrape": SCRAPE.copy()}


@route("GET", "/api/jobs")
def api_jobs(h, m):
    f, _, roles = context()
    return {"jobs": [enrich(j, roles, f) for j in db.list_jobs(USER_ID)], "latest_check": db.latest_check(USER_ID)}


@route("POST", "/api/jobs")
def api_add_job(h, m):
    body = h.json()
    url = (body.get("url") or "").strip()
    if not (body.get("title") or "").strip():
        return h.error(400, "A title is needed.")
    jid = scraper.jobly_id(url)
    if jid:
        source, external = "Jobly", jid
    elif url:
        source, external = "Manual", url
    else:
        source, external = "Manual", f"manual-{uuid.uuid4().hex[:12]}"
    fields = {**body, "url": url, "source": source, "external_id": external}
    if not fields.get("category"):
        f, _, roles = context()
        best = match.match(job_text(fields), roles)
        fields["category"] = ROLE_TYPE.get(best[0]["slug"], "Other") if best and best[0]["score"] else "Other"
    return {"id": db.add_manual(fields, USER_ID)}


@route("POST", r"/api/jobs/(\d+)/fetch")
def api_fetch_ad(h, m):
    job = db.get_job(int(m.group(1)), USER_ID)
    if not job or not job["url"]:
        return h.error(404, "This job has no link to read.")
    text = scraper.fetch_ad_text(job["url"])
    if not text:
        return h.error(502, "Couldn't read the ad page.")
    db.add_manual({**job, "ad_text": text}, USER_ID)
    return {"ok": True, "chars": len(text)}


@route("POST", r"/api/jobs/(\d+)/status")
def api_job_status(h, m):
    job_id = int(m.group(1))
    status = (h.json().get("status") or "").strip()
    f, _, roles = context()
    job = next((j for j in db.list_jobs(USER_ID) if j["id"] == job_id), None)
    if not job:
        return h.error(404, "No such job.")
    e = enrich(job, roles, f)
    contact = " ".join(x for x in (job["contact_name"], job["contact_phone"]) if x)
    try:
        app_id = db.set_status(job_id, status, {"cv_role": e["use_cv"], "employer_link": e["use_cv_link"],
                                                "contact": contact}, USER_ID)
    except ValueError as err:
        return h.error(400, str(err))
    return {"application_id": app_id}


# ---------------------------------------------------------------- tracker

FOLLOW_UP_DAYS = 5


def tracker_view(a):
    today = date.today()
    contact = a["contact"] or " ".join(x for x in (a["contact_name"], a["contact_phone"]) if x)
    overdue = bool(a["next_action_date"]) and a["next_action_date"] < today.isoformat() and a["status"] not in ("Rejected", "Offer")
    follow_up = None
    if a["status"] == "Applied":
        try:
            idle = (today - date.fromisoformat(a["status_changed_at"][:10])).days
        except ValueError:
            idle = 0
        if idle >= FOLLOW_UP_DAYS:
            follow_up = f"No news for {idle} days. Call {contact}" if contact else f"No news for {idle} days. Follow up."
    return {**a, "contact_display": contact, "overdue": overdue, "follow_up": follow_up}


@route("GET", "/api/applications")
def api_applications(h, m):
    return {"applications": [tracker_view(a) for a in db.list_applications(USER_ID)],
            "statuses": db.STATUSES}


@route("POST", r"/api/applications/(\d+)")
def api_update_application(h, m):
    try:
        db.update_application(int(m.group(1)), h.json(), USER_ID)
    except ValueError as err:
        return h.error(400, str(err))
    return {"ok": True}


@route("GET", "/api/calendar.ics")
def api_calendar(h, m):
    return (ics.build(db.list_applications(USER_ID)), "text/calendar; charset=utf-8",
            {"Content-Disposition": 'attachment; filename="jobdesk.ics"'})


# ---------------------------------------------------------------- CVs

REPO = APP.parent


def last_updated(slug):
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", f"roles/{slug}"], cwd=REPO,
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    if out:
        return out
    files = list((REPO / "roles" / slug).glob("*"))
    return date.fromtimestamp(max(f.stat().st_mtime for f in files)).isoformat() if files else ""


@route("GET", "/api/roles")
def api_roles(h, m):
    used = db.applications_per_role(USER_ID)
    out = []
    for r in match.load_roles():
        out.append({"slug": r["slug"], "title": r["title"], "langs": r["langs"], "pdfs": match.pdf_links(r),
                    "employer_link": match.employer_link(r["slug"]), "updated": last_updated(r["slug"]),
                    "applications": used.get(r["slug"], 0)})
    return {"roles": out, "pdflatex": bool(shutil.which("pdflatex"))}


@route("POST", "/api/build")
def api_build(h, m):
    if not shutil.which("pdflatex"):
        return {"ok": False, "message": "pdflatex isn't installed here. Push to GitHub to build the PDFs."}
    built, failed = [], []
    for tex in sorted((REPO / "roles").glob("*/cv-*.tex")):
        name = tex.stem
        ok = all(subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex.name],
                                cwd=tex.parent, capture_output=True, timeout=120).returncode == 0 for _ in range(2))
        (built if ok else failed).append(f"{tex.parent.name}/{name}")
    for d in sorted((REPO / "roles").glob("*/")):
        if (d / "cv-fi.pdf").exists() and (d / "cv-en.pdf").exists() and shutil.which("pdfunite"):
            subprocess.run(["sh", str(REPO / "shared" / "combine.sh"), str(d)], cwd=REPO, capture_output=True)
    msg = f"Built {len(built)} PDFs locally (in each roles/<role>/ folder; they are git-ignored)."
    if failed:
        msg += " Failed: " + ", ".join(failed) + ". Check the .log file next to each."
    return {"ok": not failed, "message": msg}


# ---------------------------------------------------------------- new CV prompt

def _prompt_job(h, m):
    if m.group(1):
        job = db.get_job(int(m.group(1)), USER_ID)
        if not job:
            raise KeyError(m.group(1))
        return job
    body = h.json() if h.command == "POST" else {}
    return body.get("job") or {}


@route("GET", r"/api/prompt/(\d+)")
def api_prompt_analyse(h, m):
    f, _, roles = context()
    return prompt.analyse(_prompt_job(h, m), roles, f)


@route("POST", r"/api/prompt(?:/(\d+))?")
def api_prompt_build(h, m):
    f, _, roles = context()
    body = h.json()
    job = db.get_job(int(m.group(1)), USER_ID) if m.group(1) else (body.get("job") or {})
    if m.group(1) and not job:
        raise KeyError(m.group(1))
    analysis = prompt.analyse(job, roles, f)
    if body.get("analyse_only"):
        return analysis
    text, missing = prompt.build(analysis, body.get("answers") or {})
    return {"prompt": text, "missing": missing, "analysis": analysis}


# ---------------------------------------------------------------- insights

@route("GET", "/api/insights")
def api_insights(h, m):
    f, _, roles = context()
    jobs = [enrich(j, roles, f) for j in db.list_jobs(USER_ID)]
    counts = {}
    for j in jobs:
        for b in j["blockers"]:
            counts[b] = counts.get(b, 0) + 1
    total = len(jobs)
    gaps = sorted(({"blocker": b, "jobs": n, "percent": round(100 * n / total) if total else 0}
                   for b, n in counts.items()), key=lambda x: -x["jobs"])
    with_text = sum(1 for j in jobs if j["has_ad_text"])
    return {"total_jobs": total, "jobs_with_ad_text": with_text, "skills_gap": gaps, "funnel": db.funnel(USER_ID)}


# ---------------------------------------------------------------- scraper (runs in the background)

SCRAPE = {"running": False, "message": "", "done": 0, "total": 0, "result": None}
SCRAPE_LOCK = threading.Lock()


def _scrape_thread():
    def progress(msg, done, total):
        SCRAPE.update(message=msg, done=done, total=total)
    try:
        SCRAPE["result"] = scraper.run(progress, user_id=USER_ID)
    finally:
        SCRAPE["running"] = False


@route("POST", "/api/scrape")
def api_scrape_start(h, m):
    with SCRAPE_LOCK:
        if not SCRAPE["running"]:
            SCRAPE.update(running=True, message="Starting…", done=0, total=0, result=None)
            threading.Thread(target=_scrape_thread, daemon=True).start()
    return SCRAPE.copy()


@route("GET", "/api/scrape")
def api_scrape_status(h, m):
    return SCRAPE.copy()


# ---------------------------------------------------------------- HTTP plumbing

class Handler(BaseHTTPRequestHandler):
    server_version = "JobDesk"

    def log_message(self, fmt, *args):     # quiet: only errors
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    def json(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def error(self, code, message):
        return (code, {"error": message})

    def send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self, method):
        path = urlparse(self.path).path
        for meth, pattern, fn in ROUTES:
            mt = pattern.match(path)
            if meth == method and mt:
                try:
                    result = fn(self, mt)
                except KeyError:
                    return self.send(404, {"error": "Not found."})
                if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], int):
                    return self.send(*result)
                if isinstance(result, tuple):       # (bytes, content-type, headers)
                    return self.send(200, result[0], result[1], result[2] if len(result) > 2 else None)
                return self.send(200, result)
        if method == "GET":
            return self.static(path)
        self.send(404, {"error": "Not found."})

    def static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        file = (APP / rel).resolve() if rel.startswith("static/") else (STATIC / rel).resolve()
        if not str(file).startswith(str(STATIC)) or not file.is_file():
            return self.send(404, b"Not found", "text/plain")
        types = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
        self.send(200, file.read_bytes(), types.get(file.suffix, "application/octet-stream") + "; charset=utf-8")

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")


def main():
    db.init()
    _, warning = facts.load()
    if warning:
        print("Warning:", warning)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"JobDesk running at {url} (local only). Press Ctrl+C to stop.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
