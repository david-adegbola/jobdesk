"""How well one job fits one CV: suitability, strengths, gaps and recommendations. Standard library only.

evaluate(ad_text, cv_content, settings, call=None, use_ai=True) ->
    {"suitability", "summary", "strengths": [{"point", "fact_ids", "ad_quote"}],
     "gaps": [{"requirement", "ad_quote", "advice", "source"}], "recommendations": [str],
     "checks": {"dropped_strengths", "cleared_quotes"}, "method", "model", "prompt_version", "notice"}

suitability is one of SUITABILITY: strong | possible | stretch | weak. The rules never say "strong".

Step by step:
1. core.cv_facts turns the CV into numbered facts. Name, email, phone, location and links are never included.
2. core.blockers finds what the ad requires that the CV doesn't show (licences, cards, fluent Finnish, years of
   experience...). These always become gaps, whatever the model says.
3. AI mode (live settings and use_ai): the model gets the ad and the facts and must answer in a fixed JSON shape
   (structured output). Rules mode (mock settings, or the member hasn't opted in to sending CV facts): words
   shared by the ad's sentences and the facts decide the strengths and gaps. Rules mode never contacts anything.
4. check() applies the same rules to both:
   - a strength must cite fact ids that exist, or it is dropped;
   - a strength that claims a missing requirement (a blocker) is dropped;
   - every quote must appear in the ad word for word (only whitespace may differ), or it is cleared.
"""

import hashlib
import json
import re
from pathlib import Path

from core import blockers as core_blockers
from core import cv_facts, llm
from core.text import STOP_STEMS, STOPWORDS, stem, tokens, word_matches

PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "fit_evaluation.md"
PROMPT_VERSION = "fit_evaluation-v1"
RULES_VERSION = "fit_rules-v1"
SUITABILITY = ("strong", "possible", "stretch", "weak")
MAX_AD_CHARS = 20_000
MAX_ITEMS = 6
RULES_POINT = ": in the ad and in your CV"

SCHEMA = {
    "type": "object",
    "properties": {
        "suitability": {"type": "string", "enum": list(SUITABILITY)},
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": {
            "type": "object",
            "properties": {"point": {"type": "string"}, "fact_ids": {"type": "array", "items": {"type": "string"}},
                           "ad_quote": {"type": "string"}},
            "required": ["point", "fact_ids", "ad_quote"], "additionalProperties": False}},
        "gaps": {"type": "array", "items": {
            "type": "object",
            "properties": {"requirement": {"type": "string"}, "ad_quote": {"type": "string"},
                           "advice": {"type": "string"}},
            "required": ["requirement", "ad_quote", "advice"], "additionalProperties": False}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["suitability", "summary", "strengths", "gaps", "recommendations"],
    "additionalProperties": False,
}

# Sentences that state what the employer expects (the rules mode looks for gaps among these)
REQUIREMENT = re.compile(
    r"\b(?:require|required|requirement|must|need|you have|you are|we expect|we hope|experience|knowledge|skills?|"
    r"familiar|degree|studies|student|qualification|edellyt|vaadi|vaatimu|odotamme|toivomme|arvostamme|"
    r"kokemus|kokemust|osaamis|osaat|taito|tunte|tutkinto|opiskel|eduksi|hallitset)", re.I)


def content_hash(value):
    """A short, stable fingerprint: the same ad or CV always gives the same value."""
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def cache_key(ad_text, cv_content, method):
    """Same ad + same CV + same method and version = the same evaluation, so it is never run twice."""
    version = PROMPT_VERSION if method == "llm" else RULES_VERSION
    return content_hash(f"{content_hash(ad_text)}|{content_hash(cv_content)}|{method}|{version}")


def _squash(text):
    return " ".join((text or "").split())


def sentences(ad_text):
    parts = re.split(r"(?<=[.!?])\s+|\n+|\s*[•·▪●]\s*", ad_text or "")
    return [_squash(p).lstrip("-–* ").strip() for p in parts if len(_squash(p)) >= 12]


