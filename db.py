"""All Woodesk data access. Shared forestry listings sit beside user-owned application data."""

import difflib
import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

from config import DATA_DIR

DB_FILE = DATA_DIR / "jobdesk.db"

STATUSES = ["Saved", "Applied", "Interview", "Offer", "Rejected"]
# How far along the funnel a status is (Rejected keeps the furthest stage reached before it)
STAGE = {"Saved": 1, "Applied": 2, "Interview": 3, "Offer": 4}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT,
  password_hash TEXT NOT NULL DEFAULT '',
  is_admin INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  preferences_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT ''
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
CREATE TABLE IF NOT EXISTS prep_answers (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
  job_type TEXT NOT NULL,
  question_id TEXT NOT NULL,
  a_fi TEXT DEFAULT '',
  a_en TEXT DEFAULT '',
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, job_type, question_id)
);
CREATE INDEX IF NOT EXISTS jobs_user ON jobs (user_id, deadline, posted);
CREATE INDEX IF NOT EXISTS applications_user ON applications (user_id, status);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions (expires_at);
CREATE TABLE IF NOT EXISTS invitations (
  id INTEGER PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  created_by INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_by INTEGER REFERENCES users(id),
  used_at TEXT
);
CREATE TABLE IF NOT EXISTS cvs (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT 'en',
  content_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cvs_user ON cvs (user_id, updated_at);
CREATE TABLE IF NOT EXISTS cv_imports (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source_path TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  cv_id INTEGER REFERENCES cvs(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, source_path)
);
CREATE TABLE IF NOT EXISTS news_items (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
  source_id TEXT NOT NULL,
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT DEFAULT '',
  published_at TEXT DEFAULT '',
  category TEXT NOT NULL,
  region TEXT DEFAULT '',
  relevance INTEGER NOT NULL DEFAULT 0,
  matched_topics TEXT DEFAULT '',
  coverage_json TEXT NOT NULL DEFAULT '[]',
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  is_read INTEGER NOT NULL DEFAULT 0,
  is_saved INTEGER NOT NULL DEFAULT 0,
  UNIQUE (user_id, source_id, external_id)
);
CREATE INDEX IF NOT EXISTS news_items_user ON news_items (user_id, published_at);
CREATE TABLE IF NOT EXISTS news_source_state (
  user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id),
  source_id TEXT NOT NULL,
  source TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  error TEXT DEFAULT '',
  found INTEGER NOT NULL DEFAULT 0,
  new INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, source_id)
);
CREATE TABLE IF NOT EXISTS news_user_state (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
  is_read INTEGER NOT NULL DEFAULT 0,
  is_saved INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, item_id)
);
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
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        migrations = {
            "email": "TEXT",
            "password_hash": "TEXT NOT NULL DEFAULT ''",
            "is_admin": "INTEGER NOT NULL DEFAULT 0",
            "is_active": "INTEGER NOT NULL DEFAULT 1",
            "preferences_json": "TEXT NOT NULL DEFAULT '{}'",
            "created_at": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in migrations.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
        cv_import_columns = {row["name"] for row in conn.execute("PRAGMA table_info(cv_imports)")}
        if "cv_id" not in cv_import_columns:
            conn.execute("ALTER TABLE cv_imports ADD COLUMN cv_id INTEGER REFERENCES cvs(id) ON DELETE CASCADE")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users (email COLLATE NOCASE) WHERE email IS NOT NULL")
        conn.execute("INSERT OR IGNORE INTO users (id, name, is_admin) VALUES (1, 'David Adegbola', 1)")
        conn.execute("UPDATE users SET is_admin=1 WHERE id=1 AND email IS NULL")
        conn.execute(
            """INSERT OR IGNORE INTO news_user_state (user_id, item_id, is_read, is_saved)
               SELECT user_id, id, is_read, is_saved FROM news_items"""
        )


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def provision_admin(email, password):
    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid administrator email address.")
    with connect() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE AND id!=1", (email,)).fetchone()
        if existing:
            raise ValueError("That email already belongs to another account.")
        conn.execute(
            """UPDATE users SET name=CASE WHEN name='' THEN ? ELSE name END, email=?,
               password_hash=?, is_admin=1, is_active=1 WHERE id=1""",
            (email.split("@")[0], email, password),
        )
        return dict(conn.execute("SELECT id, name, email, is_admin FROM users WHERE id=1").fetchone())


def get_user(user_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT id, name, email, password_hash, is_admin, is_active, preferences_json FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_email(email):
    with connect() as conn:
        row = conn.execute(
            """SELECT id, name, email, password_hash, is_admin, is_active, preferences_json
               FROM users WHERE email=? COLLATE NOCASE""",
            (email.strip(),),
        ).fetchone()
        return dict(row) if row else None


def create_user(name, email, password_hash, invite_token):
    token_hash = _hash_token(invite_token)
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        invite = conn.execute(
            """SELECT id FROM invitations WHERE token_hash=? AND used_by IS NULL AND expires_at>?""",
            (token_hash, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        ).fetchone()
        if not invite:
            raise ValueError("That invitation is invalid, expired or already used.")
        try:
            user_id = conn.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?,?,?,?)",
                (name.strip(), email.strip().lower(), password_hash, now()),
            ).lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("An account with that email already exists.") from exc
        conn.execute(
            "UPDATE invitations SET used_by=?, used_at=? WHERE id=? AND used_by IS NULL",
            (user_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), invite["id"]),
        )
        return user_id


