#!/usr/bin/env python3
"""JobDesk: job and internship search for students in Finland (originally the JobDesk forestry portal).

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
import secrets
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
import cv_latex  # noqa: E402
import auth     # noqa: E402
import db       # noqa: E402
import facts    # noqa: E402
import ics      # noqa: E402
import prep     # noqa: E402
import prompt   # noqa: E402
import match    # noqa: E402
import owner    # noqa: E402
import scraper  # noqa: E402
import news     # noqa: E402
import skills   # noqa: E402
import language  # noqa: E402
import mailer   # noqa: E402
from core import fields as core_fields  # noqa: E402
from core import batch, draft, finnish, llm, rank  # noqa: E402

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


CV_CONTENT_FIELDS = {
    "target_role", "full_name", "email", "phone", "location", "summary", "education",
    "experience", "skills", "projects", "hobbies", "certifications", "languages", "links",
}
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# Sign-in emails are limited per address and per network address, so the form can't be used to flood
# someone's inbox or to run up the email bill: (key) -> recent request times
LINK_REQUESTS = {}
LINK_REQUESTS_LOCK = threading.Lock()
LINK_WINDOW = 60 * 60
LINK_LIMIT_PER_EMAIL = 5
LINK_LIMIT_PER_IP = 30


def _allowed(key, limit):
    """Record one request for key; False when key already made limit requests in the last LINK_WINDOW."""
    now_time = datetime.now(timezone.utc).timestamp()
    with LINK_REQUESTS_LOCK:
        recent = [t for t in LINK_REQUESTS.get(key, []) if now_time - t < LINK_WINDOW]
        if len(recent) >= limit:
            LINK_REQUESTS[key] = recent
            return False
        LINK_REQUESTS[key] = recent + [now_time]
        return True


def client_ip(h):
    """The visitor's address. Behind Caddy every request comes from 127.0.0.1, so the address Caddy adds
    to X-Forwarded-For is used: the LAST entry, because earlier entries can be written by the visitor."""
    direct = h.client_address[0]
    forwarded = h.headers.get("X-Forwarded-For", "")
    if direct in ("127.0.0.1", "::1") and forwarded:
        return forwarded.split(",")[-1].strip()
    return direct


def _account_user(user):
    return {key: user[key] for key in ("id", "name", "email", "is_admin")}


def _set_login_cookie(h, user_id):
    token, expires = auth.new_session(user_id)
    h.auth_cookie = auth.cookie(token, secure=config.SECURE_COOKIE)
    return expires


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
             content.get("projects", ""), content.get("hobbies", ""), content.get("certifications", "")]
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
    # use_cv is the CV's title, for display; use_cv_slug is its slug, for code that looks roles up
    # (prep.type_for, prompt.build_email). Passing the title there made every lookup miss.
    return {**job, "status": job.get("status") or "", "is_new": bool(job.get("is_new")), "match": best, "blockers": blockers,
            "use_cv": cv["title"] if cv else "",
            "use_cv_slug": cv["slug"] if cv else "",
            # Member CVs have an id; roles from the CV repository (owner tools) don't
            "use_cv_id": cv.get("id") if cv else None,
            "cv_ready": cv is not None, "use_cv_link": "",
            "use_cv_language": cv["language"] if cv else "",
            "days_left": days_left, "has_ad_text": bool(job.get("ad_text"))}


FINNISH_LEVELS = ("none", "basic", "intermediate", "fluent")


def user_preferences(user):
    return json.loads(db.get_user(user["id"])["preferences_json"] or "{}")


def user_fields(user, preferences=None):
    """The member's chosen field ids, in profile order (default: config.DEFAULT_FIELDS)."""
    chosen = (preferences if preferences is not None else user_preferences(user)).get("fields")
    chosen = chosen if isinstance(chosen, list) and chosen else config.DEFAULT_FIELDS
    return [i for i in scraper.PROFILES if i in chosen] or list(config.DEFAULT_FIELDS)


def is_personal(job):
    """The administrator's own non-field jobs: their private Jobly categories and jobs they added
    by hand outside every field. Visible to that administrator only."""
    return job.get("source") == "Personal" or job.get("category") in scraper.PERSONAL_CATEGORIES


def can_see(job, user, owner_key="user_id", fields=None):
    """Private jobs: only the member who collected them. Personal jobs: only their administrator.
    Shared jobs: members whose fields they belong to."""
    if job.get("private"):
        return job.get(owner_key) == user["id"]
    if is_personal(job):
        return bool(user["is_admin"]) and job.get(owner_key) == user["id"]
    return bool(scraper.relevant_fields(job, fields if fields is not None else user_fields(user)))


def forestry_applications(user):
    """The member's applications for jobs they can still see (name kept from the forestry-only days)."""
    fields = user_fields(user)
    return [application for application in db.list_applications(user["id"])
            if can_see(application, user, "job_owner", fields)]


