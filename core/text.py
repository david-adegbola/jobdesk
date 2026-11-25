"""Word helpers shared by matching, skills and ranking: tokens, a crude Finnish-friendly stem and
word_matches, which lets Finnish case endings and compounds still match.

Moved here unchanged from match.py (which re-exports them), so the Flask app can use them without
the rest of JobDesk.
"""

import re

WORD = re.compile(r"[a-zåäö0-9][a-zåäö0-9-]*[a-zåäö0-9]|[a-zåäö]", re.I)
STOPWORDS = set("""
ja tai sekä on ole olen olet ovat oli myös kanssa joka jotka jossa että kun mutta niin kuin
the and or of to in for on with at by an a as is are be from this that your our you we
työ työt työn töitä työssä työhön tehtävä tehtäviin tehtävät haemme etsimme hae oy ab ltd
cv master role job type sent unchanged similar jobs including want learn opettelen haluan oppia
basic perustaidot tietotekniikan tietotekniikka computer skills it
worker workers henkilöstö henkilöstöpalvelut staff
through under companies employers general projects projektit
vastaan vastaava vastaavaa vastaavalta käyttö käyttöä
""".split())

# Lines every Jobly ad page has ("Tämä tiivistelmä on luotu tekoälyn avulla" would match the AI skills)
BOILERPLATE = re.compile(r"tiivistelmä työpaikkailmoituksesta:?|tämä tiivistelmä on luotu tekoälyn avulla\.?|"
                         r"hae paikkaa|tallenna työpaikka|skip to main content", re.I)
# Stems of words that are in almost every Finnish ad and say nothing about the job:
# itsenäinen/itsenäisesti, työskentely/työskentelet, sujuva (usually "sujuva suomen kieli"), perus-
STOP_STEMS = {"itsenä", "työske", "sujuva", "perust", "tehtäv", "yhteis", "turval", "opiske", "koulut"}
COMPOUND_MIN = 6   # a skill word this long also matches inside a longer ad word ("asennus" in "sähköasennustyöt")


def tokens(text):
    text = BOILERPLATE.sub(" ", text or "")
    return [w.lower() for w in WORD.findall(text or "")]


def stem(word):
    """Crude stem so Finnish inflections still match: first 6 letters of long words."""
    return word[:6] if len(word) > 6 else word


class WordIndex:
    """The words of one ad, indexed so that "which ad words match this skill word?" (word_matches) is a few
    dictionary lookups instead of a loop over every word. Gives exactly the words word_matches would accept.

    Matching a job against every CV asked that question tens of millions of times for a list of 1,000 jobs."""

    def __init__(self, words):
        self.words = set(words)
        self.by_prefix = {}
        for w in self.words:
            for n in range(1, len(w) + 1):
                self.by_prefix.setdefault(w[:n], []).append(w)
        self.long_words = "\n".join(w for w in self.words if len(w) > COMPOUND_MIN + 2)

    def matches(self, keyword):
        found = set()
        if keyword in self.words:
            found.add(keyword)
        root = keyword if len(keyword) <= 6 else keyword[:max(6, len(keyword) - 3)]
        limit = 4 if len(keyword) <= 6 else 6
        found.update(w for w in self.by_prefix.get(root, ()) if len(w) - len(root) <= limit)
        if len(keyword) >= COMPOUND_MIN and keyword in self.long_words:       # compounds: rare, so check cheaply first
            found.update(w for w in self.long_words.split("\n") if len(w) > len(keyword) + 2 and keyword in w)
        return found


class KeywordIndex:
    """A CV's skill words, indexed by what word_matches needs, so an ad is matched by looking up each of its
    (few) words instead of testing every skill word. Built once per CV and request.

    matched(words) -> {skill word: the ad words that match it}, exactly as word_matches decides."""

    def __init__(self, keywords):
        self.exact = set(keywords)
        self.by_root = {}               # root -> [(keyword, how many letters may follow the root)]
        self.compound = set()           # skill words that may also sit inside a longer word
        for kw in self.exact:
            root = kw if len(kw) <= 6 else kw[:max(6, len(kw) - 3)]
            self.by_root.setdefault(root, []).append((kw, 4 if len(kw) <= 6 else 6))
            if len(kw) >= COMPOUND_MIN:
                self.compound.add(kw)
        self.compound_lengths = sorted({len(kw) for kw in self.compound})

    def matched(self, words):
        found = {}
        for w in words:
            if w in self.exact:
                found.setdefault(w, set()).add(w)
            for n in range(1, len(w) + 1):
                for kw, extra in self.by_root.get(w[:n], ()):
                    if len(w) - n <= extra:
                        found.setdefault(kw, set()).add(w)
            for size in self.compound_lengths:           # a skill word inside a longer word
                if len(w) <= size + 2:
                    break
                for i in range(len(w) - size + 1):
                    piece = w[i:i + size]
                    if piece in self.compound:
                        found.setdefault(piece, set()).add(w)
        return found


def word_matches(word, keyword):
    """Does an ad word match a skill word?

    - Finnish case endings: the ad word starts with the skill word minus its last 3 letters (at least 6),
      and adds no more than 6 letters ("asentajaa", "kokoonpanotöissä"); short skill words up to 4.
    - Compounds: a skill word of 6+ letters inside a longer ad word ("asennus" in "sähköasennustyöt").
    The old rule (same first 6 letters) matched "asiakaskiinteistöissä" to "asiakaspalvelu".
    """
    if word == keyword:
        return True
    root = keyword if len(keyword) <= 6 else keyword[:max(6, len(keyword) - 3)]
    # short words ("sähkö") take case endings only ("sähköä", "sähkön"), not a second word ("sähköalalla")
    if word.startswith(root) and len(word) - len(root) <= (4 if len(keyword) <= 6 else 6):
        return True
    return len(keyword) >= COMPOUND_MIN and len(word) > len(keyword) + 2 and keyword in word
