#!/usr/bin/env python3
"""Woodesk forestry careers portal.

    python3 server.py            # opens http://localhost:8765
    python3 server.py --no-browser

It listens on 127.0.0.1 and keeps its data in data/jobdesk.db (git-ignored). On the server the same
holds, with Caddy in front for HTTPS and the login (see deploy/). Paths and port: config.py.
"""

import json
import re
import shutil
import subprocess
import sys
import threading
import uuid
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.dont_write_bytecode = True      # no __pycache__ folders in the repo
APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))

import config
import cv_import   # noqa: E402
import auth     # noqa: E402
import db       # noqa: E402
import facts    # noqa: E402
import ics      # noqa: E402
import prep     # noqa: E402
import prompt   # noqa: E402
import match    # noqa: E402
import scraper  # noqa: E402
import news     # noqa: E402

STATIC = APP / "static"
SHARED_DATA_OWNER = 1

# Which job type a role belongs to (for manual jobs, when no type is chosen)
ROLE_TYPE = {"salesperson": "Sales"}
for _type, _cv in scraper.CV_FOR_TYPE.items():
    ROLE_TYPE.setdefault(_cv, _type)        # first type wins: industrial-master is Industrial, not Construction

ROUTES = []


def route(method, pattern):
    def register(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn))
        return fn
    return register


LOGIN_ATTEMPTS = {}
LOGIN_ATTEMPTS_LOCK = threading.Lock()
LOGIN_WINDOW = 15 * 60
LOGIN_LIMIT = 10
CV_CONTENT_FIELDS = {
    "target_role", "full_name", "email", "phone", "location", "summary", "education",
    "experience", "skills", "projects", "certifications", "languages", "links",
}


def _password_error(password):
    if not isinstance(password, str) or len(password) < 12:
        return "Use a password with at least 12 characters."
    if len(password) > 256:
        return "Password must be 256 characters or fewer."
    return ""


def _account_user(user):
    return {key: user[key] for key in ("id", "name", "email", "is_admin")}


def _set_login_cookie(h, user_id):
    token, expires = auth.new_session(user_id)
    h.auth_cookie = auth.cookie(token, secure=config.SECURE_COOKIE)
    return expires


def _rate_limited(email):
    now_time = datetime.now(timezone.utc).timestamp()
    with LOGIN_ATTEMPTS_LOCK:
        attempts = [value for value in LOGIN_ATTEMPTS.get(email, []) if now_time - value < LOGIN_WINDOW]
        LOGIN_ATTEMPTS[email] = attempts
        return len(attempts) >= LOGIN_LIMIT


def _record_login_attempt(email):
    now_time = datetime.now(timezone.utc).timestamp()
    with LOGIN_ATTEMPTS_LOCK:
        attempts = [value for value in LOGIN_ATTEMPTS.get(email, []) if now_time - value < LOGIN_WINDOW]
        attempts.append(now_time)
        LOGIN_ATTEMPTS[email] = attempts


# ---------------------------------------------------------------- helpers

def context():
    f, warning = facts.load()
    return f, warning, match.load_roles()


def job_text(job):
    # Title and ad only: company and place names would add noise ("Worker Oy", "Teollisuuskatu")
    return " ".join(job.get(k) or "" for k in ("title", "ad_text"))


def cv_roles(user_id):
    roles = []
    for cv in db.list_cvs(user_id):
        content = cv["content"]
        source = " ".join(
            [cv["title"], content.get("target_role", ""), content.get("summary", ""),
             content.get("skills", ""), content.get("education", ""), content.get("experience", ""),
             content.get("projects", ""), content.get("certifications", "")]
        )
        words = {
            word: word for word in match.tokens(source)
            if len(word) > 2 and word not in match.STOPWORDS and match.stem(word) not in match.STOP_STEMS
        }
        roles.append({
            "id": cv["id"], "slug": f"cv-{cv['id']}", "title": cv["title"],
            "language": cv["language"], "keywords": words,
        })
    return roles


