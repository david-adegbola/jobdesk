"""Importer adapters: sources read through an API that needs credentials, behind one small interface.

An adapter has
    id, name      the source id (sources.json) and the name stored on its jobs
    sector        "public" | "private" | "third" | "" for all its jobs (core/jobmeta.py), when known
    attribution   text that must be shown with its jobs (an API's terms may require a credit line)
    remove_missing_after_days   how soon a posting gone from the API is closed (terms may say "at once")
    enabled()     True when it is switched on and has its credentials
    read()        yields postings: {"id", "url", "title", "company", "location", "posted", "description",
                  "deadline"}; it raises ImporterError when the source can't be read

scraper.run() reads every enabled adapter after the RSS feeds, and treats their postings like the feeds' ones
(career fields, details, dedupe, expiry). Feeds stay in scraper.py; only credentialed APIs live here.
"""

import json
import os
import urllib.parse
import urllib.request


class ImporterError(RuntimeError):
    """The source answered with an error or something that isn't a list of postings."""


class Adapter:
    id = ""
    name = ""
    sector = ""
    attribution = ""
    remove_missing_after_days = 7

    def enabled(self):
        return False

    def read(self):
        return iter(())


class TyomarkkinatoriAdapter(Adapter):
    """Työmarkkinatori's search API (hakurajapinta), run by KEHA-keskus.

    Terms (updated 12.3.2026, read 2026-11-24; see sources.json "not_added"): access is granted to an
    organisation with a Y-tunnus after KEHA-keskus approves the käyttöönottoilmoitus; ads may be shown in our
    own service with the credit "(Lähde: Työmarkkinatorin asiakastietojärjestelmä)"; ads must be kept current
    and deleted ads removed at once; ads may not be passed to third parties or used for marketing.

    Off until both JOBDESK_TMT_API_URL and JOBDESK_TMT_API_KEY are set (test credentials first). The request
    and the field names in FIELD_MAP follow the usual shape of such APIs and MUST be checked against the API
    documentation that comes with the credentials before this is switched on in production.
    """
    id = "tyomarkkinatori"
    name = "Työmarkkinatori"
    attribution = "(Lähde: Työmarkkinatorin asiakastietojärjestelmä)"
    remove_missing_after_days = 1       # "deleted ads removed at once": closed within a day (two checks a day)
    PAGE_SIZE = 100
    MAX_PAGES = 50
    # our key -> candidate keys in the API's JSON, first found wins (TO CONFIRM against the API documentation)
    FIELD_MAP = {
        "id": ("id", "ilmoitusnumero", "jobAdvertisementId"),
        "title": ("title", "tehtavanimi", "otsikko"),
        "company": ("employerName", "tyonantajanNimi", "tyonantaja"),
        "location": ("municipality", "kunta", "sijainti", "location"),
        "posted": ("publishDate", "ilmoituspaivamaara", "julkaisupaiva"),
        "deadline": ("applicationDeadline", "hakuPaattyy", "hakuaikaPaattyy"),
        "description": ("description", "kuvausteksti", "kuvaus"),
        "url": ("url", "linkki", "applicationUrl"),
    }
    LIST_KEYS = ("results", "items", "ilmoitukset", "data")

    def __init__(self, environ=None, opener=None):
        environ = os.environ if environ is None else environ
        self.api_url = (environ.get("JOBDESK_TMT_API_URL") or "").strip()
        self.api_key = (environ.get("JOBDESK_TMT_API_KEY") or "").strip()
        self.opener = opener or urllib.request.urlopen

    def enabled(self):
        return bool(self.api_url and self.api_key) and self.api_url.startswith("https://")

    @classmethod
    def map_posting(cls, item):
        """One API record as a posting, or None when it has no id or title."""
        def pick(key):
            for candidate in cls.FIELD_MAP[key]:
                value = item.get(candidate)
                if isinstance(value, dict):                 # e.g. {"fi": "...", "sv": "...", "en": "..."}
                    value = value.get("fi") or value.get("en") or value.get("sv") or next(iter(value.values()), "")
                if isinstance(value, list):
                    value = ", ".join(str(v.get("fi") if isinstance(v, dict) else v) for v in value if v)
                if value not in (None, ""):
                    return str(value).strip()
            return ""
        posting = {key: pick(key) for key in cls.FIELD_MAP}
        for key in ("posted", "deadline"):
            posting[key] = posting[key][:10]               # ISO date part
        if posting["url"] and urllib.parse.urlsplit(posting["url"]).scheme not in ("http", "https"):
            posting["url"] = ""                            # a link we show, never fetch: a scheme check is enough
        return posting if posting["id"] and posting["title"] else None

    def _page(self, page):
        query = urllib.parse.urlencode({"page": page, "pageSize": self.PAGE_SIZE})
        request = urllib.request.Request(f"{self.api_url}{'&' if '?' in self.api_url else '?'}{query}", headers={
            "Accept": "application/json", "Authorization": f"Bearer {self.api_key}", "User-Agent": "JobDesk"})
        try:
            with self.opener(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as error:
            raise ImporterError(f"Työmarkkinatori: {error}") from error
        if isinstance(data, list):
            return data
        for key in self.LIST_KEYS:
            if isinstance(data, dict) and isinstance(data.get(key), list):
                return data[key]
        raise ImporterError("Työmarkkinatori answered without a list of ads")

    def read(self):
        for page in range(self.MAX_PAGES):
            items = self._page(page)
            for item in items:
                posting = self.map_posting(item) if isinstance(item, dict) else None
                if posting:
                    yield posting
            if len(items) < self.PAGE_SIZE:
                return


def adapters(environ=None):
    return [TyomarkkinatoriAdapter(environ)]


def enabled_adapters(environ=None):
    return [a for a in adapters(environ) if a.enabled()]
