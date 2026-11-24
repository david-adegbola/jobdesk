"""Where JobDesk finds things. Everything comes from environment variables (see .env.example);
the defaults suit a local checkout, and the server sets them in deploy/jobdesk.env and the
uncommitted /srv/jobdesk/private.env.

JOBDESK_CV_REPO           clone of the CV repository (default: ../CV next to this repo). Only its
                          files are read (roles/, facts.json, shared/cv-style.sty); none of its code is run.
JOBDESK_DATA              folder for jobdesk.db (default: data/ in this repo, git-ignored)
JOBDESK_HOST              address to listen on (default 127.0.0.1; on the server Caddy sits in front)
JOBDESK_PORT              port (default 8765)
JOBDESK_SECURE_COOKIE     1 behind HTTPS so authentication cookies are sent only over TLS.
JOBDESK_OWNER_DIR         the administrator's private folder (default: owner/ in this repo, git-ignored):
                          profile.json for the owner-only tools and an optional prep/ folder.
JOBDESK_PREP_DIR          prep templates (default: <owner dir>/prep when it exists, else prep/ in this repo)
JOBDESK_CV_TEMPLATE_OWNER the name written in the shared LaTeX template's footer. Member PDFs replace
                          it with the member's own name; when unset, member PDFs are not built.
JOBDESK_DEFAULT_FIELDS    fields for members who haven't chosen any (default forestry)
JOBDESK_OPEN_SIGNUP       1 (default): anyone can create an account with their email; 0: invitation codes only
JOBDESK_PUBLIC_URL        the site's address, used in sign-in links (default http://localhost:8765)
JOBDESK_EMAIL_BACKEND     log (default, development), smtp or memory; see mailer.py
JOBDESK_AI_DAILY_LIMIT    AI checks per member per day on the Shortlist page (default 200)
JOBDESK_ENABLE_DUUNITORI  1 to read Duunitori search pages (default 0: its robots.txt disallows
                          generic crawlers, and the robots.txt check would skip it anyway).
"""

import os
from pathlib import Path

APP = Path(__file__).resolve().parent
CV_REPO = Path(os.environ.get("JOBDESK_CV_REPO") or APP.parent / "CV").resolve()
ROLES_DIR = CV_REPO / "roles"
FACTS_FILE = CV_REPO / "facts.json"
REDIRECTS_FILE = CV_REPO / "site" / "redirects.json"   # merged roles: old slug -> new slug
DATA_DIR = Path(os.environ.get("JOBDESK_DATA") or APP / "data").resolve()
HOST = os.environ.get("JOBDESK_HOST", "127.0.0.1")
PORT = int(os.environ.get("JOBDESK_PORT", "8765"))
SECURE_COOKIE = os.environ.get("JOBDESK_SECURE_COOKIE", "0") == "1"

OWNER_DIR = Path(os.environ.get("JOBDESK_OWNER_DIR") or APP / "owner").resolve()
OWNER_PROFILE_FILE = OWNER_DIR / "profile.json"
PREP_DIR = Path(os.environ.get("JOBDESK_PREP_DIR")
                or (OWNER_DIR / "prep" if (OWNER_DIR / "prep").is_dir() else APP / "prep")).resolve()
CV_TEMPLATE_OWNER = os.environ.get("JOBDESK_CV_TEMPLATE_OWNER", "").strip()
FIELDS_DIR = APP / "fields"                 # field profiles (forestry, IT, ...): JSON, see core/fields.py
SOURCES_FILE = APP / "sources.json"         # job sources, their fields and robots.txt/terms notes
# Fields for members who haven't chosen yet (comma-separated ids; the pilot asks everyone on first login)
DEFAULT_FIELDS = [f.strip() for f in os.environ.get("JOBDESK_DEFAULT_FIELDS", "forestry").split(",") if f.strip()]
ENABLE_DUUNITORI = os.environ.get("JOBDESK_ENABLE_DUUNITORI", "0") == "1"
# Sign-up: anyone with an email address (1, default), or invitation codes only (0, e.g. for a closed pilot)
OPEN_SIGNUP = os.environ.get("JOBDESK_OPEN_SIGNUP", "1") == "1"
# The address in sign-in links (no trailing slash), e.g. https://jobdesk.example.fi
PUBLIC_URL = os.environ.get("JOBDESK_PUBLIC_URL", "http://localhost:8765").rstrip("/")
# Pilot cost guard: AI checks per member per day on the Shortlist page
AI_DAILY_LIMIT = int(os.environ.get("JOBDESK_AI_DAILY_LIMIT", "200"))