def enrich(job, roles, f=None):
    text = job_text(job)
    scores = match.match(text, roles, job.get("title") or "")
    best = scores[0] if scores else {"slug": "", "score": 0, "words": []}
    use_cv = job.get("app_cv_role") or (best["slug"] if best["score"] >= 20 else "")
    days_left = None
    if job.get("deadline"):
        try:
            days_left = (date.fromisoformat(job["deadline"]) - date.today()).days
        except ValueError:
            pass
    cv = next((role for role in roles if role["slug"] == use_cv), None)
    best_cv = next((role for role in roles if role["slug"] == best["slug"]), None)
    best = {**best, "slug": best_cv["title"] if best_cv else ""}
    blockers = match.blockers(" ".join(job.get(k) or "" for k in ("title", "ad_text")), f) if f else []
    return {**job, "status": job.get("status") or "", "is_new": bool(job.get("is_new")), "match": best, "blockers": blockers,
            "use_cv": cv["title"] if cv else "",
            "use_cv_id": cv["id"] if cv else None,
            "cv_ready": cv is not None, "use_cv_link": "",
            "use_cv_language": cv["language"] if cv else "",
            "days_left": days_left, "has_ad_text": bool(job.get("ad_text"))}


def forestry_applications(user_id):
    return [application for application in db.list_applications(user_id)
            if scraper.is_forestry_related(application)]


def safe_application(application):
    return {key: value for key, value in application.items()
            if key not in {"contact_name", "contact_phone", "category", "ad_text"}}


# ---------------------------------------------------------------- state and jobs

@route("GET", "/api/auth/me")
def api_auth_me(h, m):
    return {"user": _account_user(h.user) if h.user else None}


@route("POST", "/api/auth/login")
def api_auth_login(h, m):
    body = h.json()
    if not isinstance(body, dict):
        return h.error(400, "Enter your email and password.")
    email = body.get("email", "").strip().lower() if isinstance(body.get("email"), str) else ""
    password = body.get("password", "")
    if not email or len(email) > 254 or not isinstance(password, str):
        return h.error(400, "Enter your email and password.")
    if _rate_limited(email):
        return h.error(429, "Too many sign-in attempts. Try again in 15 minutes.")
    user = db.get_user_by_email(email)
    valid = auth.verify_password(password, user["password_hash"] if user else "")
    if not user or not user["is_active"] or not valid:
        _record_login_attempt(email)
        return h.error(401, "Email or password is incorrect.")
    with LOGIN_ATTEMPTS_LOCK:
        LOGIN_ATTEMPTS.pop(email, None)
    _set_login_cookie(h, user["id"])
    h.user = user
    return {"user": _account_user(user)}


@route("POST", "/api/auth/register")
def api_auth_register(h, m):
    body = h.json()
    if not isinstance(body, dict):
        return h.error(400, "Enter your name, email, password and invitation code.")
    name = body.get("name", "").strip() if isinstance(body.get("name"), str) else ""
    email = body.get("email", "").strip().lower() if isinstance(body.get("email"), str) else ""
    password = body.get("password", "")
    invite = body.get("invite", "").strip() if isinstance(body.get("invite"), str) else ""
    if not name or len(name) > 100:
        return h.error(400, "Enter your name (up to 100 characters).")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 254:
        return h.error(400, "Enter a valid email address.")
    if _password_error(password):
        return h.error(400, _password_error(password))
    if not invite or len(invite) > 128:
        return h.error(400, "Enter an invitation code.")
    try:
        user_id = db.create_user(name, email, auth.hash_password(password), invite)
    except ValueError as error:
        return h.error(400, str(error))
    _set_login_cookie(h, user_id)
    user = db.get_user(user_id)
    h.user = user
    return {"user": _account_user(user)}


