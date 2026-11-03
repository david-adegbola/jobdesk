"""Which language a job ad or news story is written in: Finnish, English, Swedish or several.
The browser uses it to choose what to machine-translate when "Show text in English" is on.

Transparent word counting, no external service: common function words and job-ad words of each
language are counted in the title and the first part of the text. Titles alone (many listings
have no saved ad) are judged by job-title words and the letters ä/ö/å. Bilingual ads count as both
languages. When there is no evidence the result is empty and the item counts as unknown.
"""

import re

LANGUAGES = ("fi", "en", "sv")
WORD = re.compile(r"[a-zåäöé]+", re.I)

FUNCTION_WORDS = {
    "fi": set("""ja tai sekä on ovat olet olla että kanssa meillä sinulla sinua sinun haemme etsimme
              tehtävä tehtävään tehtäviin hakemus hakemuksesi hae työ työn työhön työssä työpaikka
              ilmoitus kokemus kokemusta osaamista edellytämme toivomme tarjoamme yhteystiedot lisätietoja
              mennessä alkaen määräaikainen vakituinen koulutus tutkinto kuten myös tai jos kun""".split()),
    # "on", "in", "an", "as" and similar are left out where they are also Finnish or Swedish words
    "en": set("""the and of to for with you your we our is are will be this at from
              apply application experience skills role position team join looking offer about
              who what which by or opportunity responsibilities requirements please candidate""".split()),
    "sv": set("""och att är för med vi du som på till söker ansökan erfarenhet tjänsten arbete
              hos inom eller av har kan vill""".split()),
}
TITLE_WORDS = {
    "fi": re.compile(r"asiantunti|harjoittelij|työntekij|suunnittelij|tutkija|päällikkö|kesätyö|insinööri|"
                     r"metsuri|myyjä|asentaja|opettaja|ohjaaja|neuvoja|avustaja|vastaava|johtaja|koordinaattori|"
                     r"projektipäällikkö|erikoistutkija|korkeakouluharjoittelija|sijainen|lehtori|"
                     # Finnish job-title endings: hitsaaja, myyjä, asentajia, maalari, teknikko, kirvesmies
                     r"\b\w{3,}(?:jaa?|jä|jia|jat|jiä|joita|jöitä|ri|rit|kko|kot|mies|miehiä|ttori|ttoreita)\b", re.I),
    "en": re.compile(r"\b(?:specialist|manager|engineer|intern|internship|trainee|assistant|researcher|worker|"
                     r"summer job|officer|analyst|developer|technician|coordinator|professor|doctoral|lead|"
                     r"director|consultant|operator|scientist|head of|senior|junior|counsel|advisor|adviser|"
                     r"executive|supervisor|accountant|controller|representative|administrator|architect|"
                     r"designer|planner|buyer|sales|support|customer|service|team|associate|assembler|mechanic|"
                     r"renovator|welder|electrician|driver|cleaner|lecturer)\b", re.I),
    "sv": re.compile(r"\b(?:sommarjobb|praktikant|handläggare|chef|skogs\w*|virkesköpare|lärare|vikariat)\b", re.I),
}
SAMPLE = 3000           # characters of ad text to read
BILINGUAL_SHARE = 0.4   # a second language with at least this share of the evidence also counts


def detect(title, text=""):
    """List of language codes, most evidence first; [] when it can't be told."""
    score = dict.fromkeys(LANGUAGES, 0.0)
    words = [w.lower() for w in WORD.findall((text or "")[:SAMPLE])]
    for word in words:
        for lang in LANGUAGES:
            if word in FUNCTION_WORDS[lang]:
                score[lang] += 1
    title = title or ""
    for lang in LANGUAGES:
        score[lang] += 3 * len(TITLE_WORDS[lang].findall(title))
    # Swedish has ä and ö too, so they only count for Finnish when nothing points to Swedish
    if re.search(r"[äö]", title, re.I) and not re.search(r"å", title, re.I) and not score["sv"]:
        score["fi"] += 2
    if re.search(r"å", title, re.I):
        score["sv"] += 2
    ranked = sorted((lang for lang in LANGUAGES if score[lang] > 0), key=lambda lang: -score[lang])
    if not ranked:
        return []
    top = score[ranked[0]]
    return [lang for lang in ranked if score[lang] >= 2 and score[lang] >= BILINGUAL_SHARE * top] or ranked[:1]
