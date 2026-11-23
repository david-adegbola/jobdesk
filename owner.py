"""The administrator's private profile, used only by the owner tools (the Claude Code prompt
builder and the Prep page).

These tools were written for one person's CV repository and work history. Those details now live
in <JOBDESK_OWNER_DIR>/profile.json, which is git-ignored, instead of in the code. When the file
is missing the owner tools answer with a clear error (HTTP 503) and the rest of JobDesk works as
before. owner_profile.example.json in the repo root shows every field.
"""

import json

import config

REQUIRED = ("cv_repo", "public_cv_base")


class OwnerProfileMissing(Exception):
    """The owner profile is missing or incomplete, so the owner tools are switched off."""


def _read():
    try:
        data = json.loads(config.OWNER_PROFILE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load():
    """The full profile. Raises OwnerProfileMissing when it can't be used."""
    data = _read()
    if data is None:
        raise OwnerProfileMissing(
            "The owner tools are not set up on this server: owner/profile.json is missing "
            "(see owner_profile.example.json).")
    missing = [key for key in REQUIRED if not isinstance(data.get(key), str) or not data[key].strip()]
    if missing:
        raise OwnerProfileMissing(f"owner/profile.json is missing {', '.join(missing)}.")
    return data


def get(key, default=""):
    """One optional value, or default when the profile or the value is missing."""
    data = _read() or {}
    value = data.get(key)
    return value if isinstance(value, str) and value.strip() else default
