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