@route("POST", "/api/auth/logout")
def api_auth_logout(h, m):
    if h.session_token:
        db.delete_session(db._hash_token(h.session_token))
    h.auth_cookie = auth.cookie("", max_age=0, secure=config.SECURE_COOKIE)
    h.user = None
    return {"ok": True}


@route("POST", "/api/account/password")
def api_change_password(h, m):
    body = h.json()
    if not isinstance(body, dict):
        return h.error(400, "Enter your current and new passwords.")
    current = body.get("current_password", "")
    password = body.get("new_password", "")
    user = db.get_user(h.user["id"])
    if not isinstance(current, str) or not auth.verify_password(current, user["password_hash"]):
        return h.error(400, "Current password is incorrect.")
    if _password_error(password):
        return h.error(400, _password_error(password))
    db.update_user_password(h.user["id"], auth.hash_password(password))
    _set_login_cookie(h, h.user["id"])
    return {"ok": True}


@route("GET", "/api/account/export")
def api_account_export(h, m):
    user = db.get_user(h.user["id"])
    data = {
        "account": {"name": user["name"], "email": user["email"]},
        "preferences": json.loads(user["preferences_json"] or "{}"),
        "cvs": db.list_cvs(h.user["id"]),
        "applications": [safe_application(item) for item in forestry_applications(h.user["id"])],
        "news_reading_list": [
            {"id": item["id"], "title": item["title"], "url": item["url"],
             "is_read": bool(item["is_read"]), "is_saved": bool(item["is_saved"])}
            for item in db.list_news(h.user["id"]) if item["is_read"] or item["is_saved"]
        ],
    }
    return (json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json; charset=utf-8",
            {"Content-Disposition": 'attachment; filename="jobdesk-account-data.json"'})


@route("GET", "/api/account/invitations")
def api_list_invitations(h, m):
    if not h.user["is_admin"]:
        return h.error(403, "Administrator access is required.")
    return {"invitations": db.list_invitations(h.user["id"])}


@route("POST", "/api/account/invitations")
def api_create_invitation(h, m):
    if not h.user["is_admin"]:
        return h.error(403, "Administrator access is required.")
    token, expires = auth.new_invitation()
    db.create_invitation(h.user["id"], token, expires.isoformat(timespec="seconds"))
    return {"code": token, "expires_at": expires.isoformat(timespec="seconds")}


@route("GET", "/api/cvs")
def api_list_cvs(h, m):
    return {"cvs": db.list_cvs(h.user["id"])}


def _validated_cv(body):
    if not isinstance(body, dict):
        raise ValueError("CV details must be an object.")
    title = body.get("title", "")
    language = body.get("language", "")
    content = body.get("content")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 100:
        raise ValueError("Give this CV a title (up to 100 characters).")
    if language not in {"fi", "en"}:
        raise ValueError("Choose Finnish or English.")
    if not isinstance(content, dict) or set(content) - CV_CONTENT_FIELDS:
        raise ValueError("CV content contains an unknown field.")
    clean = {}
    for field in CV_CONTENT_FIELDS:
        value = content.get(field, "")
        if not isinstance(value, str) or len(value) > 20_000:
            raise ValueError(f"{field.replace('_', ' ').capitalize()} must be text of at most 20,000 characters.")
        clean[field] = value.strip()
    if not clean["full_name"]:
        raise ValueError("Add your name to the CV.")
    return title.strip(), language, clean


@route("POST", "/api/cvs")
def api_create_cv(h, m):
    try:
        title, language, content = _validated_cv(h.json())
    except ValueError as error:
        return h.error(400, str(error))
    cv_id = db.save_cv(h.user["id"], title, language, content)
    return {"id": cv_id}


@route("POST", r"/api/cvs/(\d+)")
def api_update_cv(h, m):
    try:
        title, language, content = _validated_cv(h.json())
        cv_id = db.save_cv(h.user["id"], title, language, content, int(m.group(1)))
    except ValueError as error:
        return h.error(400, str(error))
    except KeyError:
        return h.error(404, "CV not found.")
    return {"id": cv_id}