def create_session(user_id, token_hash, expires_at):
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token_hash, user_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), expires_at),
        )


def get_session_user(token_hash):
    with connect() as conn:
        row = conn.execute(
            """SELECT u.id, u.name, u.email, u.is_admin FROM sessions s
               JOIN users u ON u.id=s.user_id
               WHERE s.token_hash=? AND s.expires_at>? AND u.is_active=1""",
            (token_hash, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        ).fetchone()
        return dict(row) if row else None


def delete_session(token_hash):
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))


def create_invitation(created_by, token, expires_at):
    with connect() as conn:
        conn.execute(
            "INSERT INTO invitations (token_hash, created_by, created_at, expires_at) VALUES (?,?,?,?)",
            (_hash_token(token), created_by, datetime.now(timezone.utc).isoformat(timespec="seconds"), expires_at),
        )


def list_invitations(created_by):
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, created_at, expires_at, used_at,
                      (used_by IS NOT NULL) AS used
               FROM invitations WHERE created_by=? ORDER BY id DESC""",
            (created_by,),
        ).fetchall()
        return [dict(row) for row in rows]


def update_user_password(user_id, password_hash):
    with connect() as conn:
        result = conn.execute(
            "UPDATE users SET password_hash=? WHERE id=? AND is_active=1",
            (password_hash, user_id),
        )
        if not result.rowcount:
            raise KeyError(user_id)
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


def update_user_preferences(user_id, preferences):
    with connect() as conn:
        result = conn.execute(
            "UPDATE users SET preferences_json=? WHERE id=? AND is_active=1",
            (json.dumps(preferences, ensure_ascii=False), user_id),
        )
        if not result.rowcount:
            raise KeyError(user_id)


def list_cvs(user_id):
    with connect() as conn:
        rows = conn.execute(
            """SELECT cvs.*, cv_imports.source_path AS original_source
               FROM cvs LEFT JOIN cv_imports
                 ON cv_imports.user_id=cvs.user_id AND cv_imports.cv_id=cvs.id
               WHERE cvs.user_id=? ORDER BY cvs.updated_at DESC, cvs.id DESC""",
            (user_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["has_original"] = bool(item.pop("original_source"))
            item["content"] = json.loads(item.pop("content_json"))
            result.append(item)
        return result


def get_cv_import_source(cv_id, user_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT source_path FROM cv_imports WHERE cv_id=? AND user_id=?",
            (cv_id, user_id),
        ).fetchone()
        return row["source_path"] if row else None


def get_cv(cv_id, user_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM cvs WHERE id=? AND user_id=?", (cv_id, user_id)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["content"] = json.loads(item.pop("content_json"))
        return item


def save_cv(user_id, title, language, content, cv_id=None):
    timestamp = now()
    with connect() as conn:
        if cv_id is None:
            return conn.execute(
                """INSERT INTO cvs (user_id, title, language, content_json, created_at, updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (user_id, title, language, json.dumps(content, ensure_ascii=False), timestamp, timestamp),
            ).lastrowid
        result = conn.execute(
            """UPDATE cvs SET title=?, language=?, content_json=?, updated_at=?
               WHERE id=? AND user_id=?""",
            (title, language, json.dumps(content, ensure_ascii=False), timestamp, cv_id, user_id),
        )
        if not result.rowcount:
            raise KeyError(cv_id)
        return cv_id