def _words(text):
    return {w for w in tokens(text) if len(w) > 2 and w not in STOPWORDS and stem(w) not in STOP_STEMS}


def _shared(fact_words, sentence_words):
    return sorted(w for w in sentence_words if any(word_matches(w, f) or word_matches(f, w) for f in fact_words))


def missing_requirements(ad_text, facts):
    texts = [f["text"] for f in facts]
    return [label for label in core_blockers.in_ad(ad_text) if not core_blockers.shown_in(label, texts)]


def _quote_for(label, ad_text):
    match = core_blockers.PATTERNS[label].search(ad_text or "")
    if not match:
        return ""
    return next((s for s in sentences(ad_text) if match.group(0).lower() in s.lower()), "")


def rules(ad_text, facts, missing):
    """The evaluation without AI: shared words between each ad sentence and each CV fact."""
    ad_sentences = sentences(ad_text)
    fact_words = {f["id"]: _words(f["text"]) for f in facts if f["section"] != "summary"}
    strengths, used = [], set()
    pairs = []
    for sentence in ad_sentences:
        words = _words(sentence)
        for fid, fw in fact_words.items():
            shared = _shared(fw, words)
            if len(shared) >= 1 and (len(shared) >= 2 or any(len(w) >= 5 for w in shared)):
                pairs.append((len(shared), sentence, fid, shared))
    pairs.sort(key=lambda p: (-p[0], p[2]))
    covered = set()
    for _, sentence, fid, shared in pairs:
        covered.add(sentence)
        if fid in used or sentence in {s["ad_quote"] for s in strengths} or len(strengths) >= 4:
            continue
        used.add(fid)
        strengths.append({"point": f"{', '.join(shared[:4])}{RULES_POINT}",
                          "fact_ids": [fid], "ad_quote": sentence})
    gaps = [{"requirement": s, "ad_quote": s, "advice": "Your CV doesn't show this. If you have it, add it to your "
             "CV; if not, say how you would learn it.", "source": "rules"}
            for s in ad_sentences if REQUIREMENT.search(s) and s not in covered][:4]
    asked = [s for s in ad_sentences if REQUIREMENT.search(s)]
    share = sum(1 for s in asked if s in covered) / len(asked) if asked else (1.0 if strengths else 0.0)
    # Shared words can show a possible fit, never a strong one: "strong" is left to a reading of the meaning (AI)
    suitability = "weak" if not strengths else "stretch" if missing or share < 0.34 else "possible"
    return {"suitability": suitability,
            "summary": f"{len(strengths)} matching point(s) and {len(gaps) + len(missing)} gap(s) found by comparing "
                       "words in the ad with your CV.",
            "strengths": strengths, "gaps": gaps, "recommendations": []}


def _recommendations(result):
    out = []
    if result["strengths"]:
        out.append("Put what matches the ad first in your CV and cover letter: " +
                   "; ".join(s["point"].replace(RULES_POINT, "").rstrip(".") for s in result["strengths"][:3]) + ".")
    for gap in [g for g in result["gaps"] if g.get("source") == "requirement"][:2]:
        out.append(f"The ad asks for {gap['requirement']}. Don't claim it; say whether you are working towards it.")
    if not result["strengths"]:
        out.append("Little in your CV matches this ad. Check that your CV lists the skills you have, or keep looking.")
    return out