@route("POST", r"/api/cvs/(\d+)/delete")
def api_delete_cv(h, m):
    try:
        db.delete_cv(int(m.group(1)), h.user["id"])
    except KeyError:
        return h.error(404, "CV not found.")
    return {"ok": True}


@route("GET", "/api/state")
def api_state(h, m):
    user = h.user
    roles = cv_roles(user["id"])
    preferences = json.loads(db.get_user(user["id"])["preferences_json"] or "{}")
    return {
        "facts": {}, "facts_warning": None,
        "roles": [{"slug": role["slug"], "title": role["title"]} for role in roles],
        "statuses": db.STATUSES, "job_types": ["Forestry"],
        "latest_check": db.latest_check(SHARED_DATA_OWNER), "scrape": SCRAPE.copy(),
        "user": {"id": user["id"], "name": user["name"], "email": user["email"],
                 "is_admin": bool(user["is_admin"])},
        "preferences": preferences,
    }


@route("GET", "/api/jobs")
def api_jobs(h, m):
    roles = cv_roles(h.user["id"])
    jobs = [job for job in db.list_jobs(h.user["id"]) if scraper.is_forestry_related(job)]
    safe_jobs = []
    for job in jobs:
        safe = {key: value for key, value in job.items()
                if key not in {"user_id", "external_id", "contact_name", "contact_phone"}}
        safe_jobs.append(enrich(safe, roles))
    return {"jobs": safe_jobs, "latest_check": db.latest_check(SHARED_DATA_OWNER)}


@route("POST", "/api/jobs")
def api_add_job(h, m):
    body = h.json()
    text_fields = ("url", "title", "company", "location", "deadline", "posted", "ad_text")
    if not isinstance(body, dict) or any(
        key in body and not isinstance(body[key], str) for key in text_fields
    ):
        return h.error(400, "Job details must be text.")
    title = body.get("title", "").strip()
    url = body.get("url", "").strip()
    if not title or len(title) > 200:
        return h.error(400, "A job title of 1–200 characters is needed.")
    if len(url) > 2048 or len(body.get("company", "")) > 200 or len(body.get("location", "")) > 200:
        return h.error(400, "The link, company or location is too long.")
    if url:
        parsed_url = urlparse(url)
        if (parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname or
                parsed_url.username or parsed_url.password or re.search(r"[\x00-\x20]", url)):
            return h.error(400, "Use a public job link beginning with http:// or https://.")
    if len(body.get("ad_text", "")) > 20_000:
        return h.error(400, "The public job description must be 20,000 characters or fewer.")
    if not scraper.is_forestry_related(body):
        return h.error(400, "Only forestry and forest-bioeconomy opportunities can be shared here.")
    jid = scraper.jobly_id(url)
    if jid:
        source, external = "Jobly", jid
    elif url:
        source, external = "Manual", url
    else:
        source, external = "Manual", f"manual-{uuid.uuid4().hex[:12]}"
    fields = {key: body.get(key, "").strip() for key in text_fields}
    fields.update(url=url, title=title, source=source, external_id=external)
    fields["category"] = "Forestry"
    fields["source"] = "Community"
    fields["contact_name"] = ""
    fields["contact_phone"] = ""
    return {"id": db.add_manual(fields, h.user["id"])}


@route("POST", r"/api/jobs/(\d+)/fetch")
def api_fetch_ad(h, m):
    job = db.get_job(int(m.group(1)), h.user["id"])
    if not job or not job["url"]:
        return h.error(404, "This job has no link to read.")
    if not scraper.is_forestry_related(job):
        return h.error(404, "This is not a forestry opportunity.")
    if not scraper.is_public_http_url(job["url"]):
        return h.error(400, "Reading an ad requires a public HTTP or HTTPS address.")
    text = scraper.fetch_ad_text(job["url"])
    if not text:
        return h.error(502, "Couldn't read the ad page.")
    db.update_job_ad_text(job["id"], text)
    return {"ok": True, "chars": len(text)}


