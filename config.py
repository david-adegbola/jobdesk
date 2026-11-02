"""Where Woodesk finds things. The defaults suit David's Mac; the server sets them in deploy/jobdesk.env.

JOBDESK_CV_REPO  clone of the public cv repo (default: ../CV next to this repo). Only its files are
                 read (roles/, facts.json); none of its code is run.
JOBDESK_DATA     folder for jobdesk.db (default: data/ in this repo, git-ignored)
JOBDESK_HOST     address to listen on (default 127.0.0.1; on the server Caddy sits in front)
JOBDESK_PORT     port (default 8765)
JOBDESK_SECURE_COOKIE Set to 1 behind HTTPS so authentication cookies are sent only over TLS.
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
