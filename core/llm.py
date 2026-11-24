"""A small Claude API client using only the standard library (urllib), for JSON answers.

Settings come from environment variables, read when settings_from_env() is called:
  JOBDESK_LLM_MODE      "mock" (default) or "live". Mock never contacts the API.
  ANTHROPIC_API_KEY     live mode through Anthropic's API. Never logged, never put in error messages.
  OPENROUTER_API_KEY    ...or through OpenRouter, which forwards requests to Claude (used when set).
  JOBDESK_LLM_MODEL     default claude-opus-5-5. For OpenRouter the name is converted automatically
                        ("claude-haiku-5-5" -> "anthropic/claude-haiku-5.5"); a name with "/" is kept.
  JOBDESK_LLM_EFFORT    low | medium | high | xhigh | max (default low; Anthropic API only).
  JOBDESK_LLM_FALLBACKS 1 (default) asks the API to retry a safety refusal on a fallback model,
                        for the models that support it; 0 turns that off.

How a live call works (call_json):
  1. Build a Messages API request: the model, a system prompt, one user message and
     output_config.format with a JSON schema. The API then guarantees the reply is valid JSON in
     that shape ("structured outputs"). There is no temperature: API version 2026-10-21 rejects it,
     so steadiness comes from the schema, low effort and the checks done by the caller.
  2. POST it to https://api.anthropic.com/v1/messages with the x-api-key and anthropic-version headers.
  3. Retry on 429 (rate limit), 5xx and network errors, up to max_retries, waiting
     retry-after seconds when the API says so, otherwise 1, 2, 4 ... seconds.
  4. Check stop_reason: "refusal" and "max_tokens" are errors, not answers.
  5. Return the parsed JSON plus the model that answered and the token usage.

Errors never include the prompt, the ad text or the key: only the HTTP status and the API's error type.
"""

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

API_URL = "https://api.anthropic.com/v1/messages"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
API_VERSION = "2026-10-21"
DEFAULT_MODEL = "claude-opus-5-5"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Models that accept the server-side refusal fallback; "default" lets the API pick the fallback model
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5-2"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504, 529}
MOCK_LABEL = "[MOCK OUTPUT – not a model result]"


class LLMError(Exception):
    """The API call failed or returned something unusable."""


class LLMUnavailable(LLMError):
    """Live mode was asked for but can't run (for example no API key)."""


@dataclass
class Settings:
    mode: str = "mock"
    provider: str = "anthropic"                       # "anthropic" or "openrouter"
    model: str = DEFAULT_MODEL
    api_key: str = field(default="", repr=False)      # repr=False: never printed with the settings
    effort: str = "low"
    fallbacks: bool = True
    timeout: float = 60.0
    max_retries: int = 2

    @property
    def live(self):
        return self.mode == "live"


def settings_from_env(environ=None):
    env = os.environ if environ is None else environ
    mode = (env.get("JOBDESK_LLM_MODE") or "mock").strip().lower()
    if mode not in {"mock", "live"}:
        raise LLMUnavailable("JOBDESK_LLM_MODE must be 'mock' or 'live'.")
    effort = (env.get("JOBDESK_LLM_EFFORT") or "low").strip().lower()
    if effort not in EFFORTS:
        raise LLMUnavailable(f"JOBDESK_LLM_EFFORT must be one of {', '.join(EFFORTS)}.")
    openrouter_key = (env.get("OPENROUTER_API_KEY") or "").strip()
    return Settings(
        mode=mode,
        provider="openrouter" if openrouter_key else "anthropic",
        model=(env.get("JOBDESK_LLM_MODEL") or DEFAULT_MODEL).strip(),
        api_key=openrouter_key or (env.get("ANTHROPIC_API_KEY") or "").strip(),
        effort=effort,
        fallbacks=(env.get("JOBDESK_LLM_FALLBACKS") or "1").strip() != "0",
    )


def openrouter_model(name):
    """Anthropic's model names in OpenRouter's style: "claude-haiku-5-5" -> "anthropic/claude-haiku-5.5"."""
    if "/" in name:
        return name
    return "anthropic/" + re.sub(r"-(\d+)-(\d+)$", r"-\1.\2", name)


