"""Career taxonomy: the fields members choose and search by, and the roles (occupations) inside them.

Both are data, in taxonomy/fields.json and taxonomy/roles.json, so a field or role is added without code.
Structure follows ISCO-08 (the base of Statistics Finland's Ammattiluokitus 2010): each field lists the ISCO
groups it covers and each role its ISCO-08 unit group; roles can also carry an ESCO occupation URI.

classify(job, profile_fields) decides which fields a job belongs to, from three signals:
    1. role title patterns: the job title matches a role, so the job is in that role's field;
    2. profile_fields: fields whose keyword profile (fields/*.json, the older rules) the caller found relevant;
    3. the job's old category ("Forestry", "Warehouse" ...) through the fields' legacy_categories.
A job can be in several fields. Standard library only.
"""

import json
import re
from pathlib import Path

ID = re.compile(r"[a-z][a-z0-9_]{1,40}")
ISCO = re.compile(r"\d{1,4}")


class TaxonomyError(ValueError):
    """taxonomy/*.json is missing something or has an invalid value."""


class Taxonomy:
    def __init__(self, fields, roles):
        self.fields = fields                               # in display order
        self.by_id = {f["id"]: f for f in fields}
        self.roles = roles
        self.roles_by_id = {r["id"]: r for r in roles}
        self._patterns = [(r, re.compile(r["title"], re.I)) for r in roles]
        self._patterns_by_id = {r["id"]: pattern for r, pattern in self._patterns}
        self._legacy = {}
        for f in fields:
            for category in f.get("legacy_categories", []):
                self._legacy.setdefault(category.lower(), []).append(f["id"])

    def field_ids(self):
        return [f["id"] for f in self.fields]

    def name(self, field_id, language="en"):
        field = self.by_id.get(field_id)
        return (field.get(language) or field["en"]) if field else field_id

    def roles_for_title(self, title):
        """Ids of the roles whose title pattern matches, in roles.json order."""
        return [r["id"] for r, pattern in self._patterns if pattern.search(title or "")]

    def roles_for_query(self, query):
        """Roles a search names in English or Finnish: the query is part of the role's name ("nurse" ->
        Registered nurse) or the role's title pattern recognises it ("sairaanhoitaja"). A search then also
        finds jobs titled in the other language. Queries under 3 letters name no role."""
        query = " ".join((query or "").lower().split())
        if len(query) < 3:
            return []
        return [r["id"] for r, pattern in self._patterns
                if query in r["en"].lower() or query in r["fi"].lower() or pattern.search(query)]

    def title_matches_roles(self, title, role_ids):
        return any(self._patterns_by_id[r].search(title or "") for r in role_ids if r in self._patterns_by_id)

    def legacy_fields(self, category):
        return list(self._legacy.get((category or "").strip().lower(), []))

    def classify(self, job, profile_fields=()):
        """Field ids for a job (see the module docstring), in display order. Empty when nothing matches."""
        found = {self.roles_by_id[r]["field"] for r in self.roles_for_title(job.get("title"))}
        found.update(f for f in profile_fields if f in self.by_id)
        found.update(self.legacy_fields(job.get("category")))
        return [f for f in self.field_ids() if f in found]


def _check_names(item, where):
    for language in ("en", "fi"):
        if not isinstance(item.get(language), str) or not item[language].strip():
            raise TaxonomyError(f"{where}: needs an {language!r} name")


def load(directory):
    """The Taxonomy in directory (taxonomy/). Raises TaxonomyError with the place of the problem."""
    directory = Path(directory)
    try:
        fields_doc = json.loads((directory / "fields.json").read_text(encoding="utf-8"))
        roles_doc = json.loads((directory / "roles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TaxonomyError(f"can't read the taxonomy in {directory}: {error}") from error
    fields, seen = [], set()
    for i, f in enumerate(fields_doc.get("fields") or []):
        where = f"fields.json field {i + 1} ({f.get('id')!r})"
        if not isinstance(f.get("id"), str) or not ID.fullmatch(f["id"]) or f["id"] in seen:
            raise TaxonomyError(f"{where}: needs a unique id of lower-case letters, digits and _")
        seen.add(f["id"])
        _check_names(f, where)
        if not isinstance(f.get("order"), int):
            raise TaxonomyError(f"{where}: needs a whole-number order")
        if not f.get("isco") or not all(isinstance(c, str) and ISCO.fullmatch(c) for c in f["isco"]):
            raise TaxonomyError(f"{where}: isco must be a list of ISCO-08 codes (1-4 digits)")
        if not all(isinstance(c, str) for c in f.get("legacy_categories", [])):
            raise TaxonomyError(f"{where}: legacy_categories must be text")
        fields.append(f)
    if not fields:
        raise TaxonomyError("fields.json has no fields")
    fields.sort(key=lambda f: (f["order"], f["id"]))
    roles, role_ids = [], set()
    for i, r in enumerate(roles_doc.get("roles") or []):
        where = f"roles.json role {i + 1} ({r.get('id')!r})"
        if not isinstance(r.get("id"), str) or not ID.fullmatch(r["id"]) or r["id"] in role_ids:
            raise TaxonomyError(f"{where}: needs a unique id of lower-case letters, digits and _")
        role_ids.add(r["id"])
        _check_names(r, where)
        if r.get("field") not in seen:
            raise TaxonomyError(f"{where}: field {r.get('field')!r} isn't in fields.json")
        if not isinstance(r.get("isco"), str) or not re.fullmatch(r"\d{4}", r["isco"]):
            raise TaxonomyError(f"{where}: isco must be an ISCO-08 unit group (4 digits)")
        if r.get("esco") is not None and not (isinstance(r["esco"], str) and r["esco"].startswith("http")):
            raise TaxonomyError(f"{where}: esco must be an ESCO occupation URI or null")
        try:
            re.compile(r.get("title") or "", re.I)
        except re.error as error:
            raise TaxonomyError(f"{where}: invalid title pattern ({error})") from error
        if not r.get("title"):
            raise TaxonomyError(f"{where}: needs a title pattern")
        roles.append(r)
    return Taxonomy(fields, roles)
