"""All JobDesk data access. Shared job listings (tagged with career fields) sit beside user-owned application data."""

import difflib
import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

from config import DATA_DIR

DB_FILE = DATA_DIR / "jobdesk.db"

STATUSES = ["Saved", "Shortlisted", "Applied", "Interview", "Offer", "Rejected", "Not a fit"]
# How far along the funnel a status is (Rejected and Not a fit keep the furthest stage reached before them)
STAGE = {"Saved": 1, "Shortlisted": 1, "Applied": 2, "Interview": 3, "Offer": 4}

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
CREATE TABLE IF NOT EXISTS finnish_levels (
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  prompt_version TEXT NOT NULL,
  text_hash TEXT NOT NULL,
  level TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '[]',
  explanation TEXT NOT NULL DEFAULT '',
  method TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  verified INTEGER NOT NULL DEFAULT 1,
  rejected_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  PRIMARY KEY (job_id, prompt_version)
);
CREATE TABLE IF NOT EXISTS fit_evaluations (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  cv_id INTEGER NOT NULL REFERENCES cvs(id) ON DELETE CASCADE,
  cache_key TEXT NOT NULL,
  ad_hash TEXT NOT NULL,
  cv_hash TEXT NOT NULL,
  method TEXT NOT NULL,
  suitability TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (user_id, job_id, cache_key)
);
CREATE INDEX IF NOT EXISTS fit_user_job ON fit_evaluations (user_id, job_id, id);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  language TEXT NOT NULL,
  source_cv_id INTEGER REFERENCES cvs(id) ON DELETE SET NULL,
  tailored_cv_id INTEGER REFERENCES cvs(id) ON DELETE SET NULL,
  cache_key TEXT NOT NULL,
  letter_json TEXT NOT NULL,
  email_json TEXT NOT NULL,
  checks_json TEXT NOT NULL,
  method TEXT NOT NULL,
  edited INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, job_id, language)
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS tasks_queue ON tasks (status, id);
CREATE TABLE IF NOT EXISTS login_links (
  token_hash TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  invite TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);
