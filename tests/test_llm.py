import json
import unittest

from core import llm

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
          "additionalProperties": False}


def message(text='{"ok": true}', stop="end_turn"):
    return json.dumps({"model": "claude-opus-5-5", "stop_reason": stop, "usage": {"input_tokens": 5},
                       "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}]}).encode()


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, url, headers, data, timeout):
        self.requests.append({"url": url, "headers": headers, "body": json.loads(data)})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def live(**overrides):
    return llm.Settings(**{"mode": "live", "api_key": "sk-test-secret", **overrides})


class SettingsTests(unittest.TestCase):
    def test_defaults_are_mock_and_opus(self):
        settings = llm.settings_from_env({})
        self.assertEqual((settings.mode, settings.model, settings.effort), ("mock", "claude-opus-5-5", "low"))
        self.assertFalse(settings.live)

    def test_key_is_never_in_the_settings_repr(self):
        settings = llm.settings_from_env({"JOBDESK_LLM_MODE": "live", "ANTHROPIC_API_KEY": "sk-test-secret"})
        self.assertNotIn("sk-test-secret", repr(settings))

    def test_bad_values_are_refused(self):
        with self.assertRaises(llm.LLMUnavailable):
            llm.settings_from_env({"JOBDESK_LLM_MODE": "production"})
        with self.assertRaises(llm.LLMUnavailable):
            llm.settings_from_env({"JOBDESK_LLM_EFFORT": "extreme"})


class CallTests(unittest.TestCase):
    def test_request_shape(self):
        transport = FakeTransport((200, {}, message()))
        result = llm.call_json("system text", "user text", SCHEMA, live(), post=transport)
        self.assertEqual(result["data"], {"ok": True})
        sent = transport.requests[0]
        self.assertEqual(sent["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(sent["headers"]["anthropic-version"], "2026-10-21")
        self.assertEqual(sent["headers"]["x-api-key"], "sk-test-secret")
        body = sent["body"]
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertEqual(body["system"], "system text")
        self.assertEqual(body["messages"], [{"role": "user", "content": "user text"}])
        self.assertEqual(body["output_config"], {"effort": "low",
                                                 "format": {"type": "json_schema", "schema": SCHEMA}})
        self.assertNotIn("temperature", body)       # rejected by API version 2026-10-21
        self.assertEqual(body["fallbacks"], "default")
        self.assertEqual(sent["headers"]["anthropic-beta"], "server-side-fallback-2026-07-01")

    def test_fallbacks_only_for_models_that_support_them(self):
        transport = FakeTransport((200, {}, message()))
        llm.call_json("s", "u", SCHEMA, live(model="claude-haiku-5-5"), post=transport)
        self.assertNotIn("fallbacks", transport.requests[0]["body"])
        transport = FakeTransport((200, {}, message()))
        llm.call_json("s", "u", SCHEMA, live(fallbacks=False), post=transport)
        self.assertNotIn("anthropic-beta", transport.requests[0]["headers"])

    def test_retries_rate_limits_and_server_errors_then_succeeds(self):
        waits = []
        transport = FakeTransport((429, {"retry-after": "3"}, b'{"error":{"type":"rate_limit_error"}}'),
                                  OSError("connection reset"),
                                  (200, {}, message()))
        result = llm.call_json("s", "u", SCHEMA, live(max_retries=2), post=transport, sleep=waits.append)
        self.assertEqual(result["data"], {"ok": True})
        self.assertEqual(waits, [3.0, 2])

    def test_client_errors_are_not_retried_and_leak_nothing(self):
        transport = FakeTransport((400, {}, b'{"error":{"type":"invalid_request_error","message":"bad"}}'))
        with self.assertRaises(llm.LLMError) as caught:
            llm.call_json("secret prompt", "secret ad text", SCHEMA, live(), post=transport, sleep=lambda s: None)
        message_text = str(caught.exception)
        self.assertIn("400 invalid_request_error", message_text)
        for secret in ("secret prompt", "secret ad text", "sk-test-secret"):
            self.assertNotIn(secret, message_text)
        self.assertEqual(len(transport.requests), 1)

    def test_gives_up_after_max_retries(self):
        transport = FakeTransport(*[(529, {}, b"{}")] * 3)
        with self.assertRaises(llm.LLMError):
            llm.call_json("s", "u", SCHEMA, live(max_retries=2), post=transport, sleep=lambda s: None)
        self.assertEqual(len(transport.requests), 3)

    def test_refusal_and_cut_off_answers_are_errors(self):
        for stop in ("refusal", "max_tokens"):
            transport = FakeTransport((200, {}, message(stop=stop)))
            with self.assertRaises(llm.LLMError):
                llm.call_json("s", "u", SCHEMA, live(), post=transport)

    def test_live_mode_without_a_key_and_mock_mode_never_send(self):
        transport = FakeTransport()
        with self.assertRaises(llm.LLMUnavailable):
            llm.call_json("s", "u", SCHEMA, live(api_key=""), post=transport)
        with self.assertRaises(llm.LLMUnavailable):
            llm.call_json("s", "u", SCHEMA, llm.Settings(), post=transport)
        self.assertEqual(transport.requests, [])


if __name__ == "__main__":
    unittest.main()
