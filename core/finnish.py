"""How much Finnish does a job ad ask for? Two classifiers and the code that checks the second.

baseline_v1(text)
    The yes/no rule JobDesk used until now, copied unchanged from match.py's "fluent Finnish"
    blocker. It answers "required" or "not_required". It is kept only as the comparison baseline
    for the evaluation and as the fallback when the LLM is off. Known flaw: "hyvä suomen kielen
    taito" also matches "good Finnish skills are an advantage", which is really "preferred".
    Do not fix it here; tests pin the pattern.

classify(ad_text)
    Four levels: "required", "preferred", "not_needed" or "unclear", with evidence and a one-line
    English explanation. In live mode the model answers in a fixed JSON schema
    (prompts/finnish_level.md). In mock mode the answer is made up locally and labelled as fake.

Why the evidence check matters: a model can invent a convincing quote. verify_evidence() keeps a
result only when every quoted sentence really appears in the ad (comparing with runs of whitespace
collapsed, nothing else). Any quote that isn't found makes the whole result "unclear", and
required / preferred / not_needed without any evidence are "unclear" too.
"""

import re
from pathlib import Path

from core import llm

LEVELS = ("required", "preferred", "not_needed", "unclear")
PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "finnish_level.md"
PROMPT_VERSION = "finnish_level-v1"
MAX_AD_CHARS = 50_000

# match.py BLOCKERS "fluent Finnish", character for character (tests/test_finnish.py pins it)
BASELINE_V1_PATTERN = (r"sujuva\w* suome|hyvä\w* suomen kiel|erinomai\w* suomen kiel|fluent finnish|native finnish|"
                       r"suomen kielen taito on (?:edellytys|välttämätön)")

SCHEMA = {
    "type": "object",
    "properties": {
        "level": {"type": "string", "enum": list(LEVELS)},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "explanation_en": {"type": "string"},
    },
    "required": ["level", "evidence", "explanation_en"],
    "additionalProperties": False,
}

# Sentences that mention a language, for the mock answer
_LANGUAGE_MENTION = re.compile(r"suom|finnish|finska|ruotsi|swedish|svenska|englan|english|engelska|työkiel|"
                               r"working language|arbetsspråk", re.I)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def baseline_v1(text):
    """'required' when the old fluent-Finnish regex matches, else 'not_required'."""
    return "required" if re.search(BASELINE_V1_PATTERN, (text or "").lower()) else "not_required"


def _squash(text):
    return " ".join((text or "").split())


def verify_evidence(ad_text, evidence):
    """(found, not_found): which quotes appear in the ad. Only runs of whitespace are ignored."""
    ad = _squash(ad_text)
    found, missing = [], []
    for quote in evidence:
        q = _squash(quote) if isinstance(quote, str) else ""
        (found if q and q in ad else missing).append(quote)
    return found, missing


def _result(level, evidence, explanation, method, model, rejected=()):
    return {"level": level, "evidence": list(evidence), "explanation_en": explanation, "method": method,
            "model": model, "prompt_version": PROMPT_VERSION, "verified": not rejected,
            "rejected_evidence": list(rejected)}


def check(ad_text, answer, method, model):
    """Turn a raw model answer into a result, applying the evidence rules."""
    level = answer.get("level")
    evidence = answer.get("evidence") or []
    explanation = answer.get("explanation_en") or ""
    if level not in LEVELS or not isinstance(evidence, list):
        return _result("unclear", [], "The model's answer was not in the expected form, so the result is unclear.",
                       method, model, rejected=evidence if isinstance(evidence, list) else [])
    found, missing = verify_evidence(ad_text, evidence)
    if missing:
        return _result("unclear", found,
                       "The model quoted text that is not in the ad, so the result is unclear. Read the ad's "
                       "language requirements yourself.", method, model, rejected=missing)
    if level != "unclear" and not found:
        return _result("unclear", [], "The model gave no quote from the ad to support its answer, so the "
                       "result is unclear.", method, model)
    return _result(level, found, explanation, method, model)


def mock_answer(ad_text):
    """A fake answer, clearly labelled, built from the ad itself so the evidence path still runs."""
    sentences = [s.strip() for s in _SENTENCE.findall(ad_text or "") if s.strip()]
    quote = next((s for s in sentences if _LANGUAGE_MENTION.search(s)), None)
    return {"level": "unclear", "evidence": [quote] if quote else [],
            "explanation_en": f"{llm.MOCK_LABEL} Mock mode does not judge the ad; this sentence mentions a "
                              "language." if quote else f"{llm.MOCK_LABEL} Mock mode does not judge the ad."}


def system_prompt():
    return PROMPT_FILE.read_text(encoding="utf-8")


def classify(ad_text, settings=None, call=None):
    """Classify one ad. settings: core.llm.Settings (default: from the environment).
    call: replaces core.llm.call_json in tests. Raises ValueError for an ad that is too long and
    core.llm.LLMError when a live call fails."""
    settings = settings or llm.settings_from_env()
    text = ad_text or ""
    if len(text) > MAX_AD_CHARS:
        raise ValueError(f"The ad is longer than {MAX_AD_CHARS:,} characters; paste only the ad itself.")
    method = "llm" if settings.live else "mock"
    if not text.strip():
        return _result("unclear", [], "The ad has no text to read.", method, settings.model if settings.live else "")
    if not settings.live:
        return check(text, mock_answer(text), "mock", "")
    call = call or llm.call_json
    reply = call(system_prompt(), f"<job_ad>\n{text}\n</job_ad>", SCHEMA, settings, max_tokens=2048)
    return check(text, reply["data"], "llm", reply.get("model", settings.model))


def fallback(ad_text):
    """The baseline expressed in the four-level shape, for screens when the LLM is off.
    'not_required' becomes 'unclear', because the regex can't tell preferred from not needed."""
    level = baseline_v1(ad_text)
    match = re.search(BASELINE_V1_PATTERN, (ad_text or "").lower())
    evidence = []
    if match:
        sentences = [s.strip() for s in _SENTENCE.findall(ad_text or "")]
        evidence = [s for s in sentences if re.search(BASELINE_V1_PATTERN, s.lower())][:1]
    return _result("required" if level == "required" else "unclear", evidence,
                   "Keyword rule (baseline_v1): the ad mentions good or fluent Finnish." if level == "required"
                   else "Keyword rule (baseline_v1): no fluent-Finnish wording found; this does not mean "
                        "Finnish isn't needed.", "baseline_v1", "")