CREATE TABLE IF NOT EXISTS finnish_feedback (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  job_id INTEGER,
  method TEXT NOT NULL,
  prompt_version TEXT NOT NULL DEFAULT '',
  level_shown TEXT NOT NULL,
  vote TEXT NOT NULL,
  correct_level TEXT NOT NULL DEFAULT '',
  evidence TEXT NOT NULL DEFAULT ''
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
        job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "private" not in job_columns:      # 1 = a job a student collected for themselves; only they see it
            conn.execute("ALTER TABLE jobs ADD COLUMN private INTEGER NOT NULL DEFAULT 0")
        cv_import_columns = {row["name"] for row in conn.execute("PRAGMA table_info(cv_imports)")}
        if "cv_id" not in cv_import_columns:
            conn.execute("ALTER TABLE cv_imports ADD COLUMN cv_id INTEGER REFERENCES cvs(id) ON DELETE CASCADE")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users (email COLLATE NOCASE) WHERE email IS NOT NULL")
        conn.execute("INSERT OR IGNORE INTO users (id, name, is_admin) VALUES (1, 'Administrator', 1)")
        conn.execute("UPDATE users SET is_admin=1 WHERE id=1 AND email IS NULL")
        conn.execute("UPDATE users SET password_hash='' WHERE password_hash!=''")    # sign-in is by magic link only
        conn.execute(
            """INSERT OR IGNORE INTO news_user_state (user_id, item_id, is_read, is_saved)
               SELECT user_id, id, is_read, is_saved FROM news_items"""
        )
    migrate()


# ---------------------------------------------------------------- numbered migrations
# Each migration runs once, in order; PRAGMA user_version records the last one applied. Before the first
# pending migration on a database that has jobs, the whole database is backed up (DATA_DIR/backups/).

def _migration_1_job_fields(conn):
    """Career fields stored per job (job_fields), filled in for every existing job from the taxonomy:
    title roles, the old keyword profiles and the old category (e.g. "Forestry" -> forestry,
    "Warehouse" -> logistics). Nothing is deleted; jobs.category stays as the display label."""
    conn.execute("""CREATE TABLE IF NOT EXISTS job_fields (
                      job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                      field_id TEXT NOT NULL,
                      PRIMARY KEY (job_id, field_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS job_fields_field ON job_fields (field_id)")
    import scraper          # the classification lives with the sources; imported late (scraper imports db)
    for row in conn.execute("SELECT * FROM jobs").fetchall():
        _set_fields(conn, row["id"], scraper.classify_job(dict(row)))


# What the ad says about the job (core/jobmeta.py), one column each; the multi-valued ones are in job_tags
META_COLUMNS = {
    "work_mode": "TEXT NOT NULL DEFAULT ''",            # '' | onsite | hybrid | remote
    "municipality_code": "TEXT NOT NULL DEFAULT ''",    # Statistics Finland kunta code (taxonomy/places.json)
    "region_code": "TEXT NOT NULL DEFAULT ''",          # maakunta code
    "start_date": "TEXT NOT NULL DEFAULT ''",           # ISO date or 'asap'
    "salary_min": "REAL",
    "salary_max": "REAL",
    "salary_period": "TEXT NOT NULL DEFAULT ''",        # '' | hour | month | year
    "tes": "TEXT NOT NULL DEFAULT ''",                  # collective agreement named in the ad
    "internship_credits": "INTEGER",                    # op / ECTS
    "paid": "INTEGER",                                  # 1 paid, 0 unpaid, NULL not said
    "combinable_with_studies": "INTEGER",
    "employer_sector": "TEXT NOT NULL DEFAULT ''",      # '' | public | private | third
    "lang_fi": "TEXT NOT NULL DEFAULT 'unclear'",       # required | preferred | not_needed | unclear
    "lang_sv": "TEXT NOT NULL DEFAULT 'unclear'",
    "lang_en": "TEXT NOT NULL DEFAULT 'unclear'",
    "ad_language": "TEXT NOT NULL DEFAULT ''",
}
# Kept by the importers (Phase 3): whether the posting is still open, and the key that finds the same posting
# from another source
LIFECYCLE_COLUMNS = {
    "listing_status": "TEXT NOT NULL DEFAULT 'active'",  # active | expired (not "status": that is the tracker's)
    "expired_at": "TEXT NOT NULL DEFAULT ''",
    "canonical_url": "TEXT NOT NULL DEFAULT ''",          # core/dedupe.py
    "dedupe_key": "TEXT NOT NULL DEFAULT ''",             # core/dedupe.py fingerprint
}
EXPIRE_AFTER_DAYS = 7      # a scraped listing missing from its source's feed this long is closed
TAG_KINDS = {"levels": "level", "employment_types": "employment", "permits": "permit"}


def _migration_2_job_details(conn):
    """Level, employment type, work mode, place, dates, pay, languages, permits and student details per job,
    read from each stored ad (core/jobmeta.py). Adds columns and the job_tags table; nothing is removed."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    for column, definition in {**META_COLUMNS, **LIFECYCLE_COLUMNS}.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")
    conn.execute("""CREATE TABLE IF NOT EXISTS job_tags (
                      job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                      kind TEXT NOT NULL,
                      value TEXT NOT NULL,
                      PRIMARY KEY (job_id, kind, value))""")
    conn.execute("CREATE INDEX IF NOT EXISTS job_tags_value ON job_tags (kind, value)")
    conn.execute("CREATE INDEX IF NOT EXISTS jobs_place ON jobs (region_code, municipality_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS jobs_listing_status ON jobs (listing_status, deadline)")
    conn.execute("CREATE INDEX IF NOT EXISTS jobs_dedupe ON jobs (dedupe_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS jobs_canonical_url ON jobs (canonical_url)")
    import scraper
    for row in conn.execute("SELECT * FROM jobs").fetchall():
        _set_meta(conn, row["id"], scraper.job_meta(dict(row)))
        _set_keys(conn, row["id"])


def _migration_3_job_submissions(conn):
    """Job ads employers send with the public form; an administrator approves or rejects each one."""
    conn.execute("""CREATE TABLE IF NOT EXISTS job_submissions (
                      id INTEGER PRIMARY KEY,
                      created_at TEXT NOT NULL,
                      status TEXT NOT NULL DEFAULT 'pending',       -- pending | approved | rejected
                      employer TEXT NOT NULL,
                      contact_name TEXT NOT NULL DEFAULT '',
                      contact_email TEXT NOT NULL,
                      data_json TEXT NOT NULL,                      -- the validated ad (server.py)
                      decided_at TEXT NOT NULL DEFAULT '',
                      decided_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                      decision_note TEXT NOT NULL DEFAULT '',
                      job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS job_submissions_status ON job_submissions (status, created_at)")


def _migration_4_job_search(conn):
    """Full-text search over title, employer, place and ad text (SQLite FTS5), kept in step with jobs by
    triggers. Diacritics are folded (a search for "paa" finds "pää"). If this SQLite has no FTS5, nothing is
    created and search_text() falls back to LIKE."""
    try:
        conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
                          title, company, location, ad_text, content='jobs', content_rowid='id',
                          tokenize='unicode61 remove_diacritics 2')""")
    except sqlite3.OperationalError:
        return
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS jobs_fts_insert AFTER INSERT ON jobs BEGIN
          INSERT INTO jobs_fts (rowid, title, company, location, ad_text)
          VALUES (new.id, new.title, new.company, new.location, new.ad_text);
        END;
        CREATE TRIGGER IF NOT EXISTS jobs_fts_delete AFTER DELETE ON jobs BEGIN
          INSERT INTO jobs_fts (jobs_fts, rowid, title, company, location, ad_text)
          VALUES ('delete', old.id, old.title, old.company, old.location, old.ad_text);
        END;
        CREATE TRIGGER IF NOT EXISTS jobs_fts_update AFTER UPDATE OF title, company, location, ad_text ON jobs BEGIN
          INSERT INTO jobs_fts (jobs_fts, rowid, title, company, location, ad_text)
          VALUES ('delete', old.id, old.title, old.company, old.location, old.ad_text);
          INSERT INTO jobs_fts (rowid, title, company, location, ad_text)
          VALUES (new.id, new.title, new.company, new.location, new.ad_text);
        END;
        INSERT INTO jobs_fts (jobs_fts) VALUES ('rebuild');
    """)


MIGRATIONS = [
    (1, "career fields stored per job", _migration_1_job_fields),
    (2, "job details read from the ad", _migration_2_job_details),
    (3, "employer job submissions", _migration_3_job_submissions),
    (4, "full-text job search", _migration_4_job_search),
]


def search_text(query):
    """Ids of jobs whose title, employer, place or ad text contain every word of query (as a word start:
    "sairaanhoit" finds "sairaanhoitaja"). Uses FTS5 when the database has it, else LIKE."""
    words = re.findall(r"\w[\w-]*", (query or "").lower())[:8]
    if not words:
        return None
    with connect() as conn:
        has_fts = conn.execute("SELECT 1 FROM sqlite_master WHERE name='jobs_fts'").fetchone()
        if has_fts:
            match = " AND ".join('"' + w.replace('"', "") + '"*' for w in words)
            try:
                return {r[0] for r in conn.execute("SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?", (match,))}
            except sqlite3.OperationalError:
                pass
        where = " AND ".join("(lower(title || ' ' || company || ' ' || location || ' ' || ad_text) LIKE ?)" for _ in words)
        return {r[0] for r in conn.execute(f"SELECT id FROM jobs WHERE {where}", [f"%{w}%" for w in words])}


def schema_version():
    with connect() as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate():
    """Apply the pending MIGRATIONS. Returns the numbers applied."""
    with connect() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        has_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] > 0
    pending = [m for m in MIGRATIONS if m[0] > version]
    if pending and has_jobs:
        backup(f"before-migration-{pending[0][0]}")
    for number, _description, step in pending:
        with connect() as conn:
            step(conn)
            conn.execute(f"PRAGMA user_version = {int(number)}")
    return [m[0] for m in pending]


def _set_fields(conn, job_id, field_ids):
    conn.execute("DELETE FROM job_fields WHERE job_id=?", (job_id,))
    conn.executemany("INSERT OR IGNORE INTO job_fields (job_id, field_id) VALUES (?, ?)",
                     [(job_id, f) for f in dict.fromkeys(field_ids or [])])


def set_job_fields(job_id, field_ids):
    with connect() as conn:
        _set_fields(conn, job_id, field_ids)


def _set_meta(conn, job_id, meta):
    """Store core.jobmeta.extract() output. The deadline is filled only when the job has none."""
    values = {c: meta[c] for c in META_COLUMNS if c in meta}
    for column, value in values.items():
        if value is None and "NOT NULL" in META_COLUMNS[column]:
            values[column] = ""
    if values:
        conn.execute(f"UPDATE jobs SET {', '.join(f'{c}=?' for c in values)} WHERE id=?",
                     list(values.values()) + [job_id])
    if meta.get("deadline"):
        conn.execute("UPDATE jobs SET deadline=? WHERE id=? AND deadline=''", (meta["deadline"], job_id))
    for key, kind in TAG_KINDS.items():
        if key in meta:
            conn.execute("DELETE FROM job_tags WHERE job_id=? AND kind=?", (job_id, kind))
            conn.executemany("INSERT OR IGNORE INTO job_tags (job_id, kind, value) VALUES (?, ?, ?)",
                             [(job_id, kind, v) for v in meta[key] or []])


def set_job_meta(job_id, meta):
    with connect() as conn:
        _set_meta(conn, job_id, meta)
        _set_keys(conn, job_id)


def _set_keys(conn, job_id):
    """Store the job's dedupe keys (core/dedupe.py) from its stored address, title, employer and place."""
    from core import dedupe
    row = conn.execute("SELECT url, title, company, municipality_code FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row:
        conn.execute("UPDATE jobs SET canonical_url=?, dedupe_key=? WHERE id=?",
                     (dedupe.canonical_url(row["url"]),
                      dedupe.fingerprint(row["title"], row["company"], row["municipality_code"]), job_id))


def _duplicate_of(conn, job, meta, user_id):
    """The id of an open listing that is the same posting from another source, or None."""
    from core import dedupe
    url = dedupe.canonical_url(job.get("url"))
    key = dedupe.fingerprint(job.get("title"), job.get("company"), (meta or {}).get("municipality_code", ""))
    if not (url or key):
        return None
    row = conn.execute(
        """SELECT id FROM jobs WHERE user_id=? AND private=0 AND listing_status='active' AND source!=?
             AND ((?!='' AND canonical_url=?) OR (?!='' AND dedupe_key=?))
           ORDER BY (canonical_url=?) DESC, id LIMIT 1""",
        (user_id, job["source"], url, url, key, key, url)).fetchone()
    return row["id"] if row else None


# ---------------------------------------------------------------- employer submissions
SUBMISSION_KEEP_DAYS = 90      # contact details of decided submissions are deleted after this


def add_submission(employer, contact_name, contact_email, data):
    with connect() as conn:
        return conn.execute(
            """INSERT INTO job_submissions (created_at, employer, contact_name, contact_email, data_json)
               VALUES (?, ?, ?, ?, ?)""",
            (now(), employer, contact_name, contact_email, json.dumps(data, ensure_ascii=False))).lastrowid


def _submission(row):
    item = dict(row)
    item["data"] = json.loads(item.pop("data_json") or "{}")
    return item


def list_submissions(status=None):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM job_submissions" + (" WHERE status=?" if status else "")
                            + " ORDER BY created_at DESC, id DESC", (status,) if status else ()).fetchall()
        return [_submission(r) for r in rows]


def get_submission(submission_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM job_submissions WHERE id=?", (submission_id,)).fetchone()
        if not row:
            raise KeyError(submission_id)
        return _submission(row)


def decide_submission(submission_id, approved, admin_id, note="", job_id=None):
    """Record the decision. Raises KeyError when there is no such pending submission."""
    with connect() as conn:
        result = conn.execute(
            """UPDATE job_submissions SET status=?, decided_at=?, decided_by=?, decision_note=?, job_id=?
               WHERE id=? AND status='pending'""",
            ("approved" if approved else "rejected", now(), admin_id, note, job_id, submission_id))
        if not result.rowcount:
            raise KeyError(submission_id)


def purge_submissions(today, keep_days=SUBMISSION_KEEP_DAYS):
    """Delete decided submissions (with the employer's contact details) keep_days after the decision.
    An approved job stays listed; only the submission record goes. Returns how many were deleted."""
    cutoff = (date.fromisoformat(today) - timedelta(days=keep_days)).isoformat()
    with connect() as conn:
        return conn.execute("DELETE FROM job_submissions WHERE status!='pending' AND decided_at < ?",
                            (cutoff,)).rowcount


def expire_jobs(today, sources_read=(), stale_days=EXPIRE_AFTER_DAYS):
    """Close listings that are over: shared jobs whose deadline has passed, and scraped jobs from one of
    sources_read (sources the latest check read without errors) that weren't in the feed for stale_days.
    Members' own saved jobs are never closed. Returns how many were closed."""
    cutoff = (date.fromisoformat(today) - timedelta(days=stale_days)).isoformat()
    sources_read = list(sources_read)
    absent = (f" OR (manual=0 AND source IN ({','.join('?' * len(sources_read))}) AND last_seen < ?)"
              if sources_read else "")
    with connect() as conn:
        return conn.execute(
            f"""UPDATE jobs SET listing_status='expired', expired_at=?
                WHERE listing_status='active' AND private=0
                  AND ((deadline!='' AND deadline < ?){absent})""",
            [today, today] + (sources_read + [cutoff] if sources_read else [])).rowcount


# The job's career fields as "it,health", and its tags as "level:internship,employment:summer", for rows read
# from jobs (alias j)
FIELD_IDS = ("(SELECT GROUP_CONCAT(field_id) FROM job_fields WHERE job_id = j.id) AS field_ids, "
             "(SELECT GROUP_CONCAT(kind || ':' || value) FROM job_tags WHERE job_id = j.id) AS tags")


def tags_of(row):
    """{'levels': [...], 'employment_types': [...], 'permits': [...]} from a row's tags column."""
    found = {key: [] for key in TAG_KINDS}
    by_kind = {kind: key for key, kind in TAG_KINDS.items()}
    for tag in (row.get("tags") or "").split(","):
        kind, _, value = tag.partition(":")
        if kind in by_kind and value:
            found[by_kind[kind]].append(value)
    return found


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def provision_admin(email):
    """Make user 1 the administrator with this email address. They sign in with a magic link."""
    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid administrator email address.")
    with connect() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE AND id!=1", (email,)).fetchone()
        if existing:
            raise ValueError("That email already belongs to another account.")
        conn.execute(
            """UPDATE users SET name=CASE WHEN name='' THEN ? ELSE name END, email=?,
               password_hash='', is_admin=1, is_active=1 WHERE id=1""",
            (email.split("@")[0], email),
        )
        return dict(conn.execute("SELECT id, name, email, is_admin FROM users WHERE id=1").fetchone())


def get_user(user_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT id, name, email, is_admin, is_active, preferences_json FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_email(email):
    with connect() as conn:
        row = conn.execute(
            """SELECT id, name, email, is_admin, is_active, preferences_json
               FROM users WHERE email=? COLLATE NOCASE""",
            (email.strip(),),
        ).fetchone()
        return dict(row) if row else None


def create_user(name, email, invite_token=None):
    """A new member account. With invite_token (invitation-only mode) the code must be valid and unused,
    and is used up in the same transaction."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        invite = None
        if invite_token is not None:
            invite = conn.execute(
                """SELECT id FROM invitations WHERE token_hash=? AND used_by IS NULL AND expires_at>?""",
                (_hash_token(invite_token), datetime.now(timezone.utc).isoformat(timespec="seconds")),
            ).fetchone()
            if not invite:
                raise ValueError("That invitation is invalid, expired or already used.")
        try:
            user_id = conn.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?,?,'',?)",
                (name.strip(), email.strip().lower(), now()),
            ).lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("An account with that email already exists.") from exc
        if invite:
            conn.execute(
                "UPDATE invitations SET used_by=?, used_at=? WHERE id=? AND used_by IS NULL",
                (user_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), invite["id"]),
            )
        return user_id


def create_login_link(token, email, name="", invite="", minutes=15):
    """Store a magic link (only its hash). name/invite are kept for links that create a new account."""
    expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    with connect() as conn:
        conn.execute("""INSERT INTO login_links (token_hash, email, name, invite, created_at, expires_at)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                     (_hash_token(token), email.strip().lower(), name.strip(), invite.strip(),
                      datetime.now(timezone.utc).isoformat(timespec="seconds"), expires.isoformat(timespec="seconds")))
    return expires


def use_login_link(token):
    """The link's email, name and invite if the link is valid, unused and unexpired; it is used up at once,
    so the same link can never sign in twice. None otherwise."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("""SELECT email, name, invite FROM login_links
                              WHERE token_hash=? AND used_at IS NULL AND expires_at>?""",
                           (_hash_token(token), datetime.now(timezone.utc).isoformat(timespec="seconds"))).fetchone()
        if not row:
            return None
        conn.execute("UPDATE login_links SET used_at=? WHERE token_hash=?",
                     (datetime.now(timezone.utc).isoformat(timespec="seconds"), _hash_token(token)))
        conn.execute("DELETE FROM login_links WHERE expires_at<?",            # tidy up old links
                     ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds"),))
        return dict(row)


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


def active_field_ids(default):
    """Every field chosen by at least one active account; accounts that haven't chosen get default."""
    fields = set()
    with connect() as conn:
        for row in conn.execute("SELECT preferences_json FROM users WHERE is_active=1"):
            try:
                chosen = json.loads(row["preferences_json"] or "{}").get("fields")
            except (ValueError, AttributeError):
                chosen = None
            fields.update(chosen if isinstance(chosen, list) and chosen else default)
    return sorted(fields or default)


def finnish_levels(prompt_version):
    """{job id: stored classification} for one prompt version."""
    with connect() as conn:
        rows = conn.execute("SELECT * FROM finnish_levels WHERE prompt_version=?", (prompt_version,)).fetchall()
    return {row["job_id"]: {
        "level": row["level"], "evidence": json.loads(row["evidence_json"]), "explanation_en": row["explanation"],
        "method": row["method"], "model": row["model"], "prompt_version": row["prompt_version"],
        "verified": bool(row["verified"]), "rejected_evidence": json.loads(row["rejected_json"]),
        "text_hash": row["text_hash"], "created_at": row["created_at"],
    } for row in rows}


def save_finnish_level(job_id, text_hash, result):
    """Store one classification (core.finnish.classify result) for a job and prompt version."""
    with connect() as conn:
        conn.execute("""INSERT OR REPLACE INTO finnish_levels (job_id, prompt_version, text_hash, level,
                        evidence_json, explanation, method, model, verified, rejected_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (job_id, result["prompt_version"], text_hash, result["level"],
                      json.dumps(result["evidence"], ensure_ascii=False), result.get("explanation_en") or "",
                      result["method"], result.get("model") or "", int(bool(result.get("verified", True))),
                      json.dumps(result.get("rejected_evidence") or [], ensure_ascii=False),
                      datetime.now(timezone.utc).isoformat(timespec="seconds")))


FINNISH_LEVELS = ("required", "preferred", "not_needed", "unclear")


def save_finnish_feedback(user_id, feedback):
    """One "Was this right?" answer. Stores the level shown, the vote, the student's correction and the
    quoted sentence (public ad text), so the pilot can measure accuracy on real ads."""
    with connect() as conn:
        conn.execute("""INSERT INTO finnish_feedback (user_id, created_at, job_id, method, prompt_version,
                        level_shown, vote, correct_level, evidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                     (user_id, now(), feedback.get("job_id"), feedback["method"], feedback.get("prompt_version", ""),
                      feedback["level_shown"], feedback["vote"], feedback.get("correct_level", ""),
                      feedback.get("evidence", "")))


def finnish_feedback_summary():
    """Counts per method and level shown: how often students said the result was right or wrong."""
    with connect() as conn:
        rows = conn.execute("""SELECT method, level_shown, vote, COUNT(*) AS n FROM finnish_feedback
                               GROUP BY method, level_shown, vote ORDER BY method, level_shown, vote""").fetchall()
    return [dict(row) for row in rows]


def delete_user(user_id):
    """Delete an account and everything personal in it, in one transaction.

    Deleted: CVs, applications, jobs they collected privately, prep answers, sessions, news reading state,
    feedback, the account.
    Kept: job listings the member shared with others (public ads, moved to the administrator account so they
    don't disappear for everyone else). The administrator account (id 1) owns shared data and can't be deleted."""
    if user_id == 1:
        raise ValueError("The administrator account owns the shared listings and can't be deleted.")
    with connect() as conn:
        for sql in ("DELETE FROM applications WHERE user_id=?",
                    "DELETE FROM prep_answers WHERE user_id=?",
                    "DELETE FROM checks WHERE user_id=?",
                    "DELETE FROM news_source_state WHERE user_id=?",
                    "DELETE FROM invitations WHERE created_by=?",
                    "UPDATE invitations SET used_by=NULL WHERE used_by=?",
                    "UPDATE news_items SET user_id=1 WHERE user_id=?",
                    "DELETE FROM tasks WHERE user_id=?",
                    "DELETE FROM documents WHERE user_id=?",
                    "DELETE FROM fit_evaluations WHERE user_id=?",
                    "DELETE FROM jobs WHERE user_id=? AND private=1",       # their own collected jobs go too
                    "UPDATE jobs SET user_id=1 WHERE user_id=?",              # shared ads stay for others
                    "DELETE FROM users WHERE id=?"):       # cascades: sessions, cvs, cv_imports, news state, feedback
            conn.execute(sql, (user_id,))


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
        folders = {}
        for row in rows:
            item = dict(row)
            source = item.pop("original_source")
            item["has_original"] = bool(source)
            item["content"] = json.loads(item.pop("content_json"))
            # Imported role CVs come in language pairs from one folder (roles/<slug>/cv-fi.tex, cv-en.tex)
            item["versions"] = folders.setdefault(source.rsplit("/", 1)[0], {}) if source else {}
            item["versions"][item["language"]] = item["id"]
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

def upsert_scraped(job, check_id, user_id=1, fields=None, meta=None):
    """Insert or refresh a scraped job. Returns True if it is new (never seen before).
    fields: its career field ids (scraper.classify_job); None leaves the stored ones as they are.
    meta: what the ad says (scraper.job_meta); None leaves the stored details as they are."""
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
            if fields is not None:
                _set_fields(conn, row["id"], fields)
            if meta is not None:
                _set_meta(conn, row["id"], meta)
            _set_keys(conn, row["id"])
            # back in the feed: open again unless its deadline has passed
            conn.execute("""UPDATE jobs SET listing_status='active', expired_at=''
                            WHERE id=? AND listing_status='expired' AND (deadline='' OR deadline >= ?)""",
                         (row["id"], today))
            return False
        duplicate = _duplicate_of(conn, job, meta, user_id)
        if duplicate:          # the same posting is already listed from another source: keep that one
            conn.execute("UPDATE jobs SET last_seen=? WHERE id=?", (today, duplicate))
            return False
        job_id = conn.execute("""INSERT INTO jobs (user_id, source, external_id, url, title, company, location,
                          posted, category, ad_text, first_check_id, first_seen, last_seen)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (user_id, job["source"], job["external_id"], job["url"], job["title"],
                      job["company"], job["location"], job["posted"], job["category"], description,
                      check_id, today, today)).lastrowid
        if fields is not None:
            _set_fields(conn, job_id, fields)
        if meta is not None:
            _set_meta(conn, job_id, meta)
        _set_keys(conn, job_id)
        return True


def add_manual(fields, user_id=1, field_ids=None, meta=None):
    """Add a job by hand. Shared (community) jobs are deduplicated across accounts by source and external id;
    private jobs carry the member's id in their external id, so each member has their own copy.
    field_ids: its career fields (scraper.classify_job). meta: what the ad says (scraper.job_meta)."""
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
            if field_ids is not None:
                _set_fields(conn, row["id"], field_ids)
            if meta is not None:
                _set_meta(conn, row["id"], meta)
            return row["id"]
        job_id = conn.execute(
            f"""INSERT INTO jobs (user_id, source, external_id, {', '.join(cols)}, manual, private,
                  first_check_id, first_seen, last_seen)
                VALUES (?,?,?,{','.join('?' * len(cols))},1,?,NULL,?,?)""",
            [user_id, fields["source"], fields["external_id"]] + [vals[c] for c in cols]
            + [1 if fields.get("private") else 0, today, today]
        ).lastrowid
        if field_ids is not None:
            _set_fields(conn, job_id, field_ids)
        if meta is not None:
            _set_meta(conn, job_id, meta)
        _set_keys(conn, job_id)
        return job_id


def list_jobs(user_id=1):
    """Shared listings with only the requesting user's application status."""
    latest = latest_check(1)
    latest_id = latest["id"] if latest else -1
    with connect() as conn:
        rows = conn.execute("""
            SELECT j.*, a.id AS app_id, a.status, a.cv_role AS app_cv_role,
                   (j.first_check_id = ?) AS is_new, """ + FIELD_IDS + """
            FROM jobs j LEFT JOIN applications a ON a.job_id = j.id AND a.user_id = ?
            ORDER BY j.posted DESC, j.id DESC""", (latest_id, user_id)).fetchall()
        return [dict(r) for r in rows]

def get_job(job_id, user_id=1):
    with connect() as conn:
        row = conn.execute(f"SELECT j.*, {FIELD_IDS} FROM jobs j WHERE j.id=?", (job_id,)).fetchone()
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


# ---------------------------------------------------------------- news (the former forestry News desk)
# The page and its feeds are removed; the tables stay so stories members saved are kept in their data export.

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


# ---------------------------------------------------------------- prep answers (the administrator's edits, per job type)

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
                   j.contact_name, j.contact_phone, j.source, j.user_id AS job_owner, j.private, """ + FIELD_IDS + """
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


# ---------------------------------------------------------------- fit evaluations (cached per job, CV and version)

def save_fit(user_id, job_id, cv_id, cache_key, ad_hash, cv_hash, result):
    with connect() as conn:
        conn.execute("""INSERT OR REPLACE INTO fit_evaluations (user_id, job_id, cv_id, cache_key, ad_hash, cv_hash,
                          method, suitability, result_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (user_id, job_id, cv_id, cache_key, ad_hash, cv_hash, result["method"], result["suitability"],
                      json.dumps(result, ensure_ascii=False), now()))


def _fit_row(row):
    if not row:
        return None
    item = dict(row)
    item["result"] = json.loads(item.pop("result_json"))
    return item


def cached_fit(user_id, job_id, cache_key):
    with connect() as conn:
        return _fit_row(conn.execute("SELECT * FROM fit_evaluations WHERE user_id=? AND job_id=? AND cache_key=?",
                                     (user_id, job_id, cache_key)).fetchone())


def latest_fit(user_id, job_id):
    with connect() as conn:
        return _fit_row(conn.execute("""SELECT * FROM fit_evaluations WHERE user_id=? AND job_id=?
                                        ORDER BY id DESC LIMIT 1""", (user_id, job_id)).fetchone())


def latest_fits(user_id):
    """job id -> the newest evaluation's summary, for the Jobs list."""
    with connect() as conn:
        rows = conn.execute("""SELECT f.job_id, f.cv_id, f.suitability, f.method, f.ad_hash, f.cv_hash
                               FROM fit_evaluations f
                               WHERE f.user_id=? AND f.id = (SELECT MAX(id) FROM fit_evaluations
                                                             WHERE user_id=f.user_id AND job_id=f.job_id)""",
                            (user_id,)).fetchall()
        return {r["job_id"]: dict(r) for r in rows}


def list_fits(user_id):
    with connect() as conn:
        return [_fit_row(r) for r in conn.execute(
            "SELECT * FROM fit_evaluations WHERE user_id=? ORDER BY id", (user_id,)).fetchall()]


# ---------------------------------------------------------------- background tasks (a small queue in SQLite)

def enqueue_task(user_id, kind, key, payload):
    """Queue a task, unless the same one (same user, kind and key) is already waiting or running.
    Returns (task id, True if newly queued)."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("""SELECT id FROM tasks WHERE user_id=? AND kind=? AND key=? AND status IN ('queued','running')""",
                           (user_id, kind, key)).fetchone()
        if row:
            return row["id"], False
        task_id = conn.execute("""INSERT INTO tasks (user_id, kind, key, payload_json, created_at)
                                  VALUES (?,?,?,?,?)""",
                               (user_id, kind, key, json.dumps(payload), now())).lastrowid
        return task_id, True


def claim_task():
    """The oldest queued task, marked running in the same transaction so two workers never take the same one."""
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return None
        conn.execute("UPDATE tasks SET status='running', started_at=? WHERE id=?", (now(), row["id"]))
        task = dict(row)
        task["payload"] = json.loads(task.pop("payload_json"))
        return task


def finish_task(task_id, error=""):
    with connect() as conn:
        conn.execute("UPDATE tasks SET status=?, error=?, finished_at=? WHERE id=?",
                     ("failed" if error else "done", error[:300], now(), task_id))


def get_task(task_id, user_id):
    with connect() as conn:
        row = conn.execute("SELECT id, kind, key, status, error, created_at, finished_at FROM tasks WHERE id=? AND user_id=?",
                           (task_id, user_id)).fetchone()
        return dict(row) if row else None


def latest_task(user_id, kind, key_prefix):
    with connect() as conn:
        row = conn.execute("""SELECT id, kind, key, status, error, created_at, finished_at FROM tasks
                              WHERE user_id=? AND kind=? AND key LIKE ? ORDER BY id DESC LIMIT 1""",
                           (user_id, kind, key_prefix + "%")).fetchone()
        return dict(row) if row else None


def requeue_interrupted_tasks():
    """At start-up: tasks left 'running' by a stopped server go back in the queue."""
    with connect() as conn:
        return conn.execute("UPDATE tasks SET status='queued', started_at=NULL WHERE status='running'").rowcount


def delete_old_tasks(days=30):
    with connect() as conn:
        conn.execute("DELETE FROM tasks WHERE status IN ('done','failed') AND finished_at<?",
                     ((datetime.now() - timedelta(days=days)).isoformat(timespec="seconds"),))


# ---------------------------------------------------------------- application documents (letter + email per language)

def _document_row(row):
    if not row:
        return None
    item = dict(row)
    for key in ("letter", "email", "checks"):
        item[key] = json.loads(item.pop(f"{key}_json"))
    item["edited"] = bool(item["edited"])
    return item


def save_documents(user_id, job_id, language, source_cv_id, tailored_cv_id, cache_key, letter, email, checks, method):
    """Store (or replace) the documents for one job and language."""
    with connect() as conn:
        conn.execute("""INSERT INTO documents (user_id, job_id, language, source_cv_id, tailored_cv_id, cache_key,
                          letter_json, email_json, checks_json, method, edited, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)
                        ON CONFLICT (user_id, job_id, language) DO UPDATE SET
                          source_cv_id=excluded.source_cv_id, tailored_cv_id=excluded.tailored_cv_id,
                          cache_key=excluded.cache_key, letter_json=excluded.letter_json, email_json=excluded.email_json,
                          checks_json=excluded.checks_json, method=excluded.method, edited=0, updated_at=excluded.updated_at""",
                     (user_id, job_id, language, source_cv_id, tailored_cv_id, cache_key,
                      json.dumps(letter, ensure_ascii=False), json.dumps(email, ensure_ascii=False),
                      json.dumps(checks, ensure_ascii=False), method, now(), now()))


def get_documents(user_id, job_id, language=None):
    with connect() as conn:
        if language:
            return _document_row(conn.execute("SELECT * FROM documents WHERE user_id=? AND job_id=? AND language=?",
                                              (user_id, job_id, language)).fetchone())
        return [_document_row(r) for r in conn.execute(
            "SELECT * FROM documents WHERE user_id=? AND job_id=? ORDER BY language", (user_id, job_id)).fetchall()]


def get_document(document_id, user_id):
    with connect() as conn:
        return _document_row(conn.execute("SELECT * FROM documents WHERE id=? AND user_id=?",
                                          (document_id, user_id)).fetchone())


def update_document(document_id, user_id, letter, email):
    with connect() as conn:
        result = conn.execute("""UPDATE documents SET letter_json=?, email_json=?, edited=1, updated_at=?
                                 WHERE id=? AND user_id=?""",
                              (json.dumps(letter, ensure_ascii=False), json.dumps(email, ensure_ascii=False), now(),
                               document_id, user_id))
        if not result.rowcount:
            raise KeyError(document_id)


def list_all_documents(user_id):
    with connect() as conn:
        return [_document_row(r) for r in conn.execute("SELECT * FROM documents WHERE user_id=? ORDER BY id",
                                                       (user_id,)).fetchall()]


def tailored_cv_ids(user_id):
    """CVs JobDesk wrote for one job (they are never the member's main CV)."""
    with connect() as conn:
        return {r[0] for r in conn.execute("SELECT tailored_cv_id FROM documents WHERE user_id=? AND tailored_cv_id IS NOT NULL",
                                           (user_id,))}