@route("POST", r"/api/jobs/(\d+)/status")
def api_job_status(h, m):
    job_id = int(m.group(1))
    body = h.json()
    if not isinstance(body, dict):
        return h.error(400, "Choose an application status.")
    status = (body.get("status") or "").strip()
    job = db.get_job(job_id, h.user["id"])
    if not job or not scraper.is_forestry_related(job):
        return h.error(404, "No such job.")
    roles = cv_roles(h.user["id"])
    e = enrich(job, roles)
    cv_id = body.get("cv_id") or e["use_cv_id"]
    if cv_id is not None and not db.get_cv(int(cv_id), h.user["id"]):
        return h.error(400, "Choose one of your own CVs.")
    cv = db.get_cv(int(cv_id), h.user["id"]) if cv_id is not None else None
    contact = " ".join(x for x in (job["contact_name"], job["contact_phone"]) if x)
    try:
        app_id = db.set_status(job_id, status, {
            "cv_role": f"cv-{cv['id']}" if cv else "",
            "employer_link": "",
            "contact": contact,
        }, h.user["id"])
    except ValueError as err:
        return h.error(400, str(err))
    if app_id and cv_id is not None:
        db.update_application(app_id, {"cv_role": f"cv-{int(cv_id)}", "employer_link": ""}, h.user["id"])
    return {"application_id": app_id}


@route("GET", "/api/account/profile")
def api_account_profile(h, m):
    user = db.get_user(h.user["id"])
    return {"preferences": json.loads(user["preferences_json"] or "{}")}


@route("POST", "/api/account/profile")
def api_update_account_profile(h, m):
    body = h.json()
    if not isinstance(body, dict):
        return h.error(400, "Choose valid audiences, topics and a location.")
    audiences = body.get("audiences")
    topics = body.get("topics")
    region = body.get("region")
    allowed_audiences = {"student", "researcher", "owner", "professional", "exploring"}
    allowed_topics = {"bioeconomy", "management", "research", "data", "nature", "materials", "policy"}
    if (not isinstance(audiences, list) or not all(isinstance(item, str) and item in allowed_audiences
                                                    for item in audiences) or
            not isinstance(topics, list) or not all(isinstance(item, str) and item in allowed_topics
                                                     for item in topics) or
            not isinstance(region, str) or region not in {"anywhere", "finland", "north-karelia"}):
        return h.error(400, "Choose valid audiences, topics and a location.")
    preferences = {
        "audiences": list(dict.fromkeys(audiences)),
        "topics": list(dict.fromkeys(topics)),
        "region": region,
    }
    db.update_user_preferences(h.user["id"], preferences)
    return {"preferences": preferences}


# ---------------------------------------------------------------- tracker

FOLLOW_UP_DAYS = 5


def tracker_view(a):
    today = date.today()
    contact = a["contact"] or ""
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
    safe = [safe_application(application) for application in forestry_applications(h.user["id"])]
    return {"applications": [tracker_view(a) for a in safe],
            "statuses": db.STATUSES}


@route("POST", r"/api/applications/(\d+)")
def api_update_application(h, m):
    application_id = int(m.group(1))
    application = next((item for item in forestry_applications(h.user["id"])
                        if item["id"] == application_id), None)
    if not application:
        return h.error(404, "No such forestry application.")
    body = h.json()
    if not isinstance(body, dict):
        return h.error(400, "Application updates must be an object.")
    try:
        db.update_application(application_id, body, h.user["id"])
    except ValueError as err:
        return h.error(400, str(err))
    return {"ok": True}


