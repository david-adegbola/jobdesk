"""Facts about the administrator, read from facts.json in the CV repository (owner tools only).

facts.json is generated there from CV-RULES.md (the authority) by `python3 site/facts.py`, and the
CV repo's GitHub Action fails if the two differ. JobDesk only reads the JSON.
"""

import json
import sys

from config import FACTS_FILE

REQUIRED = ("name", "phone", "email", "location", "not_held", "not_confirmed", "public_base")


class FactsUnavailable(Exception):
    """facts.json can't be read. Routes that need it answer 503 instead of stopping the server."""


def load():
    """Return (facts, warning). warning is None when facts.json has every field the app uses.
    Raises FactsUnavailable when the file is missing or isn't valid JSON."""
    try:
        facts = json.loads(FACTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        # The full path goes to the server log only, not to the browser
        print(f"Could not read {FACTS_FILE} ({e}). Set JOBDESK_CV_REPO to the CV repository clone.",
              file=sys.stderr)
        raise FactsUnavailable(
            "The CV facts file (facts.json) could not be read on this server. "
            "Set JOBDESK_CV_REPO to the CV repository clone.") from e
    if not isinstance(facts, dict):
        raise FactsUnavailable("The CV facts file (facts.json) is not a JSON object.")
    missing = [k for k in REQUIRED if k not in facts]
    if missing:
        return facts, f"facts.json is missing {', '.join(missing)}. Run python3 site/facts.py in the CV repo."
    return facts, None