def _text_hash(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def finnish_text(job):
    """What the Finnish classifier reads: the title and the saved ad (public job text only)."""
    return f"{job.get('title') or ''}\n{job.get('ad_text') or ''}".strip()


def finnish_for(job, stored):
    """The stored LLM classification when it was made from the current ad text, else the
    keyword baseline (core.finnish.fallback)."""
    text = finnish_text(job)
    saved = stored.get(job["id"])
    if saved and saved["text_hash"] == _text_hash(text):
        return {k: v for k, v in saved.items() if k not in ("text_hash", "created_at")}
    return finnish.fallback(text)


def safe_application(application):
    return {key: value for key, value in application.items()
            if key not in {"contact_name", "contact_phone", "category", "ad_text", "job_owner"}}


# ---------------------------------------------------------------- state and jobs

@route("GET", "/api/auth/me")
def api_auth_me(h, m):
    return {"user": _account_user(h.user) if h.user else None}


@route("GET", "/api/auth/config")
def api_auth_config(h, m):
    """What the sign-in page needs to know before anyone is signed in."""
    return {"open_signup": config.OPEN_SIGNUP, "dev_email": mailer.backend() == "log"}


SENT = "If that address can receive email, a sign-in link is on its way. It works once, for 15 minutes."


@route("POST", "/api/auth/link")
def api_auth_link(h, m):
    """Email a magic link. Existing account: a sign-in link. New address with a name: a link that creates
    the account when it is opened (so nobody can create an account with someone else's address).
    The answer is the same whether or not the address has an account, so the form can't reveal who uses JobDesk."""
    body = h.json()
    if not isinstance(body, dict):
        return h.error(400, "Enter your email address.")
    email, name, invite = (body.get(key, "") if isinstance(body.get(key, ""), str) else None
                           for key in ("email", "name", "invite"))
    if email is None or name is None or invite is None:
        return h.error(400, "Enter your email address.")
    email, name, invite = email.strip().lower(), name.strip(), invite.strip()
    if not EMAIL_RE.fullmatch(email) or len(email) > 254 or len(name) > 100 or len(invite) > 128:
        return h.error(400, "Enter a valid email address (and a name of up to 100 characters).")
    if not _allowed("ip:" + client_ip(h), LINK_LIMIT_PER_IP) or not _allowed("email:" + email, LINK_LIMIT_PER_EMAIL):
        return h.error(429, "Too many sign-in emails requested. Try again in an hour.")
    user = db.get_user_by_email(email)
    if user and not user["is_active"]:
        return {"ok": True, "message": SENT}
    new_account = user is None
    if new_account and (not name or (not config.OPEN_SIGNUP and not invite)):
        return {"ok": True, "message": SENT + " New here? Choose “Create an account” and add your name"
                + ("." if config.OPEN_SIGNUP else " and invitation code.")}
    token = secrets.token_urlsafe(32)
    db.create_login_link(token, email, name if new_account else "", invite if new_account else "")
    try:
        mailer.send(email, "Your JobDesk sign-in link" if not new_account else "Create your JobDesk account",
                    mailer.sign_in_text(f"{config.PUBLIC_URL}/#/auth?token={token}", new_account))
    except mailer.MailError as error:
        print("Email error:", error)
        return h.error(503, "The sign-in email couldn't be sent right now. Try again in a few minutes.")
    return {"ok": True, "message": SENT}


@route("POST", "/api/auth/verify")
def api_auth_verify(h, m):
    """Open a magic link: the page posts the token (a GET would let email scanners use links up)."""
    body = h.json()
    token = body.get("token") if isinstance(body, dict) else None
    link = db.use_login_link(token) if isinstance(token, str) and 20 <= len(token) <= 100 else None
    if not link:
        return h.error(400, "This link is invalid, expired or already used. Ask for a new one.")
    user = db.get_user_by_email(link["email"])
    if user is None:
        try:
            user_id = db.create_user(link["name"] or link["email"].split("@")[0], link["email"],
                                     None if config.OPEN_SIGNUP else link["invite"])
        except ValueError as error:
            return h.error(400, str(error))
        user = db.get_user(user_id)
    if not user["is_active"]:
        return h.error(400, "This account is closed.")
    _set_login_cookie(h, user["id"])
    h.user = user
    return {"user": _account_user(user)}


@route("POST", "/api/auth/logout")
def api_auth_logout(h, m):
    if h.session_token:
        db.delete_session(db._hash_token(h.session_token))
    h.auth_cookie = auth.cookie("", max_age=0, secure=config.SECURE_COOKIE)
    h.user = None
    return {"ok": True}


@route("GET", "/api/account/export")
def api_account_export(h, m):
    user = db.get_user(h.user["id"])
    data = {
        "account": {"name": user["name"], "email": user["email"]},
        "preferences": json.loads(user["preferences_json"] or "{}"),
        "cvs": db.list_cvs(h.user["id"]),
        "applications": [safe_application(item) for item in forestry_applications(h.user)],
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


@route("GET", "/api/cvs/example")
def api_cv_example(h, m):
    return {"cv": cv_latex.example_cv()}


@route("GET", "/api/cvs/example.pdf")
def api_cv_example_pdf(h, m):
    try:
        pdf = cv_latex.build_pdf(cv_latex.example_cv())
    except FileNotFoundError:
        return h.error(
            503, "Formatted PDF building is not available on this server. Install the JobDesk LaTeX packages and try again.",
        )
    except cv_latex.PdfBuildError as error:
        return h.error(422, str(error))
    return (
        pdf,
        "application/pdf",
        {"Content-Disposition": 'inline; filename="JobDesk-CV-example.pdf"'},
    )


@route("GET", r"/api/cvs/(\d+)/formatted\.pdf")
def api_build_user_cv(h, m):
    cv_id = int(m.group(1))
    user_id = h.user["id"]
    cv = db.get_cv(cv_id, user_id)
    if not cv:
        return h.error(404, "CV not found.")
    source_path = db.get_cv_import_source(cv_id, user_id)
    if source_path:
        try:
            pdf = _read_imported_cv_pdf(source_path)
        except FileNotFoundError:
            return h.error(
                503, "Formatted PDF building is not available on this server. Install the JobDesk LaTeX packages and try again.",
            )
        except cv_latex.PdfBuildError as error:
            return h.error(422, str(error))
        except OSError:
            return h.error(404, "The original formatted PDF is not available for this CV.")
        if pdf is None:
            return h.error(404, "The original formatted PDF is not available for this CV.")
        filename = cv_latex.safe_filename(cv["title"])
        return (
            pdf, "application/pdf",
            {"Content-Disposition": f'inline; filename="{filename}"'},
        )
    try:
        pdf = cv_latex.build_pdf(cv)
    except FileNotFoundError:
        return h.error(
            503, "Formatted PDF building is not available on this server. Install the JobDesk LaTeX packages and try again.",
        )
    except cv_latex.PdfBuildError as error:
        return h.error(422, str(error))
    filename = cv_latex.safe_filename(cv["title"])
    return (
        pdf, "application/pdf",
        {"Content-Disposition": f'inline; filename="{filename}"'},
    )


def _resolve_imported_cv_file(source_path, suffix):
    repo = config.CV_REPO.resolve()
    source = (repo / source_path).resolve()
    if not source.is_relative_to(repo) or source.suffix.lower() != ".tex":
        return None
    file = source.with_suffix(suffix).resolve()
    return file if file.is_relative_to(repo) else None


def _read_imported_cv_pdf(source_path):
    original_pdf = _resolve_imported_cv_file(source_path, ".pdf")
    if original_pdf and original_pdf.is_file():
        return original_pdf.read_bytes()

    source = _resolve_imported_cv_file(source_path, ".tex")
    if not source or not source.is_file():
        return None
    return cv_latex.build_original_pdf(source)


@route("GET", r"/api/cvs/(\d+)/(original\.pdf|source\.tex)")
def api_original_cv_file(h, m):
    source_path = db.get_cv_import_source(int(m.group(1)), h.user["id"])
    if not source_path:
        return h.error(404, "Original CV files are not available for this CV.")
    is_pdf = m.group(2) == "original.pdf"
    file = _resolve_imported_cv_file(source_path, ".pdf" if is_pdf else ".tex")
    if not file:
        return h.error(404, "Original CV files are not available for this CV.")
    try:
        content = _read_imported_cv_pdf(source_path) if is_pdf else file.read_bytes()
    except FileNotFoundError:
        return h.error(
            503, "Formatted PDF building is not available on this server. Install the JobDesk LaTeX packages and try again.",
        )
    except cv_latex.PdfBuildError as error:
        return h.error(422, str(error))
    except OSError:
        return h.error(404, "Original formatted PDF or LaTeX source is not available.")
    if content is None:
        return h.error(404, "Original formatted PDF or LaTeX source is not available.")
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", file.name)
    disposition = "inline" if is_pdf else "attachment"
    content_type = "application/pdf" if is_pdf else "application/x-tex; charset=utf-8"
    return (
        content, content_type,
        {"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


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
    preferences = user_preferences(user)
    fields = user_fields(user, preferences)
    settings = llm_settings()
    return {
        "facts": {}, "facts_warning": None,
        "roles": [{"slug": role["slug"], "title": role["title"]} for role in roles],
        "statuses": db.STATUSES,
        "job_types": [scraper.PROFILES[i]["category"] for i in fields]
                     + (scraper.PERSONAL_CATEGORIES if user["is_admin"] else []),
        "fields": [core_fields.summary(p) for p in scraper.PROFILES.values()],
        "user_fields": fields,
        "finnish_level": preferences.get("finnish_level") or "none",
        "llm_opt_in": preferences.get("llm_opt_in") is True,
        "llm": {"mode": settings.mode, "model": settings.model if settings.live else ""},
        "latest_check": db.latest_check(SHARED_DATA_OWNER), "scrape": SCRAPE.copy(),
        "classify": CLASSIFY.copy() if user["is_admin"] else None,
        "user": {"id": user["id"], "name": user["name"], "email": user["email"],
                 "is_admin": bool(user["is_admin"])},
        "preferences": preferences,
    }


@route("GET", "/api/jobs")
def api_jobs(h, m):
    roles = cv_roles(h.user["id"])
    fields = user_fields(h.user)
    jobs = [job for job in db.list_jobs(h.user["id"]) if can_see(job, h.user, fields=fields)]
    stored = db.finnish_levels(finnish.PROMPT_VERSION)
    safe_jobs = []
    for job in jobs:
        safe = {key: value for key, value in job.items()
                if key not in {"user_id", "external_id", "contact_name", "contact_phone"}}
        safe["personal"] = is_personal(job)     # only ever true for the admin
        matched = [] if safe["personal"] else scraper.relevant_fields(job, fields)
        safe["fields"] = matched
        if matched:     # show the job under the member's own field, e.g. a Valtiolle job as "IT"
            safe["category"] = scraper.PROFILES[matched[0]]["category"]
        safe["languages"] = language.detect(job.get("title"), job.get("ad_text"))
        safe["finnish"] = finnish_for(job, stored)
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
    member_fields = user_fields(h.user)
    matched = scraper.relevant_fields({**body, "source": "Community"}, member_fields)
    share = body.get("share") is True
    if share and not matched:
        labels = " or ".join(scraper.PROFILES[i]["label_en"].lower() for i in member_fields)
        return h.error(400, f"Only {labels} opportunities can be shared here. "
                            "You can still save it for yourself, or choose more fields on the Account page.")
    jid = scraper.jobly_id(url)
    external = f"jobly-{jid}" if jid else (url or f"manual-{uuid.uuid4().hex[:12]}")
    fields = {key: body.get(key, "").strip() for key in text_fields}
    fields.update(url=url, title=title)
    matched_any = matched or scraper.relevant_fields({**body, "source": "Community"})
    fields["category"] = scraper.PROFILES[matched_any[0]]["category"] if matched_any else "Other"
    if share:      # shared with members in the same field (the old community listings)
        fields.update(source="Community", external_id=external, private=False)
    else:          # the default: a job this member collects for themselves; nobody else sees it
        fields.update(source="Saved", external_id=f"private-{h.user['id']}-{external}", private=True)
    fields["contact_name"] = ""
    fields["contact_phone"] = ""
    return {"id": db.add_manual(fields, h.user["id"])}


@route("POST", r"/api/jobs/(\d+)/fetch")
def api_fetch_ad(h, m):
    job = db.get_job(int(m.group(1)), h.user["id"])
    if not job or not job["url"]:
        return h.error(404, "This job has no link to read.")
    if not can_see(job, h.user):
        return h.error(404, "This job is not in your fields.")
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
    if not job or not can_see(job, h.user):
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
        **user_preferences(h.user),      # keep fields, Finnish level and anything else already saved
        "audiences": list(dict.fromkeys(audiences)),
        "topics": list(dict.fromkeys(topics)),
        "region": region,
    }
    db.update_user_preferences(h.user["id"], preferences)
    return {"preferences": preferences}


@route("POST", "/api/account/fields")
def api_update_account_fields(h, m):
    """The member's fields (forestry, IT, ...) and their own Finnish level, used for jobs, Match,
    What to study and the shortlist order."""
    body = h.json()
    if not isinstance(body, dict):
        return h.error(400, "Choose at least one field and your Finnish level.")
    fields, level = body.get("fields"), body.get("finnish_level")
    if (not isinstance(fields, list) or not fields
            or not all(isinstance(i, str) and i in scraper.PROFILES for i in fields)):
        return h.error(400, "Choose at least one field.")
    if level not in FINNISH_LEVELS:
        return h.error(400, "Choose your Finnish level.")
    preferences = {**user_preferences(h.user), "fields": [i for i in scraper.PROFILES if i in fields],
                   "finnish_level": level}
    db.update_user_preferences(h.user["id"], preferences)
    return {"fields": preferences["fields"], "finnish_level": level}


@route("POST", "/api/account/ai")
def api_update_account_ai(h, m):
    """The member's explicit opt-in to sending their CV facts to the AI service for drafting.
    Off by default; turning it off takes effect for the next request."""
    body = h.json()
    if not isinstance(body, dict) or not isinstance(body.get("llm_opt_in"), bool):
        return h.error(400, "Choose on or off.")
    preferences = {**user_preferences(h.user), "llm_opt_in": body["llm_opt_in"]}
    db.update_user_preferences(h.user["id"], preferences)
    return {"llm_opt_in": preferences["llm_opt_in"]}


# ---------------------------------------------------------------- shortlist: many ads at once

SHORTLIST_MAX_ADS = 20          # per request: each ad is one AI call in live mode
SHORTLIST_MAX_URLS = 10         # links are fetched one by one, with the robots.txt check
SHORTLIST_DAILY_LIMIT = config.AI_DAILY_LIMIT   # ads per member per day in live mode: a pilot cost guard
SHORTLIST_USAGE = {}            # (user id, date) -> ads classified with the AI today
SHORTLIST_LOCK = threading.Lock()


def _take_ai_quota(user_id, count):
    """Reserve count AI classifications for today; False when the member's daily limit would be passed."""
    key = (user_id, date.today().isoformat())
    with SHORTLIST_LOCK:
        if SHORTLIST_USAGE.get(key, 0) + count > SHORTLIST_DAILY_LIMIT:
            return False
        SHORTLIST_USAGE[key] = SHORTLIST_USAGE.get(key, 0) + count
        return True


def classify_ads(ads, settings):
    """{ad id: Finnish result}. Live: the AI (4 at a time); a failed call falls back to the keyword rule.
    Mock: the keyword rule (core.finnish.fallback), as on the Jobs page."""
    def one(ad):
        if not settings.live:
            return finnish.fallback(ad["ad_text"])
        try:
            return finnish.classify(ad["ad_text"], settings)
        except (llm.LLMError, ValueError) as error:
            print(f"  ! Finnish level for {ad['id']}: {error}")
            result = finnish.fallback(ad["ad_text"])
            return {**result, "explanation_en": "The AI service failed for this ad, so the keyword rule was used. "
                                                + result["explanation_en"]}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4 if settings.live else 1) as pool:
        return dict(zip([ad["id"] for ad in ads], pool.map(one, ads)))


@route("POST", "/api/shortlist")
def api_shortlist(h, m):
    """Rank a batch of ads for this member: Finnish level with the quoted sentence, skill matches and
    reasons. Only the ads' text goes to the AI service (live mode); skills and Finnish level stay here."""
    body = h.json()
    if not isinstance(body, dict):
        return h.error(400, BODY_ERROR)
    texts = {key: body.get(key, "") for key in ("ads_text", "csv_text", "urls_text")}
    skills = body.get("skills", [])
    if not all(isinstance(value, str) for value in texts.values()):
        return h.error(400, "Ads, CSV and links must be text.")
    if not isinstance(skills, list) or len(skills) > 30 or \
            not all(isinstance(skill, str) and len(skill) <= 100 for skill in skills):
        return h.error(400, "Give up to 30 skills, each up to 100 characters.")
    if texts["csv_text"].strip():
        parsed = batch.fill_from_urls(batch.parse_csv(texts["csv_text"]), scraper.fetch_ad_text)
    elif texts["urls_text"].strip():
        links = batch.split_urls(texts["urls_text"])
        parsed = batch.fetch_urls(links[:SHORTLIST_MAX_URLS], scraper.fetch_ad_text)
        if len(links) > SHORTLIST_MAX_URLS:
            parsed["errors"].append({"item": "links", "message": f"Only the first {SHORTLIST_MAX_URLS} links were read."})
    else:
        parsed = batch.parse_pasted(texts["ads_text"])
    ads, errors = parsed["ads"], parsed["errors"]
    if len(ads) > SHORTLIST_MAX_ADS:
        errors.append({"item": "input", "message": f"Only the first {SHORTLIST_MAX_ADS} ads were checked."})
        ads = ads[:SHORTLIST_MAX_ADS]
    if not ads:
        return {"rows": [], "errors": errors or [{"item": "input", "message": "Paste at least one ad."}],
                "method": ""}
    settings = llm_settings()
    if settings.live and not _take_ai_quota(h.user["id"], len(ads)):
        return h.error(429, f"You've checked {SHORTLIST_DAILY_LIMIT} ads with the AI today, the pilot's daily "
                            "limit. Try again tomorrow.")
    level = user_preferences(h.user).get("finnish_level") or "none"
    rows = rank.rank(ads, [s.strip() for s in skills if s.strip()], classify_ads(ads, settings), level)
    text_of = {ad["id"]: ad["ad_text"] for ad in ads}
    rows = [{**row, "ad_text": text_of[row["id"]]} for row in rows]     # for "Draft an answer" on each row
    return {"rows": rows, "errors": errors, "method": "llm" if settings.live else "baseline_v1",
            "finnish_level": level}


# ---------------------------------------------------------------- "Was this right?" (pilot accuracy)

@route("POST", "/api/finnish/feedback")
def api_finnish_feedback(h, m):
    """A student's verdict on one Finnish result: right, or wrong with the level the ad really states."""
    body = h.json()
    if not isinstance(body, dict):
        return h.error(400, BODY_ERROR)
    level, vote, correct = body.get("level_shown"), body.get("vote"), body.get("correct_level", "")
    method, evidence, job_id = body.get("method"), body.get("evidence", ""), body.get("job_id")
    if level not in db.FINNISH_LEVELS or vote not in ("right", "wrong") or \
            (correct and correct not in db.FINNISH_LEVELS) or method not in ("llm", "baseline_v1", "mock"):
        return h.error(400, "Choose right or wrong (and, if wrong, what the ad really says).")
    if not isinstance(evidence, str) or len(evidence) > 2000 or \
            (job_id is not None and (not isinstance(job_id, int) or isinstance(job_id, bool))):
        return h.error(400, "Invalid feedback.")
    db.save_finnish_feedback(h.user["id"], {
        "job_id": job_id, "method": method, "prompt_version": finnish.PROMPT_VERSION if method == "llm" else "",
        "level_shown": level, "vote": vote, "correct_level": correct if vote == "wrong" else "",
        "evidence": evidence})
    return {"ok": True}


@route("GET", "/api/finnish/feedback/summary")
def api_finnish_feedback_summary(h, m):
    """Administrator: how often students said each kind of result was right, for the pilot report."""
    if not h.user["is_admin"]:
        return h.error(403, "Administrator access is required.")
    rows = db.finnish_feedback_summary()
    by_method = {}
    for row in rows:
        counts = by_method.setdefault(row["method"], {"right": 0, "wrong": 0})
        counts[row["vote"]] += row["n"]
    accuracy = {method: {**c, "share_right": c["right"] / (c["right"] + c["wrong"])} for method, c in by_method.items()}
    return {"rows": rows, "by_method": accuracy}


# ---------------------------------------------------------------- delete account

@route("POST", "/api/account/delete")
def api_account_delete(h, m):
    """Delete the signed-in account and everything personal in it (see db.delete_user). The member types
    their email address to confirm, so a slip of the mouse can't delete an account."""
    body = h.json()
    confirm = body.get("confirm_email") if isinstance(body, dict) else None
    user = db.get_user(h.user["id"])
    if not isinstance(confirm, str) or confirm.strip().lower() != (user["email"] or "").lower():
        return h.error(400, "Type your email address exactly to confirm.")
    try:
        db.delete_user(user["id"])
    except ValueError as error:
        return h.error(400, str(error))
    h.auth_cookie = auth.cookie("", max_age=0, secure=config.SECURE_COOKIE)
    h.user = None
    return {"ok": True}


# ---------------------------------------------------------------- grounded application answers

@route("POST", "/api/draft")
def api_draft(h, m):
    """Draft the answer to one application question from one of the member's own CVs.

    In live mode the CV facts (never name, email, phone, location or links), the question and the
    ad text go to the AI service, and only when the member has opted in. Mock mode needs no opt-in:
    nothing leaves the server. The draft is returned for editing; nothing is sent anywhere else."""
    body = h.json()
    if not isinstance(body, dict):
        return h.error(400, BODY_ERROR)
    cv_id, job_id = body.get("cv_id"), body.get("job_id")
    question, ad_text = body.get("question"), body.get("ad_text", "")
    word_limit, language = body.get("word_limit", 150), body.get("language", "en")
    def whole(value):      # bool is a subclass of int in Python: {"cv_id": true} must not mean CV 1
        return isinstance(value, int) and not isinstance(value, bool)
    if not whole(cv_id) or (job_id is not None and not whole(job_id)):
        return h.error(400, "Choose one of your CVs (and optionally a job).")
    if not isinstance(question, str) or not isinstance(ad_text, str) or not whole(word_limit):
        return h.error(400, "The question and ad must be text and the word limit a whole number.")
    cv = db.get_cv(cv_id, h.user["id"])
    if not cv:
        return h.error(404, "CV not found.")
    if job_id is not None:
        job = db.get_job(job_id, h.user["id"])
        if not job or not can_see(job, h.user):
            return h.error(404, "No such job.")
        ad_text = finnish_text(job)
    settings = llm_settings()
    if settings.live and user_preferences(h.user).get("llm_opt_in") is not True:
        return h.error(403, "AI drafting sends facts from your CV to an AI service, so it is off until you turn it "
                            "on under Account → AI drafting.")
    try:
        result = draft.draft_answer(ad_text, question, cv["content"], word_limit, language, settings)
    except ValueError as error:
        return h.error(400, str(error))
    except llm.LLMError as error:
        return h.error(502, f"The AI service couldn't draft an answer: {error}")
    return result


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
    safe = [safe_application(application) for application in forestry_applications(h.user)]
    return {"applications": [tracker_view(a) for a in safe],
            "statuses": db.STATUSES}


@route("POST", r"/api/applications/(\d+)")
def api_update_application(h, m):
    application_id = int(m.group(1))
    application = next((item for item in forestry_applications(h.user)
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
    applications = [safe_application(item) for item in forestry_applications(h.user)]
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

BODY_ERROR = "The request body must be a JSON object."


def _prompt_body(h):
    """The request body of a prompt route, or None when it (or its "job"/"answers") isn't an object."""
    body = h.json()
    if not isinstance(body, dict):
        return None
    for key in ("job", "answers"):
        if body.get(key) is not None and not isinstance(body[key], dict):
            return None
    return body


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
    body = _prompt_body(h)
    if body is None:
        return h.error(400, BODY_ERROR)
    f, _, roles = context()
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
        analysis["suggested_cv"] = enrich(job, roles, f)["use_cv_slug"]
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
    body = _prompt_body(h)
    if body is None:
        return h.error(400, BODY_ERROR)
    f, _, roles = context()
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
    job_type = m.group(2) or prep.type_for(e["use_cv_slug"], job.get("category"))
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
    if not isinstance(body, dict):
        return h.error(400, BODY_ERROR)
    job_type, qid = body.get("type") or "", body.get("id") or ""
    a_fi, a_en = body.get("a_fi") or "", body.get("a_en") or ""
    if not all(isinstance(value, str) for value in (job_type, qid, a_fi, a_en)):
        return h.error(400, "Question type, id and answers must be text.")
    if len(a_fi) > 5000 or len(a_en) > 5000:
        return h.error(400, "Answers must be 5,000 characters or fewer.")
    if job_type not in prep.TYPES or qid not in prep.question_ids(job_type):
        return h.error(400, "Unknown question.")
    db.save_prep_answer(job_type, qid, a_fi, a_en, h.user["id"])
    return {"ok": True}


# ---------------------------------------------------------------- insights

@route("GET", "/api/insights")
def api_insights(h, m):
    if not h.user["is_admin"]:
        return h.error(404, "Not found.")
    f, _, roles = context()
    jobs = [enrich(j, roles) for j in db.list_jobs(h.user["id"]) if can_see(j, h.user)]
    counts = {}
    for j in jobs:
        for b in j["blockers"]:
            counts[b] = counts.get(b, 0) + 1
    total = len(jobs)
    gaps = sorted(({"blocker": b, "jobs": n, "percent": round(100 * n / total) if total else 0}
                   for b, n in counts.items()), key=lambda x: -x["jobs"])
    with_text = sum(1 for j in jobs if j["has_ad_text"])
    return {"total_jobs": total, "jobs_with_ad_text": with_text, "skills_gap": gaps, "funnel": db.funnel(h.user["id"])}


# ---------------------------------------------------------------- what to study

def _skills_analysis(user):
    fields = user_fields(user)
    jobs = [{**job, "personal": is_personal(job)}
            for job in db.list_jobs(user["id"]) if can_see(job, user, fields=fields)]
    cvs = db.list_cvs(user["id"])
    return skills.analyse(jobs, cvs, [scraper.PROFILES[i] for i in fields]), cvs


@route("GET", "/api/skills")
def api_skills(h, m):
    """Skills the visible job ads ask for, compared with this member's own CVs."""
    analysis, _ = _skills_analysis(h.user)
    return analysis


@route("GET", r"/api/skills/draft/([\w-]+)(?:/(fi|en))?")
def api_skills_draft(h, m):
    """An unsaved CV draft for one role type, optionally in a chosen language (fi/en); the CV page
    opens it in the editor."""
    analysis, cvs = _skills_analysis(h.user)
    role = next((r for r in analysis["role_types"] if r["id"] == m.group(1)), None)
    if not role:
        return h.error(404, "No jobs of this type are listed now.")
    draft = skills.draft_cv(role, cvs, role["study"], m.group(2))
    return {"cv": {**draft, "role_id": role["id"]}}


# ---------------------------------------------------------------- forestry news

@route("GET", "/api/news")
def api_news(h, m):
    states = {state["source_id"]: state for state in db.list_news_source_state(SHARED_DATA_OWNER)}
    sources = [{**source, "state": states.get(source["id"])} for source in news.SOURCES]
    stories = [{**item,
                "languages": language.detect(item.get("title"), item.get("summary")),
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
        SCRAPE["result"] = scraper.run(progress, user_id=SHARED_DATA_OWNER, personal=True)
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


# ---------------------------------------------------------------- Finnish level (LLM, runs in the background)

CLASSIFY = {"running": False, "message": "", "done": 0, "total": 0, "result": None}
CLASSIFY_LOCK = threading.Lock()
CLASSIFY_BATCH = 25     # ads per run: each is one paid API call


def llm_settings():
    """LLM settings from the environment; a mistyped setting falls back to mock mode."""
    try:
        return llm.settings_from_env()
    except llm.LLMUnavailable as error:
        print("Warning:", error)
        return llm.Settings()


def classification_queue():
    """Shared jobs with a saved ad whose current text hasn't been classified with this prompt version.
    Personal (administrator-only) jobs and title-only listings are left out."""
    stored = db.finnish_levels(finnish.PROMPT_VERSION)
    queue = []
    for job in db.list_jobs(SHARED_DATA_OWNER):
        if is_personal(job) or not (job.get("ad_text") or "").strip() or not scraper.relevant_fields(job):
            continue
        saved = stored.get(job["id"])
        if saved and saved["text_hash"] == _text_hash(finnish_text(job)):
            continue
        queue.append(job)
    return queue


def _classify_thread(jobs, settings):
    classified = failed = 0
    try:
        for n, job in enumerate(jobs):
            CLASSIFY.update(message=f"Reading “{(job.get('title') or '')[:60]}”", done=n, total=len(jobs))
            text = finnish_text(job)
            try:
                result = finnish.classify(text, settings)
            except (llm.LLMError, ValueError) as error:
                print(f"  ! Finnish level for job {job['id']}: {error}")
                failed += 1
                continue
            db.save_finnish_level(job["id"], _text_hash(text), result)
            classified += 1
    finally:
        CLASSIFY.update(running=False, done=len(jobs), message="",
                        result={"classified": classified, "failed": failed})


@route("POST", "/api/jobs/classify")
def api_classify_start(h, m):
    """Administrator: classify the next batch of shared job ads with the LLM. Only public ad text is
    sent (title + saved ad), never anyone's CV. Refused in mock mode."""
    if not h.user["is_admin"]:
        return h.error(403, "Administrator access is required.")
    settings = llm_settings()
    if not settings.live or not settings.api_key:
        return h.error(400, "The LLM is off (JOBDESK_LLM_MODE is not live, or ANTHROPIC_API_KEY is missing). "
                            "The Jobs page shows the keyword rule meanwhile.")
    with CLASSIFY_LOCK:
        if not CLASSIFY["running"]:
            batch = classification_queue()[:CLASSIFY_BATCH]
            CLASSIFY.update(running=bool(batch), message="Starting…", done=0, total=len(batch),
                            result=None if batch else {"classified": 0, "failed": 0})
            if batch:
                threading.Thread(target=_classify_thread, args=(batch, settings), daemon=True).start()
    return CLASSIFY.copy()


@route("GET", "/api/jobs/classify")
def api_classify_status(h, m):
    if not h.user["is_admin"]:
        return h.error(403, "Administrator access is required.")
    return {**CLASSIFY.copy(), "waiting": len(classification_queue())}


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
        except ValueError:      # invalid JSON, or bytes that aren't UTF-8
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
            public_auth = {"/api/auth/me", "/api/auth/config", "/api/auth/link", "/api/auth/verify"}
            if path not in public_auth and not self.user:
                return self.send(401, {"error": "Sign in to continue."})
        for meth, pattern, fn in ROUTES:
            mt = pattern.match(path)
            if meth == method and mt:
                try:
                    result = fn(self, mt)
                except KeyError:
                    return self.send(404, {"error": "Not found."})
                except (facts.FactsUnavailable, owner.OwnerProfileMissing) as error:
                    # Server set-up problems for the owner tools: say so instead of crashing the request
                    return self.send(503, {"error": str(error)})
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


def unrelated_jobs():
    """Stored jobs that nobody can see: in no field, and not one of the administrator's own
    personal jobs (those stay, visible only to the administrator)."""
    return [job for job in db.jobs_with_applications()
            if not scraper.relevant_fields(job)
            and not (job["user_id"] == SHARED_DATA_OWNER and is_personal(job))]


def prune_unrelated_jobs(apply=False):
    """List non-forestry jobs; with apply=True back up the database and delete them."""
    jobs = unrelated_jobs()
    by_hand = [job for job in jobs if job["manual"]]
    tracked = [job for job in jobs if job["applications"]]
    print(f"{len(jobs)} unrelated jobs: {len(by_hand)} added by hand, "
          f"{len(tracked)} with tracker entries (deleted with them).")
    for job in jobs:
        if job["manual"] or job["applications"]:
            notes = ", ".join(filter(None, ["added by hand" if job["manual"] else "",
                                            job["statuses"] and f"tracker: {job['statuses']}"]))
            print(f"  #{job['id']} {job['title']} | {job['company'] or job['source']} ({notes})")
    if not jobs:
        return
    if not apply:
        print("Dry run: nothing deleted. Run again with --apply to delete these jobs.")
        return
    print(f"Backup saved to {db.backup('before-prune')}")
    print(f"Deleted {db.delete_jobs(job['id'] for job in jobs)} jobs.")


# ---------------------------------------------------------------- pilot administration (command line)

def create_invitations(count, days):
    """count single-use invitation codes valid for days days, for handing out to a pilot group."""
    if not 1 <= count <= 500 or not 1 <= days <= 120:
        raise ValueError("Create 1–500 codes, valid for 1–120 days.")
    codes = []
    for _ in range(count):
        token, expires = auth.new_invitation(days)
        db.create_invitation(SHARED_DATA_OWNER, token, expires.isoformat(timespec="seconds"))
        codes.append(token)
    return codes, expires


def delete_member_accounts(apply=False):
    """End of the pilot: every account except the administrator's, with everything personal in it.
    Without apply it only counts them (a dry run). Returns the number of accounts."""
    with db.connect() as conn:
        ids = [row["id"] for row in conn.execute("SELECT id FROM users WHERE id != ?", (SHARED_DATA_OWNER,))]
    if apply:
        for user_id in ids:
            db.delete_user(user_id)
    return len(ids)


def _option(name, default):
    """The value after --name on the command line, or default."""
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else default


def main():
    db.init()
    if "--provision-admin" in sys.argv:
        email = _option("--provision-admin", "") or input("Administrator email: ")
        try:
            user = db.provision_admin(email)
        except ValueError as error:
            print(error, file=sys.stderr)
            raise SystemExit(1)
        print(f"Administrator account ready for {user['email']}. Sign in with a link sent to that address.")
        return
    if "--create-invitations" in sys.argv:
        codes, expires = create_invitations(int(_option("--create-invitations", "1")), int(_option("--days", "7")))
        print(f"{len(codes)} single-use invitation codes, valid until {expires:%Y-%m-%d %H:%M} UTC:")
        print("\n".join(codes))
        return
    if "--delete-member-accounts" in sys.argv:
        apply = "--apply" in sys.argv
        if apply:
            print(f"Backup saved to {db.backup('before-deleting-members')}")
        n = delete_member_accounts(apply)
        print(f"Deleted {n} member accounts. The backup above and the daily backups still contain their data: "
              "delete them once you have checked the result (see docs/PILOT-DEPLOYMENT.md)." if apply else
              f"{n} member accounts would be deleted. Run again with --apply to delete them.")
        return
    if "--prune-unrelated-jobs" in sys.argv:
        prune_unrelated_jobs(apply="--apply" in sys.argv)
        return
    imported_cvs = cv_import.import_admin_cv_repo()
    if imported_cvs:
        print(f"Imported {imported_cvs} existing CVs to the administrator account.")
    moved = db.rename_roles(merged_roles(), SHARED_DATA_OWNER)
    if moved:
        print(f"Moved {moved} tracker entr{'y' if moved == 1 else 'ies'} from merged CVs to the CV that absorbed them.")
    try:
        _, warning = facts.load()
    except facts.FactsUnavailable as error:
        warning = f"{error} The owner tools (prompt, prep, insights) answer 503 until it is fixed."
    if warning:
        print("Warning:", warning)
    server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    url = f"http://localhost:{config.PORT}"
    print(f"JobDesk running at {url} (CV repository: {config.CV_REPO}). Press Ctrl+C to stop.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
