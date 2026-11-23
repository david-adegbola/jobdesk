"""Drafting the answer to one application question, grounded only in the person's CV.

draft_answer(ad_text, question, cv_content, word_limit, language, settings, call) ->
    {"sentences": [{"text", "fact_ids", "status", "reasons"}], "word_count", "word_limit",
     "over_limit", "unsupported": int, "ad_blockers": [...], "method", "model", "notice"}

Step by step:
1. core.cv_facts turns the CV into numbered facts and a list of things still being learned.
   Name, email, phone, location and links are never included.
2. core.blockers finds what the ad asks for (licences, cards, fluent Finnish, years of experience …)
   and keeps those the CV doesn't show: the draft must not claim them.
3. Live mode: the model gets the ad, the question, the facts, the not-held lists and the limits, and
   must answer as {"sentences": [{"text", "fact_ids"}]} (structured output, so the shape is fixed).
   Mock mode: sentences are copied from the most relevant facts and labelled as mock output.
4. core.verify checks every sentence (cited ids exist, key words and numbers come from the cited
   facts, no blocker or want-to-learn item claimed). Failing sentences stay in, marked unsupported.
5. The word count is compared with the limit. Nothing is sent anywhere: the person edits the draft.
"""

from pathlib import Path

from core import blockers as core_blockers
from core import cv_facts, llm, verify
from core.text import STOPWORDS, tokens, word_matches

PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "grounded_answer.md"
PROMPT_VERSION = "grounded_answer-v1"
LANGUAGES = ("en", "fi")
MAX_WORD_LIMIT = 1000
MAX_QUESTION_CHARS = 1000
MAX_AD_CHARS = 20_000

SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "fact_ids": {"type": "array", "items": {"type": "string"}}},
                "required": ["text", "fact_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sentences"],
    "additionalProperties": False,
}


def ad_blockers(ad_text, facts):
    """Requirements the ad mentions that no CV fact shows."""
    fact_texts = [fact["text"] for fact in facts]
    return [label for label in core_blockers.in_ad(ad_text) if not core_blockers.shown_in(label, fact_texts)]


def user_message(ad_text, question, facts, learning, missing, word_limit, language):
    return "\n".join([
        f"<job_ad>\n{ad_text}\n</job_ad>",
        f"<question>\n{question}\n</question>",
        f"<cv_facts>\n{cv_facts.as_text(facts)}\n</cv_facts>",
        f"<not_held>\n{chr(10).join(learning) or '(none)'}\n</not_held>",
        f"<ad_asks_for_but_cv_lacks>\n{chr(10).join(missing) or '(none)'}\n</ad_asks_for_but_cv_lacks>",
        f"<limits>\nword limit: {word_limit}\nlanguage: {language}\n</limits>",
    ])


def _relevance(fact, words):
    fact_words = set(tokens(fact["text"]))
    return sum(1 for w in words if any(word_matches(fw, w) for fw in fact_words))


def mock_sentences(ad_text, question, facts, word_limit):
    """Up to three facts that share most words with the question and ad, copied as sentences."""
    words = [w for w in tokens(f"{question} {ad_text}") if len(w) > 3 and w not in STOPWORDS]
    ranked = sorted(facts, key=lambda f: (-_relevance(f, words), f["id"]))
    chosen, used = [], 0
    for fact in [f for f in ranked if f["section"] != "summary"][:3]:
        text = f"{llm.MOCK_LABEL} {fact['text']}"
        if used + len(text.split()) > word_limit:
            break
        chosen.append({"text": text, "fact_ids": [fact["id"]]})
        used += len(text.split())
    return chosen


def draft_answer(ad_text, question, cv_content, word_limit=150, language="en", settings=None, call=None):
    """Raises ValueError for bad input and core.llm.LLMError when a live call fails."""
    question = (question or "").strip()
    ad_text = ad_text or ""
    if not question or len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"Give the application question (up to {MAX_QUESTION_CHARS} characters).")
    if len(ad_text) > MAX_AD_CHARS:
        raise ValueError(f"The ad is longer than {MAX_AD_CHARS:,} characters.")
    if not isinstance(word_limit, int) or not 10 <= word_limit <= MAX_WORD_LIMIT:
        raise ValueError(f"The word limit must be a whole number from 10 to {MAX_WORD_LIMIT}.")
    if language not in LANGUAGES:
        raise ValueError("Choose English (en) or Finnish (fi).")
    settings = settings or llm.settings_from_env()
    extracted = cv_facts.facts_from_cv(cv_content)
    facts, learning = extracted["facts"], extracted["learning"]
    if not facts:
        raise ValueError("This CV has no content to draft from yet.")
    missing = ad_blockers(ad_text, facts)
    if settings.live:
        call = call or llm.call_json
        reply = call(PROMPT_FILE.read_text(encoding="utf-8"),
                     user_message(ad_text, question, facts, learning, missing, word_limit, language),
                     SCHEMA, settings, max_tokens=4096)
        raw = reply["data"].get("sentences") if isinstance(reply.get("data"), dict) else None
        sentences = [s for s in (raw or []) if isinstance(s, dict)]
        method, model, notice = "llm", reply.get("model", settings.model), ""
    else:
        sentences = mock_sentences(ad_text, question, facts, word_limit)
        method, model = "mock", ""
        notice = f"{llm.MOCK_LABEL} Mock mode copies CV facts; it doesn't write an answer."
    checked = verify.verify(sentences, facts, learning, missing)
    count = verify.word_count(checked)
    return {"sentences": checked, "word_count": count, "word_limit": word_limit, "over_limit": count > word_limit,
            "unsupported": sum(1 for s in checked if s["status"] == "unsupported"), "ad_blockers": missing,
            "learning": learning, "facts": facts, "method": method, "model": model,
            "prompt_version": PROMPT_VERSION, "notice": notice}
