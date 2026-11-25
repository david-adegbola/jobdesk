"""Finding the same job posting when it comes from more than one source.

Two keys, checked in this order:
    canonical_url(url)   the posting's address written one way (core/jobpage.py: https, no www, no tracking
                         parameters, no trailing slash). Same address = same posting.
    fingerprint(job)     "fp:<title>|<employer>|<municipality>", each normalised: lower case, punctuation and
                         gender markers ("(m/f)", "(m/n/x)") removed, company forms (Oy, Ab, Ltd ...) dropped.
                         Used when the addresses differ (a state portal and the employer's own feed). Empty
                         when the title or both the employer and place are missing, so vague jobs never merge.
"""

import re

from core.jobpage import canonical_url  # noqa: F401 (re-exported)

_GENDER = re.compile(r"\((?:[mfnwdx]\s*/\s*)+[mfnwdx]\)|\b[mfn]/[mfn](?:/[mfnx])?\b", re.I)
_COMPANY_FORMS = re.compile(r"\b(?:oy|oyj|ab|abp|ltd|limited|inc|gmbh|plc|llc|ky|tmi|ry|r\.y)\b\.?", re.I)
_NON_WORD = re.compile(r"[^\wåäö]+", re.I)


def _norm(text, company=False):
    text = _GENDER.sub(" ", text or "")
    if company:
        text = _COMPANY_FORMS.sub(" ", text)
    return " ".join(_NON_WORD.sub(" ", text.lower()).split())


def fingerprint(title, company="", municipality_code=""):
    title, company = _norm(title), _norm(company, company=True)
    if not title or not (company or municipality_code):
        return ""
    return f"fp:{title}|{company}|{municipality_code or ''}"
