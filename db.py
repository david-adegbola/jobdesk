"""All JobDesk data access. SQLite file: app/data/jobdesk.db (git-ignored, never pushed).

Every table has a user_id column (default 1) so the app can become multi-user later;
every function takes user_id and only touches that user's rows.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
DB_FILE = DATA_DIR / "jobdesk.db"

STATUSES = ["Saved", "Applied", "Interview", "Offer", "Rejected"]
# How far along the funnel a status is (Rejected keeps the furthest stage reached before it)
STAGE = {"Saved": 1, "Applied": 2, "Interview": 3, "Offer": 4}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checks (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  found INTEGER DEFAULT 0,
  new INTEGER DEFAULT 0,
  error TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  url TEXT DEFAULT '',
  title TEXT NOT NULL,
  company TEXT DEFAULT '',
  location TEXT DEFAULT '',
  posted TEXT DEFAULT '',
  deadline TEXT DEFAULT '',
  category TEXT DEFAULT '',
  ad_text TEXT DEFAULT '',
  contact_name TEXT DEFAULT '',
  contact_phone TEXT DEFAULT '',
  manual INTEGER NOT NULL DEFAULT 0,
  first_check_id INTEGER,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  UNIQUE (user_id, source, external_id)
);
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'Saved',
  max_stage INTEGER NOT NULL DEFAULT 1,
  date_applied TEXT DEFAULT '',
  cv_role TEXT DEFAULT '',
  employer_link TEXT DEFAULT '',
  contact TEXT DEFAULT '',
  notes TEXT DEFAULT '',
  next_action TEXT DEFAULT '',
  next_action_date TEXT DEFAULT '',
  status_changed_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, job_id)
);
CREATE INDEX IF NOT EXISTS jobs_user ON jobs (user_id, deadline, posted);
CREATE INDEX IF NOT EXISTS applications_user ON applications (user_id, status);
"""

APP_FIELDS = ["status", "date_applied", "cv_role", "employer_link", "contact", "notes",
              "next_action", "next_action_date"]


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO users (id, name) VALUES (1, 'David Adegbola')")


# ---------------------------------------------------------------- checks (scraper runs)

def start_check(user_id=1):
    with connect() as conn:
        return conn.execute("INSERT INTO checks (user_id, started_at) VALUES (?, ?)",
                            (user_id, now())).lastrowid


def finish_check(check_id, found, new, error=None, user_id=1):
    with connect() as conn:
        conn.execute("UPDATE checks SET finished_at=?, found=?, new=?, error=? WHERE id=? AND user_id=?",
                     (now(), found, new, error, check_id, user_id))