def import_cv_for_admin(source_path, title, language, content):
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        admin = conn.execute("SELECT is_admin FROM users WHERE id=1").fetchone()
        if not admin or not admin["is_admin"]:
            raise PermissionError("Existing role CVs can only be imported to the administrator account.")
        exists = conn.execute(
            "SELECT cv_id, imported_at FROM cv_imports WHERE user_id=1 AND source_path=?",
            (source_path,),
        ).fetchone()
        if exists:
            if exists["cv_id"] is None:
                imported_cv = conn.execute(
                    """SELECT id FROM cvs
                       WHERE user_id=1 AND title=? AND language=? AND created_at=?
                       ORDER BY id DESC LIMIT 1""",
                    (title, language, exists["imported_at"]),
                ).fetchone()
                if imported_cv:
                    conn.execute(
                        "UPDATE cv_imports SET cv_id=? WHERE user_id=1 AND source_path=?",
                        (imported_cv["id"], source_path),
                    )
            return False
        timestamp = now()
        cv_id = conn.execute(
            """INSERT INTO cvs (user_id, title, language, content_json, created_at, updated_at)
               VALUES (1, ?, ?, ?, ?, ?)""",
            (title, language, json.dumps(content, ensure_ascii=False), timestamp, timestamp),
        ).lastrowid
        conn.execute(
            "INSERT INTO cv_imports (user_id, source_path, imported_at, cv_id) VALUES (1, ?, ?, ?)",
            (source_path, timestamp, cv_id),
        )
        return True


def delete_cv(cv_id, user_id):
    with connect() as conn:
        result = conn.execute("DELETE FROM cvs WHERE id=? AND user_id=?", (cv_id, user_id))
        if not result.rowcount:
            raise KeyError(cv_id)
        conn.execute(
            "UPDATE applications SET cv_role='' WHERE user_id=? AND cv_role=?",
            (user_id, f"cv-{cv_id}"),
        )


def rename_roles(mapping, user_id=1):
    """Move tracker entries from merged (old) roles to the role that absorbed them. Returns rows changed."""
    changed = 0
    with connect() as conn:
        for old, new in mapping.items():
            changed += conn.execute(
                """UPDATE applications SET cv_role=?, employer_link=REPLACE(employer_link, ?, ?)
                   WHERE user_id=? AND cv_role=?""", (new, f"/r/{old}/", f"/r/{new}/", user_id, old)).rowcount
    return changed


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

def upsert_scraped(job, check_id, user_id=1):
    """Insert or refresh a scraped job. Returns True if it is new (never seen before)."""
    today = date.today().isoformat()
    description = (job.get("description") or job.get("ad_text") or "")[:20_000]
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
                              url=CASE WHEN url='' THEN ? ELSE url END,
                              ad_text=CASE WHEN ad_text='' THEN ? ELSE ad_text END
                            WHERE id=?""",
                         (today, job["title"], job["company"], job["location"], job["posted"],
                          job["category"], job["url"], description, row["id"]))
            return False
        conn.execute("""INSERT INTO jobs (user_id, source, external_id, url, title, company, location,
                          posted, category, ad_text, first_check_id, first_seen, last_seen)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (user_id, job["source"], job["external_id"], job["url"], job["title"],
                      job["company"], job["location"], job["posted"], job["category"], description,
                      check_id, today, today))
        return True


