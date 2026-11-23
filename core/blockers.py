"""Things job ads often require that an applicant may not have: licences, cards, qualifications,
years of experience, fluent Finnish. Used by drafting (core/draft.py) so an answer never claims one.

The patterns are copied from match.py BLOCKERS (tests/test_drafting.py checks they stay the same);
here they carry no owner facts: whether the applicant has something is decided from their own CV.

  in_ad(ad_text)                 labels the ad mentions
  shown_in(label, texts)         does any CV text show this (e.g. "B driving licence" in Certifications)?
  claims(label, sentence)        does a sentence mention it WITHOUT saying it isn't held yet?
"""

import re

BLOCKERS = [
    ("welding", r"hitsa|welding|welder"),
    ("welding certificate", r"hitsauspätevyy|hitsaussertifik|welding certif"),
    ("hot-work card", r"tulityö|hot[- ]work"),
    ("forklift card", r"trukki|trukin|forklift"),
    ("reading drawings", r"piirustu|drawings|blueprint"),
    ("B licence", r"\bb-(?:ajo)?kort|(?<![c-])\bajokortti|driving licen[cs]e|driver'?s licen[cs]e|ajokortillinen"),
    ("C licence", r"\bc-(?:ajo)?kort|\bce-(?:ajo)?kort|c-kortillinen|\bc licen[cs]e"),
    ("fluent Finnish",
     r"sujuva\w* suome|hyvä\w* suomen kiel|erinomai\w* suomen kiel|fluent finnish|native finnish|"
     r"suomen kielen taito on (?:edellytys|välttämätön)"),
    ("electrician qualification", r"sähköasentaja|sähköpätevyy|sähköalan tutkin"),
    ("electrical safety card", r"sähkötyöturvallisuu|sfs ?6002|electrical safety (?:card|training)"),
    ("first aid card", r"\bea ?1\b|ensiapukortti|ensiapukoulutus|first aid"),
    ("1+ years' experience",
     r"at least (?:one|two|three|\d+) years?\b|\b\d+\+? years?(?:'|’)? (?:of )?(?:relevant |similar |work )?experience|"
     r"(?:one|two|three) years? of (?:relevant |similar |work )?experience|"
     r"vähintään (?:vuoden|\d+ vuoden|kahden|kolmen)|(?:usean|useamman) vuoden (?:työ)?kokemus"),
    ("vocational qualification",
     r"vocational (?:education|qualification|degree)|technical/vocational|ammatillinen (?:tutkinto|koulutus)|"
     r"alan (?:ammatillinen|perus)tutkinto|alalle soveltuva koulutus"),
    ("brush saw experience", r"raivaussah|brush ?saw|clearing saw"),
    ("chainsaw", r"moottorisah|chain ?saw"),
    ("forest machine operator qualification", r"metsäkoneenkuljettaj|forest machine operator"),
    ("forestry degree",
     r"metsä\w* \w*tutkin|metsätalousinsinöö|metsänhoitaj|metsätieteiden|forestry degree|degree in forestry|"
     r"(?:bsc|msc|bachelor|master)\W+(?:\w+\W+)?forestry"),
]
PATTERNS = {label: re.compile(pattern, re.I) for label, pattern in BLOCKERS}

# A sentence that mentions a blocker honestly says it isn't held yet, or that it is being learned
NOT_HELD = re.compile(
    r"\b(?:ei|en|eikä|don'?t|do not|doesn'?t|haven'?t|have not|not yet|no)\b|ei ole|vielä|"
    r"haluan (?:oppia|suorittaa)|opettel|opiskel(?:en|emassa)|aion|suoritan mielelläni|"
    r"want to (?:learn|get|take)|learning|plan to|happy to (?:learn|take)|studying|working towards", re.I)


def in_ad(ad_text):
    return [label for label, _ in BLOCKERS if PATTERNS[label].search(ad_text or "")]


def shown_in(label, texts):
    return any(PATTERNS[label].search(text or "") for text in texts)


def claims(label, sentence):
    return bool(PATTERNS[label].search(sentence or "")) and not NOT_HELD.search(sentence or "")
