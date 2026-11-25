"""Finnish municipalities (kunnat) and regions (maakunnat): the official list and matching job locations to it.

The list is taxonomy/places.json, from Statistics Finland's classifications (Kunnat and Maakunnat, CC BY 4.0;
the file names its source and year). Update it each January when the classifications change.

match(location) reads a job's location text ("00100 Helsinki", "Espoo / Vantaa", "Tampereella", "Pohjois-Karjala",
"Esbo") and returns (municipality_code, region_code). A region name alone gives ("", region_code); nothing
recognised gives ("", ""). The first place named wins. Standard library only.
"""

import json
import re
from pathlib import Path

PLACES_FILE = Path(__file__).resolve().parent.parent / "taxonomy" / "places.json"

# Finnish local-case endings: Tampereella, Oulussa, Espoossa, Turusta, Lahteen ...
_ENDINGS = ("ssa", "ssä", "sta", "stä", "lla", "llä", "lta", "ltä", "lle", "seen", "hin", "een", "n")
_SPLIT = re.compile(r"[,;/|()\n]+|\s+(?:ja|and|och|tai|or)\s+|\s+[-–]\s+")
_POSTCODE = re.compile(r"\b\d{5}\b")


class Places:
    def __init__(self, doc):
        self.regions = doc["regions"]
        self.municipalities = doc["municipalities"]
        self.region_by_code = {r["code"]: r for r in self.regions}
        self.municipality_by_code = {m["code"]: m for m in self.municipalities}
        self._municipality = {}
        for m in self.municipalities:
            for name in (m["fi"], m["sv"]):
                self._municipality.setdefault(name.lower(), m["code"])
        self._region = {}
        for r in self.regions:
            for name in (r["fi"], r["sv"], r["en"]):
                self._region.setdefault(name.lower(), r["code"])
        # Stems for inflected Finnish forms, from names ending in a vowel or -nen ("Tampere" -> "tamperee-",
        # "Kotka" -> "kotka-"); consonant gradation (Helsinki -> Helsingissä) is listed in _GRADATION
        self._stems = {}
        for m in self.municipalities:
            name = m["fi"].lower()
            if " " not in name and len(name) >= 4:
                self._stems.setdefault(name, m["code"])
                self._stems.setdefault(name + "e" if name.endswith("e") else name, m["code"])
        for stem, name in _GRADATION.items():
            code = self._municipality.get(name)
            if code:
                self._stems[stem] = code

    def region_of(self, municipality_code):
        m = self.municipality_by_code.get(municipality_code)
        return m["region"] if m else ""

    def name(self, code, language="fi"):
        """The name of a municipality (3-digit code) or region (2-digit code)."""
        place = self.municipality_by_code.get(code) or self.region_by_code.get(code)
        if not place:
            return ""
        return place.get(language) or place["fi"]

    def _lookup(self, part):
        part = _POSTCODE.sub(" ", part).strip(" .:-–").lower()
        part = re.sub(r"\s+", " ", part)
        if not part:
            return "", ""
        if part in self._municipality:
            code = self._municipality[part]
            return code, self.region_of(code)
        if part in self._region:
            return "", self._region[part]
        for word in reversed(part.split(" ")):         # "Helsinki, Kamppi" or "toimipaikka Espoo"
            if word in self._municipality:
                code = self._municipality[word]
                return code, self.region_of(code)
            for ending in _ENDINGS:
                if word.endswith(ending) and word[: -len(ending)] in self._stems:
                    code = self._stems[word[: -len(ending)]]
                    return code, self.region_of(code)
        return "", ""

    def towns(self, location):
        """(Finnish municipality codes named, in order; True when some part names no Finnish place, e.g. a
        posting that also lists 'West Perth WA 6005, Australia')."""
        codes, elsewhere = [], False
        for part in _SPLIT.split(location or ""):
            if not part.strip():
                continue
            municipality, region = self._lookup(part)
            if municipality and municipality not in codes:
                codes.append(municipality)
            elif not municipality and not region and part.strip().lower() not in ("finland", "suomi", "remote", "etätyö"):
                elsewhere = True
        return codes, elsewhere

    def match(self, location):
        first_region = ""
        for part in _SPLIT.split(location or ""):
            municipality, region = self._lookup(part)
            if municipality:
                return municipality, region
            first_region = first_region or region
        return "", first_region


# Common towns whose inflected stem changes (astevaihtelu): stem -> nominative
_GRADATION = {
    "helsingi": "helsinki", "turu": "turku", "lahde": "lahti", "lahte": "lahti",
    "lappeenranna": "lappeenranta", "seinäjoe": "seinäjoki", "rovanieme": "rovaniemi",
    "nurmijärve": "nurmijärvi", "kirkkonumme": "kirkkonummi", "ylöjärve": "ylöjärvi", "siilinjärve": "siilinjärvi",
    "kemijärve": "kemijärvi", "kangasala": "kangasala", "lempäälä": "lempäälä", "kaarina": "kaarina",
}


_cache = {}


def load(path=PLACES_FILE):
    path = Path(path)
    if path not in _cache:
        _cache[path] = Places(json.loads(path.read_text(encoding="utf-8")))
    return _cache[path]