def latest_check(user_id=1):
    with connect() as conn:
        row = conn.execute("SELECT * FROM checks WHERE user_id=? AND finished_at IS NOT NULL "
                           "ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------- jobs

def upsert_scraped(job, check_id, already_seen=False, user_id=1):
    """Insert or refresh a scraped job. Returns True if it is new (never seen before)."""
    today = date.today().isoformat()
    with connect() as conn:
        row = conn.execute("SELECT id FROM jobs WHERE user_id=? AND source=? AND external_id=?",
                           (user_id, job["source"], job["external_id"])).fetchone()
        if row:
            # keep anything typed in by hand; refresh what the listing says
            conn.execute("""UPDATE jobs SET last_seen=?,
                              title=CASE WHEN manual=1 AND title!='' THEN title ELSE ? END,
                              company=CASE WHEN company='' THEN ? ELSE company END,
                              location=CASE WHEN location='' THEN ? ELSE location END,
                              posted=CASE WHEN posted='' THEN ? ELSE posted END,
                              category=CASE WHEN category='' THEN ? ELSE category END,
                              url=CASE WHEN url='' THEN ? ELSE url END
                            WHERE id=?""",
                         (today, job["title"], job["company"], job["location"], job["posted"],
                          job["category"], job["url"], row["id"]))
            return False
        conn.execute("""INSERT INTO jobs (user_id, source, external_id, url, title, company, location,
                          posted, category, first_check_id, first_seen, last_seen)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (user_id, job["source"], job["external_id"], job["url"], job["title"],
                      job["company"], job["location"], job["posted"], job["category"],
                      0 if already_seen else check_id, today, today))
        return not already_seen


def add_manual(fields, user_id=1):
    """Add (or update) a job typed in by hand. Returns the job id."""
    today = date.today().isoformat()
    cols = ["url", "title", "company", "location", "posted", "deadline", "category", "ad_text",
            "contact_name", "contact_phone"]
    vals = {c: (fields.get(c) or "").strip() for c in cols}
    with connect() as conn:
        row = conn.execute("SELECT id FROM jobs WHERE user_id=? AND source=? AND external_id=?",
                           (user_id, fields["source"], fields["external_id"])).fetchone()
        if row:
            sets = ", ".join(f"{c}=CASE WHEN ?!='' THEN ? ELSE {c} END" for c in cols)
            args = [x for c in cols for x in (vals[c], vals[c])]
            conn.execute(f"UPDATE jobs SET {sets}, manual=1, last_seen=? WHERE id=?",
                         args + [today, row["id"]])
            return row["id"]
        return conn.execute(
            f"""INSERT INTO jobs (user_id, source, external_id, {', '.join(cols)}, manual,
                  first_check_id, first_seen, last_seen)
                VALUES (?,?,?,{','.join('?' * len(cols))},1,NULL,?,?)""",
            [user_id, fields["source"], fields["external_id"]] + [vals[c] for c in cols] + [today, today]
        ).lastrowid


def list_jobs(user_id=1):
    """Jobs with their application (if any) and whether they are NEW in the latest check."""
    latest = latest_check(user_id)
    latest_id = latest["id"] if latest else -1
    with connect() as conn:
        rows = conn.execute("""
            SELECT j.*, a.id AS app_id, a.status, a.cv_role AS app_cv_role,
                   (j.first_check_id = ?) AS is_new
            FROM jobs j LEFT JOIN applications a ON a.job_id = j.id AND a.user_id = j.user_id
            WHERE j.user_id = ?""", (latest_id, user_id)).fetchall()
        return [dict(r) for r in rows]


def get_job(job_id, user_id=1):
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user_id)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------- applications

def set_status(job_id, status, defaults=None, user_id=1):
    """Create the application for a job if needed and set its status. '' removes it."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM applications WHERE job_id=? AND user_id=?",
                           (job_id, user_id)).fetchone()
        if not status:
            if row:
                conn.execute("DELETE FROM applications WHERE id=?", (row["id"],))
            return None
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        if not row:
            d = defaults or {}
            app_id = conn.execute(
                """INSERT INTO applications (user_id, job_id, status, max_stage, cv_role, employer_link,
                     contact, status_changed_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (user_id, job_id, "Saved", 1, d.get("cv_role", ""), d.get("employer_link", ""),
                 d.get("contact", ""), now(), now(), now())).lastrowid
        else:
            app_id = row["id"]
    update_application(app_id, {"status": status}, user_id=user_id)
    return app_id


def update_application(app_id, fields, user_id=1):
    with connect() as conn:
        row = conn.execute("SELECT * FROM applications WHERE id=? AND user_id=?",
                           (app_id, user_id)).fetchone()
        if not row:
            raise KeyError(app_id)
        changes = {k: (fields[k] or "").strip() if isinstance(fields[k], str) else fields[k]
                   for k in APP_FIELDS if k in fields}
        status = changes.get("status")
        if status:
            if status not in STATUSES:
                raise ValueError(f"unknown status {status!r}")
            if status != row["status"]:
                changes["status_changed_at"] = now()
                changes["max_stage"] = max(row["max_stage"], STAGE.get(status, 0))
                if status == "Applied" and not row["date_applied"] and "date_applied" not in fields:
                    changes["date_applied"] = date.today().isoformat()
        if not changes:
            return
        changes["updated_at"] = now()
        conn.execute(f"UPDATE applications SET {', '.join(k + '=?' for k in changes)} WHERE id=?",
                     list(changes.values()) + [app_id])


def list_applications(user_id=1):
    with connect() as conn:
        rows = conn.execute("""
            SELECT a.*, j.title, j.company, j.location, j.url, j.deadline, j.contact_name,
                   j.contact_phone
            FROM applications a JOIN jobs j ON j.id = a.job_id
            WHERE a.user_id = ? ORDER BY a.updated_at DESC""", (user_id,)).fetchall()
        return [dict(r) for r in rows]


def applications_per_role(user_id=1):
    with connect() as conn:
        rows = conn.execute("""SELECT cv_role, COUNT(*) AS n FROM applications
                               WHERE user_id=? AND cv_role!='' GROUP BY cv_role""",
                            (user_id,)).fetchall()
        return {r["cv_role"]: r["n"] for r in rows}


def funnel(user_id=1):
    """Per CV role: how many applications reached each stage."""
    with connect() as conn:
        rows = conn.execute("""SELECT COALESCE(NULLIF(cv_role,''),'(no CV chosen)') AS role,
                                 SUM(max_stage>=1) AS saved, SUM(max_stage>=2) AS applied,
                                 SUM(max_stage>=3) AS interview, SUM(max_stage>=4) AS offer,
                                 SUM(status='Rejected') AS rejected
                               FROM applications WHERE user_id=? GROUP BY role ORDER BY role""",
                            (user_id,)).fetchall()
        return [dict(r) for r in rows]