def check(raw, ad_text, facts, missing):
    """Apply the evidence rules to a raw evaluation (from the model or from the rules)."""
    ids = {f["id"] for f in facts}
    ad = _squash(ad_text)
    cleared = dropped = 0

    def quote(value):
        nonlocal cleared
        q = _squash(value) if isinstance(value, str) else ""
        if q and q not in ad:
            cleared += 1
            return ""
        return q

    strengths = []
    for item in (raw.get("strengths") or [])[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        cited = [i for i in item.get("fact_ids") or [] if isinstance(i, str) and i in ids]
        point = _squash(item.get("point"))
        if not cited or not point or any(core_blockers.claims(label, point) for label in missing):
            dropped += 1
            continue
        strengths.append({"point": point, "fact_ids": cited, "ad_quote": quote(item.get("ad_quote"))})
    gaps = [{"requirement": label, "ad_quote": _quote_for(label, ad_text),
             "advice": "Required by the ad, and not shown in your CV.", "source": "requirement"} for label in missing]
    for item in (raw.get("gaps") or [])[:MAX_ITEMS]:
        if isinstance(item, dict) and _squash(item.get("requirement")):
            q = quote(item.get("ad_quote"))
            if q and q in {g["ad_quote"] for g in gaps}:
                continue            # the same sentence is already a gap (usually a requirement found by the rules)
            gaps.append({"requirement": _squash(item["requirement"]), "ad_quote": q,
                         "advice": _squash(item.get("advice")), "source": item.get("source") or "model"})
    suitability = raw.get("suitability") if raw.get("suitability") in SUITABILITY else "stretch"
    if missing and suitability == "strong":
        suitability = "possible"            # a hard requirement the CV doesn't show caps the rating
    result = {"suitability": suitability, "summary": _squash(raw.get("summary")), "strengths": strengths,
              "gaps": gaps[:MAX_ITEMS + len(missing)],
              "recommendations": [_squash(r) for r in (raw.get("recommendations") or [])
                                  if isinstance(r, str) and _squash(r)][:MAX_ITEMS]}
    if not result["recommendations"]:
        result["recommendations"] = _recommendations(result)
    result["checks"] = {"dropped_strengths": dropped, "cleared_quotes": cleared}
    return result


def user_message(ad_text, facts, missing):
    return "\n".join([
        f"<job_ad>\n{ad_text}\n</job_ad>",
        f"<cv_facts>\n{cv_facts.as_text(facts)}\n</cv_facts>",
        f"<ad_asks_for_but_cv_lacks>\n{chr(10).join(missing) or '(none)'}\n</ad_asks_for_but_cv_lacks>",
    ])


def evaluate(ad_text, cv_content, settings=None, call=None, use_ai=True):
    """Raises ValueError for unusable input and core.llm.LLMError when a live call fails."""
    ad_text = (ad_text or "").strip()
    if len(ad_text) < 40:
        raise ValueError("This job has too little text to evaluate. Add the ad's description first.")
    ad_text = ad_text[:MAX_AD_CHARS]
    settings = settings or llm.settings_from_env()
    facts = cv_facts.facts_from_cv(cv_content)["facts"]
    if not facts:
        raise ValueError("This CV is empty. Add your experience and skills first.")
    missing = missing_requirements(ad_text, facts)
    if settings.live and use_ai:
        reply = (call or llm.call_json)(PROMPT_FILE.read_text(encoding="utf-8"), user_message(ad_text, facts, missing),
                                        SCHEMA, settings, max_tokens=4096)
        raw = reply["data"] if isinstance(reply.get("data"), dict) else {}
        method, model, notice, version = "llm", reply.get("model", settings.model), "", PROMPT_VERSION
    else:
        raw = rules(ad_text, facts, missing)
        method, model, version = "rules", "", RULES_VERSION
        notice = ("Compared word by word, without AI. It finds shared words, not meaning: read the ad yourself."
                  if settings.live else f"{llm.MOCK_LABEL} Mock mode compares words; no AI was used.")
    result = check(raw, ad_text, facts, missing)
    facts_by_id = {f["id"]: f["text"] for f in facts}
    for strength in result["strengths"]:
        strength["facts"] = [facts_by_id[i] for i in strength["fact_ids"]]
    return {**result, "method": method, "model": model, "prompt_version": version, "notice": notice}