@route("GET", "/api/calendar.ics")
def api_calendar(h, m):
    applications = [safe_application(item) for item in forestry_applications(h.user["id"])]
    return (ics.build(applications), "text/calendar; charset=utf-8",
            {"Content-Disposition": 'attachment; filename="jobdesk.ics"'})


# ---------------------------------------------------------------- CVs

REPO = config.CV_REPO


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
    roles = cv_roles(h.user["id"])
    used = db.applications_per_role(h.user["id"])
    return {"roles": [{"slug": role["slug"], "title": role["title"],
                       "language": role["language"], "applications": used.get(role["slug"], 0)}
                      for role in roles], "pdflatex": False}


@route("POST", "/api/build")
def api_build(h, m):
    if not h.user["is_admin"]:
        return h.error(404, "Not found.")
    if not shutil.which("pdflatex"):
        return {"ok": False, "message": "pdflatex isn't installed here. Push the cv repo to GitHub to build the PDFs."}
    built, failed = [], []
    for tex in sorted((REPO / "roles").glob("*/cv-*.tex")):
        name = tex.stem
        ok = all(subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex.name],
                                cwd=tex.parent, capture_output=True, timeout=120).returncode == 0 for _ in range(2))
        (built if ok else failed).append(f"{tex.parent.name}/{name}")
    for d in sorted((REPO / "roles").glob("*/")):
        if shutil.which("pdfunite"):        # combine.sh follows the role's Language line (and skips if a PDF is missing)
            subprocess.run(["sh", str(REPO / "shared" / "combine.sh"), str(d)], cwd=REPO, capture_output=True)
    msg = f"Built {len(built)} PDFs locally (in each roles/<role>/ folder; they are git-ignored)."
    if failed:
        msg += " Failed: " + ", ".join(failed) + ". Check the .log file next to each."
    return {"ok": not failed, "message": msg}


# ---------------------------------------------------------------- new CV prompt

def _prompt_job(h, m):
    if m.group(1):
        job = db.get_job(int(m.group(1)), h.user["id"])
        if not job:
            raise KeyError(m.group(1))
        return job
    body = h.json() if h.command == "POST" else {}
    return body.get("job") or {}


@route("GET", r"/api/prompt/(\d+)")
def api_prompt_analyse(h, m):
    if not h.user["is_admin"]:
        return h.error(404, "Not found.")
    f, _, roles = context()
    return prompt.analyse(_prompt_job(h, m), roles, f)


@route("POST", r"/api/email-prompt(?:/(\d+))?")
def api_email_prompt(h, m):
    if not h.user["is_admin"]:
        return h.error(404, "Not found.")
    """Application email prompt. With a job id it is also saved in that job's tracker notes."""
    f, _, roles = context()
    body = h.json()
    job = db.get_job(int(m.group(1)), h.user["id"]) if m.group(1) else (body.get("job") or {})
    if m.group(1) and not job:
        raise KeyError(m.group(1))
    if m.group(1) and not job.get("ad_text") and job.get("url"):
        text = scraper.fetch_ad_text(job["url"])
        if text:
            db.update_job_ad_text(job["id"], text)
            job = db.get_job(job["id"], h.user["id"])
    analysis = prompt.analyse(job, roles, f)
    if m.group(1):
        analysis["suggested_cv"] = enrich(job, roles, f)["use_cv"]
    if body.get("analyse_only"):
        return analysis
    text, missing = prompt.build_email(job, analysis, body.get("answers") or {}, roles)
    saved = False
    if text and m.group(1):
        slug = (body.get("answers") or {}).get("cv_role") or analysis.get("suggested_cv") or analysis["closest"]
        db.save_email_prompt(job["id"], text, {"cv_role": slug, "employer_link": match.employer_link(slug)}, h.user["id"])
        saved = True
    return {"prompt": text, "missing": missing, "saved": saved}