def build_request(settings, system, user, schema, max_tokens):
    """(url, headers, body) for one call. Separate so tests can check it without a network."""
    if settings.provider == "openrouter":
        headers = {"content-type": "application/json", "authorization": f"Bearer {settings.api_key}"}
        body = {
            "model": openrouter_model(settings.model),
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "answer", "strict": True, "schema": schema}},
            # Only providers that support the JSON schema, and that don't store or train on the data
            "provider": {"require_parameters": True, "data_collection": "deny"},
        }
        return OPENROUTER_URL, headers, body
    headers = {
        "content-type": "application/json",
        "x-api-key": settings.api_key,
        "anthropic-version": API_VERSION,
    }
    body = {
        "model": settings.model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "output_config": {
            "effort": settings.effort,
            "format": {"type": "json_schema", "schema": schema},
        },
    }
    if settings.fallbacks and settings.model in FALLBACK_MODELS:
        headers["anthropic-beta"] = FALLBACK_BETA
        body["fallbacks"] = "default"
    return API_URL, headers, body


def answer_text(settings, message):
    """The JSON text of a successful reply. The two services shape replies differently."""
    if settings.provider == "openrouter":
        choice = (message.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise LLMError("The model's answer was cut off (max_tokens).")
        if choice.get("finish_reason") == "content_filter":
            raise LLMError("The model declined this request.")
        return (choice.get("message") or {}).get("content")
    stop = message.get("stop_reason")
    if stop == "refusal":
        raise LLMError("The model declined this request.")
    if stop == "max_tokens":
        raise LLMError("The model's answer was cut off (max_tokens).")
    return next((block.get("text", "") for block in message.get("content", [])
                 if block.get("type") == "text"), None)


def _urllib_post(url, headers, data, timeout):
    """Default transport: (status, response headers, body bytes)."""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() if hasattr(e, "read") else b""


def _api_error_type(raw):
    try:
        error = json.loads(raw)["error"]
        return str(error.get("type") or error.get("code") or "unknown_error")
    except (ValueError, KeyError, TypeError, AttributeError):
        return "unknown_error"


def call_json(system, user, schema, settings, max_tokens=2048, post=None, sleep=time.sleep):
    """Ask the model and return {"data": parsed JSON, "model": str, "usage": dict}.

    post(url, headers, data, timeout) -> (status, headers, body) is the transport; tests pass a fake.
    Raises LLMUnavailable when live mode can't run and LLMError for every other failure."""
    if not settings.live:
        raise LLMUnavailable("call_json is only for live mode; callers produce mock output themselves.")
    if not settings.api_key:
        raise LLMUnavailable("Live mode needs ANTHROPIC_API_KEY or OPENROUTER_API_KEY.")
    post = post or _urllib_post
    url, headers, body = build_request(settings, system, user, schema, max_tokens)
    data = json.dumps(body).encode("utf-8")
    attempt = 0
    while True:
        try:
            status, resp_headers, raw = post(url, headers, data, settings.timeout)
        except (urllib.error.URLError, OSError) as error:
            status, resp_headers, raw = None, {}, b""
            network_error = type(error).__name__
        else:
            network_error = None
        if status == 200:
            break
        retryable = status is None or status in RETRY_STATUSES
        if not retryable or attempt >= settings.max_retries:
            reason = network_error or f"HTTP {status} {_api_error_type(raw)}"
            raise LLMError(f"{settings.provider} API call failed: {reason}.")
        retry_after = {k.lower(): v for k, v in (resp_headers or {}).items()}.get("retry-after")
        try:
            wait = float(retry_after) if retry_after else 2 ** attempt
        except ValueError:
            wait = 2 ** attempt
        sleep(min(wait, 60))
        attempt += 1

    try:
        message = json.loads(raw)
    except ValueError as error:
        raise LLMError("Claude API returned a response that isn't JSON.") from error
    text = answer_text(settings, message)
    if text is None:
        raise LLMError("The model's answer had no text block.")
    try:
        parsed = json.loads(text)
    except ValueError as error:
        raise LLMError("The model's answer wasn't valid JSON.") from error
    return {"data": parsed, "model": message.get("model", settings.model), "usage": message.get("usage", {})}