def add_manual(fields, user_id=1):
    """Publish a community job, deduplicating by source and external id across accounts."""
    today = date.today().isoformat()
    cols = ["url", "title", "company", "location", "posted", "deadline", "category", "ad_text",
            "contact_name", "contact_phone"]
    vals = {c: (fields.get(c) or "").strip() for c in cols}
    with connect() as conn:
        row = conn.execute("SELECT id, user_id FROM jobs WHERE source=? AND external_id=? ORDER BY id LIMIT 1",
                           (fields["source"], fields["external_id"])).fetchone()
        if row:
            if row["user_id"] != user_id:
                return row["id"]
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
    """Shared listings with only the requesting user's application status."""
    latest = latest_check(1)
    latest_id = latest["id"] if latest else -1
    with connect() as conn:
        rows = conn.execute("""
            SELECT j.*, a.id AS app_id, a.status, a.cv_role AS app_cv_role,
                   (j.first_check_id = ?) AS is_new
            FROM jobs j LEFT JOIN applications a ON a.job_id = j.id AND a.user_id = ?
            ORDER BY j.posted DESC, j.id DESC""", (latest_id, user_id)).fetchall()
        return [dict(r) for r in rows]

def get_job(job_id, user_id=1):
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def update_job_ad_text(job_id, text):
    with connect() as conn:
        result = conn.execute("UPDATE jobs SET ad_text=? WHERE id=?", (text, job_id))
        if not result.rowcount:
            raise KeyError(job_id)


