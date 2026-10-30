"""Facts about David, read from facts.json in the cv repo.

facts.json is generated there from CV-RULES.md (the authority) by `python3 site/facts.py`, and the
cv repo's GitHub Action fails if the two differ. JobDesk only reads the JSON.
"""

import json

from config import FACTS_FILE

REQUIRED = ("name", "phone", "email", "location", "not_held", "not_confirmed", "public_base")


def load():
    """Return (facts, warning). warning is None when facts.json has every field the app uses."""
    try:
        facts = json.loads(FACTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"Could not read {FACTS_FILE} ({e}). Set JOBDESK_CV_REPO to the cv repo clone.")
    missing = [k for k in REQUIRED if k not in facts]
    if missing:
        return facts, f"facts.json is missing {', '.join(missing)}. Run python3 site/facts.py in the cv repo."
    return facts, None
