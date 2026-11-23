"""Checks every sentence of a drafted application answer against the CV facts it cites.

verify(sentences, facts, learning, ad_blockers) -> list of
    {"text", "fact_ids", "status": "supported" | "unsupported", "reasons": [str]}

A sentence is UNSUPPORTED when any of these is true:
  1. it cites no fact, or a fact id that doesn't exist;
  2. none of its key words appear in the cited facts (key words: not stop words, not generic
     application words like "experience" or "motivated", at least 4 letters; Finnish case endings
     still match, via core.text.word_matches);
  3. it contains a number (a year, "3 months", "40 plots") that isn't in the cited facts;
  4. it claims something the ad asks for that the CV doesn't show (ad_blockers, e.g. "forklift card"),
     unless the sentence says it isn't held yet;
  5. it presents a want-to-learn item as a skill the person has.

Failing sentences are never dropped: they come back marked, with the reasons, for the person to
fix or delete. These checks are deliberately simple and transparent. They catch invented facts,
numbers and cards, but not a real fact used in a misleading way; the person must still read the draft.
"""

import re

from core import blockers as core_blockers
from core.text import STOPWORDS, tokens, word_matches

# Words that appear in almost any application answer and prove nothing about the CV
GENERIC = set("""
experience experienced work worked working job jobs team teams skill skills ability able also very
good great strong well would like love eager motivated passionate interested interest learn learned
learning keen believe think hope position role opportunity company your this that with have been
which where when what from into about more most such these those their there them they will make
made really always usually responsible responsibilities task tasks duties
kokemus kokemusta kokemuksen työ työssä työskentelin työskentely tiimi tiimissä taidot taitoja osaan
osaamista hyvä hyvin vahva motivoitunut kiinnostunut innostunut haluan halusin oppia oppinut olen olin
ollut tehtävä tehtäviä tehtävissä vastuu vastasin myös erittäin paljon tässä siellä sekä joka jossa
""".split())
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# "want to learn" language: saying you are learning something is honest, claiming it is not
LEARNING_WORDS = re.compile(r"want to learn|would like to learn|learning|studying|plan to|interested in learning|"
                            r"haluan oppia|opettelen|opiskelen|aion|kiinnostaa oppia", re.I)


def key_words(text):
    return [w for w in tokens(text) if len(w) >= 4 and w not in STOPWORDS and w not in GENERIC
            and not w.isdigit()]


def _shares_a_key_word(sentence, fact_text):
    fact_words = set(tokens(fact_text))
    return any(any(word_matches(fw, w) or word_matches(w, fw) for fw in fact_words) for w in key_words(sentence))


def _claims_learning_item(sentence, item):
    words = key_words(item) or [w for w in tokens(item) if w not in STOPWORDS]
    sentence_words = set(tokens(sentence))
    mentioned = words and all(any(word_matches(sw, w) for sw in sentence_words) for w in words)
    return bool(mentioned) and not LEARNING_WORDS.search(sentence)


def verify(sentences, facts, learning=(), ad_blockers=()):
    by_id = {fact["id"]: fact for fact in facts}
    checked = []
    for sentence in sentences:
        text = (sentence.get("text") or "").strip()
        ids = [i for i in (sentence.get("fact_ids") or []) if isinstance(i, str)]
        reasons = []
        unknown = [i for i in ids if i not in by_id]
        if not ids:
            reasons.append("It doesn't cite any fact from your CV.")
        elif unknown:
            reasons.append(f"It cites {', '.join(unknown)}, which is not in your CV.")
        cited = " ".join(by_id[i]["text"] for i in ids if i in by_id)
        if cited:
            if key_words(text) and not _shares_a_key_word(text, cited):
                reasons.append("None of its key words appear in the CV facts it cites.")
            missing_numbers = [n for n in NUMBER.findall(text) if n not in NUMBER.findall(cited)]
            if missing_numbers:
                reasons.append(f"The number(s) {', '.join(missing_numbers)} are not in the cited CV facts.")
        for label in ad_blockers:
            if core_blockers.claims(label, text):
                reasons.append(f"It claims “{label}”, which the ad asks for but your CV doesn't show.")
        for item in learning:
            if _claims_learning_item(text, item):
                reasons.append(f"“{item}” is on your want-to-learn list, but the sentence presents it as a skill you have.")
        checked.append({"text": text, "fact_ids": ids,
                        "status": "unsupported" if reasons else "supported", "reasons": reasons})
    return checked


def word_count(sentences):
    return sum(len(re.findall(r"\S+", s.get("text") or "")) for s in sentences)