def jobs_with_applications():
    """Every stored job, with how many tracker entries point at it and their statuses."""
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT jobs.*, COUNT(applications.id) AS applications,
                      COALESCE(GROUP_CONCAT(applications.status, ', '), '') AS statuses
               FROM jobs LEFT JOIN applications ON applications.job_id = jobs.id
               GROUP BY jobs.id ORDER BY jobs.id""")]


def backup(label):
    """Copy the whole database to DATA_DIR/backups/ (SQLite online backup) and return the path."""
    folder = DATA_DIR / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"jobdesk-{label}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    with connect() as conn, sqlite3.connect(target) as copy:
        conn.backup(copy)
    return target


def delete_jobs(job_ids):
    """Delete jobs by id. Their tracker entries go with them (ON DELETE CASCADE)."""
    job_ids = list(job_ids)
    with connect() as conn:
        for start in range(0, len(job_ids), 500):
            chunk = job_ids[start:start + 500]
            conn.execute(f"DELETE FROM jobs WHERE id IN ({','.join('?' * len(chunk))})", chunk)
    return len(job_ids)


# ---------------------------------------------------------------- forestry news

def upsert_news_item(item, user_id=1):
    """Insert or refresh a story, attaching corroborating coverage without changing reader state."""
    today = date.today().isoformat()
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM news_items WHERE user_id=? AND source_id=? AND external_id=?",
            (user_id, item["source_id"], item["external_id"]),
        ).fetchone()
        if row:
            conn.execute(
                """UPDATE news_items SET last_seen=?, source=?, url=?, title=?, summary=?,
                   published_at=?, category=?, region=?, relevance=?, matched_topics=?
                   WHERE id=? AND user_id=?""",
                (today, item["source"], item["url"], item["title"], item["summary"],
                 item["published_at"], item["category"], item["region"], item["relevance"],
                 item["matched_topics"], row["id"], user_id),
            )
            return False
        rows = conn.execute(
            """SELECT id, source_id, source, external_id, url, title, summary, published_at,
                      relevance, matched_topics, coverage_json
               FROM news_items WHERE user_id=?""",
            (user_id,),
        ).fetchall()
        item_date = _news_datetime(item["published_at"])
        candidate, similarity = None, 0
        normalized_title = _news_title(item["title"])
        for existing in rows:
            if existing["url"] == item["url"]:
                candidate, similarity = existing, 1
                break
            existing_date = _news_datetime(existing["published_at"])
            if not item_date or not existing_date or abs(item_date - existing_date) > timedelta(days=3):
                continue
            score = difflib.SequenceMatcher(
                None, normalized_title, _news_title(existing["title"]),
            ).ratio()
            if score >= 0.85 and score > similarity:
                candidate, similarity = existing, score
        if candidate:
            coverage = json.loads(candidate["coverage_json"] or "[]")
            coverage_item = {
                key: item[key] for key in
                ("source_id", "source", "external_id", "url", "title", "summary", "published_at")
            }
            existing_coverage = next(
                (entry for entry in coverage
                 if entry["source_id"] == item["source_id"] and entry["external_id"] == item["external_id"]),
                None,
            )
            if existing_coverage:
                existing_coverage.update(coverage_item)
            elif candidate["source_id"] != item["source_id"] or candidate["external_id"] != item["external_id"]:
                coverage.append(coverage_item)
            topics = list(dict.fromkeys(
                [topic for topic in candidate["matched_topics"].split(", ") if topic] +
                [topic for topic in item["matched_topics"].split(", ") if topic]
            ))
            conn.execute(
                """UPDATE news_items SET last_seen=?, coverage_json=?, relevance=?,
                   matched_topics=? WHERE id=? AND user_id=?""",
                (today, json.dumps(coverage, ensure_ascii=False),
                 max(candidate["relevance"], item["relevance"]), ", ".join(topics),
                 candidate["id"], user_id),
            )
            return False
        conn.execute(
            """INSERT INTO news_items (user_id, source_id, source, external_id, url, title,
               summary, published_at, category, region, relevance, matched_topics, first_seen, last_seen)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, item["source_id"], item["source"], item["external_id"], item["url"],
             item["title"], item["summary"], item["published_at"], item["category"],
             item["region"], item["relevance"], item["matched_topics"], today, today),
        )
        return True


def _news_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _news_title(value):
    return " ".join(re.sub(r"[\W_]+", " ", value.casefold()).split())