@route("POST", r"/api/prompt(?:/(\d+))?")
def api_prompt_build(h, m):
    if not h.user["is_admin"]:
        return h.error(404, "Not found.")
    f, _, roles = context()
    body = h.json()
    job = db.get_job(int(m.group(1)), h.user["id"]) if m.group(1) else (body.get("job") or {})
    if m.group(1) and not job:
        raise KeyError(m.group(1))
    if m.group(1) and not job.get("ad_text") and job.get("url"):
        text = scraper.fetch_ad_text(job["url"])     # one request; stored, so it's read only once
        if text:
            db.update_job_ad_text(job["id"], text)
            job = db.get_job(job["id"], h.user["id"])
    analysis = prompt.analyse(job, roles, f)
    if body.get("analyse_only"):
        return analysis
    text, missing = prompt.build(analysis, body.get("answers") or {})
    return {"prompt": text, "missing": missing, "analysis": analysis}


# ---------------------------------------------------------------- prep (call script and interview answers)

@route("GET", r"/api/prep/(\d+)(?:/(\w+))?")
def api_prep(h, m):
    if not h.user["is_admin"]:
        return h.error(404, "Not found.")
    """Prep for one job. The type comes from the CV used (or the job's category) unless given in the path."""
    f, _, roles = context()
    job = next((j for j in db.list_jobs(h.user["id"]) if j["id"] == int(m.group(1))), None)
    if not job:
        raise KeyError(m.group(1))
    e = enrich(job, roles, f)
    job_type = m.group(2) or prep.type_for(e["use_cv"], job.get("category"))
    if job_type not in prep.TYPES:
        return h.error(400, f"Unknown job type {job_type!r}.")
    app = db.get_application(job["id"], h.user["id"])
    if not job.get("contact_name") and app and app["contact"]:       # e.g. "Esa Räsänen 040 123 4567"
        job = {**job, "contact_name": re.sub(r"[+\d\s()-]+$", "", app["contact"]).strip()}
    return {"job": {k: job.get(k) or "" for k in ("id", "title", "company", "location", "url", "contact_name",
                                                  "contact_phone", "deadline")},
            "status": job.get("status") or "", "cv": e["use_cv"],
            "types": prep.labels(), **prep.build(job, job_type, e["blockers"], db.prep_answers(job_type, h.user["id"]))}


@route("POST", "/api/prep/answer")
def api_prep_answer(h, m):
    if not h.user["is_admin"]:
        return h.error(404, "Not found.")
    body = h.json()
    job_type, qid = body.get("type") or "", body.get("id") or ""
    if job_type not in prep.TYPES or qid not in prep.question_ids(job_type):
        return h.error(400, "Unknown question.")
    db.save_prep_answer(job_type, qid, body.get("a_fi") or "", body.get("a_en") or "", h.user["id"])
    return {"ok": True}


# ---------------------------------------------------------------- insights

@route("GET", "/api/insights")
def api_insights(h, m):
    if not h.user["is_admin"]:
        return h.error(404, "Not found.")
    f, _, roles = context()
    jobs = [enrich(j, roles) for j in db.list_jobs(h.user["id"]) if scraper.is_forestry_related(j)]
    counts = {}
    for j in jobs:
        for b in j["blockers"]:
            counts[b] = counts.get(b, 0) + 1
    total = len(jobs)
    gaps = sorted(({"blocker": b, "jobs": n, "percent": round(100 * n / total) if total else 0}
                   for b, n in counts.items()), key=lambda x: -x["jobs"])
    with_text = sum(1 for j in jobs if j["has_ad_text"])
    return {"total_jobs": total, "jobs_with_ad_text": with_text, "skills_gap": gaps, "funnel": db.funnel(h.user["id"])}


# ---------------------------------------------------------------- forestry news

@route("GET", "/api/news")
def api_news(h, m):
    states = {state["source_id"]: state for state in db.list_news_source_state(SHARED_DATA_OWNER)}
    sources = [{**source, "state": states.get(source["id"])} for source in news.SOURCES]
    stories = [{**item,
                "why_it_matters": news.story_context(item["category"]),
                "career_angle": news.career_context(item["category"])}
               for item in db.list_news(h.user["id"])]
    return {"items": stories, "sources": sources}