def list_news(user_id=1):
    with connect() as conn:
        rows = conn.execute(
            """SELECT n.*, COALESCE(s.is_read, 0) AS reader_is_read,
                      COALESCE(s.is_saved, 0) AS reader_is_saved
               FROM news_items n LEFT JOIN news_user_state s ON s.item_id=n.id AND s.user_id=?
               WHERE n.user_id=1
               ORDER BY CASE WHEN n.published_at='' THEN n.first_seen ELSE n.published_at END DESC,
                        n.id DESC""",
            (user_id,),
        ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["is_read"] = item.pop("reader_is_read")
            item["is_saved"] = item.pop("reader_is_saved")
            item["coverage"] = json.loads(item.pop("coverage_json") or "[]")
        return items


def update_news_state(item_id, fields, user_id=1):
    if not isinstance(fields, dict):
        raise ValueError("News state must be an object.")
    changes = {key: int(value) for key, value in fields.items()
               if key in {"is_read", "is_saved"} and isinstance(value, bool)}
    if not changes or len(changes) != len(fields):
        raise ValueError("News state must include a boolean read or saved value.")
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM news_items WHERE id=? AND user_id=1", (item_id,)).fetchone():
            raise KeyError(item_id)
        columns = ["is_read", "is_saved"]
        row = conn.execute(
            "SELECT is_read, is_saved FROM news_user_state WHERE item_id=? AND user_id=?",
            (item_id, user_id),
        ).fetchone()
        state = {key: (row[key] if row else 0) for key in columns}
        state.update({key: int(value) for key, value in fields.items()})
        conn.execute(
            """INSERT INTO news_user_state (user_id, item_id, is_read, is_saved) VALUES (?,?,?,?)
               ON CONFLICT (user_id, item_id) DO UPDATE SET
               is_read=excluded.is_read, is_saved=excluded.is_saved""",
            (user_id, item_id, state["is_read"], state["is_saved"]),
        )


def record_news_source_check(source_id, source, found, new, error="", user_id=1):
    with connect() as conn:
        conn.execute(
            """INSERT INTO news_source_state (user_id, source_id, source, checked_at, error, found, new)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT (user_id, source_id) DO UPDATE SET
                 source=excluded.source, checked_at=excluded.checked_at, error=excluded.error,
                 found=excluded.found, new=excluded.new""",
            (user_id, source_id, source, now(), error, found, new),
        )


def list_news_source_state(user_id=1):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM news_source_state WHERE user_id=? ORDER BY source",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


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
    if not isinstance(fields, dict):
        raise ValueError("Application updates must be an object.")
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


EMAIL_PROMPT_START = "--- Application email prompt ---"
EMAIL_PROMPT_END = "--- end of email prompt ---"


def save_email_prompt(job_id, text, defaults, user_id=1):
    """Keep the latest application email prompt in the job's tracker notes (creates a Saved entry if needed)."""
    with connect() as conn:
        row = conn.execute("SELECT id, notes FROM applications WHERE job_id=? AND user_id=?", (job_id, user_id)).fetchone()
    app_id = row["id"] if row else set_status(job_id, "Saved", defaults, user_id=user_id)
    notes = row["notes"] if row else ""
    start, end = notes.find(EMAIL_PROMPT_START), notes.find(EMAIL_PROMPT_END)
    if start != -1 and end > start:                      # replace the earlier one
        notes = (notes[:start] + notes[end + len(EMAIL_PROMPT_END):]).strip()
    block = f"{EMAIL_PROMPT_START}\n{text.strip()}\n{EMAIL_PROMPT_END}"
    update_application(app_id, {"notes": (notes + "\n\n" + block).strip()}, user_id=user_id)
    return app_id


def get_application(job_id, user_id=1):
    with connect() as conn:
        row = conn.execute("SELECT * FROM applications WHERE job_id=? AND user_id=?", (job_id, user_id)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------- prep answers (David's edits, per job type)

def prep_answers(job_type, user_id=1):
    with connect() as conn:
        rows = conn.execute("SELECT question_id, a_fi, a_en FROM prep_answers WHERE user_id=? AND job_type=?",
                            (user_id, job_type)).fetchall()
        return {r["question_id"]: {"a_fi": r["a_fi"], "a_en": r["a_en"]} for r in rows}


def save_prep_answer(job_type, question_id, a_fi, a_en, user_id=1):
    """Save an edited answer; empty in both languages goes back to the draft."""
    with connect() as conn:
        if not (a_fi.strip() or a_en.strip()):
            conn.execute("DELETE FROM prep_answers WHERE user_id=? AND job_type=? AND question_id=?",
                         (user_id, job_type, question_id))
            return
        conn.execute("""INSERT INTO prep_answers (user_id, job_type, question_id, a_fi, a_en, updated_at)
                        VALUES (?,?,?,?,?,?)
                        ON CONFLICT (user_id, job_type, question_id)
                        DO UPDATE SET a_fi=excluded.a_fi, a_en=excluded.a_en, updated_at=excluded.updated_at""",
                     (user_id, job_type, question_id, a_fi.strip(), a_en.strip(), now()))


def list_applications(user_id=1):
    with connect() as conn:
        rows = conn.execute("""
            SELECT a.*, j.title, j.company, j.location, j.url, j.deadline, j.category, j.ad_text,
                   j.contact_name, j.contact_phone, j.source, j.user_id AS job_owner
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