NEWS_REFRESH_LOCK = threading.Lock()


@route("POST", "/api/news/refresh")
def api_news_refresh(h, m):
    with NEWS_REFRESH_LOCK:
        return news.refresh(SHARED_DATA_OWNER)


@route("POST", r"/api/news/(\d+)/state")
def api_news_state(h, m):
    body = h.json()
    if not isinstance(body, dict):
        return h.error(400, "News state must be an object.")
    try:
        db.update_news_state(int(m.group(1)), body, h.user["id"])
    except ValueError as err:
        return h.error(400, str(err))
    return {"ok": True}


# ---------------------------------------------------------------- scraper (runs in the background)

SCRAPE = {"running": False, "message": "", "done": 0, "total": 0, "result": None}
SCRAPE_LOCK = threading.Lock()


def _scrape_thread():
    def progress(msg, done, total):
        SCRAPE.update(message=msg, done=done, total=total)
    try:
        SCRAPE["result"] = scraper.run(progress, user_id=SHARED_DATA_OWNER)
    finally:
        SCRAPE["running"] = False


@route("POST", "/api/scrape")
def api_scrape_start(h, m):
    if not h.user["is_admin"]:
        return h.error(403, "Administrator access is required to refresh shared job listings.")
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
    server_version = "Woodesk"

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
        headers = dict(extra or {})
        if getattr(self, "auth_cookie", None):
            headers["Set-Cookie"] = self.auth_cookie
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def dispatch(self, method):
        path = urlparse(self.path).path
        origin = self.headers.get("Origin")
        if method == "POST" and origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self.send(403, {"error": "Cross-site request refused."})
        if method == "POST" and int(self.headers.get("Content-Length") or 0) > 1_000_000:
            return self.send(413, {"error": "Request body is too large."})
        self.user = None
        self.session_token = ""
        if path.startswith("/api/"):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except CookieError:
                return self.send(400, {"error": "Invalid session cookie."})
            morsel = cookie.get("jobdesk_session")
            self.session_token = morsel.value if morsel else ""
            self.user = auth.session_user(self.session_token)
            public_auth = {"/api/auth/me", "/api/auth/login", "/api/auth/register"}
            if path not in public_auth and not self.user:
                return self.send(401, {"error": "Sign in to continue."})
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


def merged_roles():
    """site/redirects.json from the cv repo (data only): {old slug: new slug} for merged roles."""
    try:
        data = json.loads(config.REDIRECTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, str)}


def main():
    db.init()
    if "--provision-admin" in sys.argv:
        import getpass

        email = input("Administrator email: ").strip()
        while True:
            password = getpass.getpass("Administrator password (12+ characters): ")
            if _password_error(password):
                print(_password_error(password))
                continue
            confirmation = getpass.getpass("Again: ")
            if password != confirmation:
                print("They don't match.")
                continue
            break
        try:
            user = db.provision_admin(email, auth.hash_password(password))
        except ValueError as error:
            print(error, file=sys.stderr)
            raise SystemExit(1)
        print(f"Administrator account ready for {user['email']}.")
        return
    imported_cvs = cv_import.import_admin_cv_repo()
    if imported_cvs:
        print(f"Imported {imported_cvs} existing CVs to the administrator account.")
    moved = db.rename_roles(merged_roles(), SHARED_DATA_OWNER)
    if moved:
        print(f"Moved {moved} tracker entr{'y' if moved == 1 else 'ies'} from merged CVs to the CV that absorbed them.")
    _, warning = facts.load()
    if warning:
        print("Warning:", warning)
    server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    url = f"http://localhost:{config.PORT}"
    print(f"Woodesk running at {url} (CV repository: {config.CV_REPO}). Press Ctrl+C to stop.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
