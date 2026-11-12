from datetime import datetime
from types import SimpleNamespace

import pytest

from classifier import json_schema, make_classifier, parse_json_reply
from config import LLMConfig
from gmail_client import Email

EMAIL = Email(id="m1", thread_id="t1", date=datetime(2026, 9, 1), sender="jobs@acme.com",
              subject="Your application to Acme", body="Thanks for applying to Software Engineer Intern.")
GOOD = '{"is_application_email": true, "company": "Acme", "role": "Software Engineer Intern", "stage": "Applied"}'


def test_llm_config_defaults_and_presets():
    assert LLMConfig().model == "claude-haiku-5-5"
    g = LLMConfig(provider="Gemini", model="some-model")
    assert g.provider == "gemini" and "generativelanguage" in g.base_url and g.api_key_env == "GEMINI_API_KEY"
    o = LLMConfig(provider="ollama", model="llama")
    assert o.base_url.startswith("http://localhost") and o.api_key_env is None
    with pytest.raises(SystemExit):
        LLMConfig(provider="openai")                      # model required
    with pytest.raises(SystemExit):
        LLMConfig(provider="openai-compatible", model="m")  # base_url required
    with pytest.raises(SystemExit):
        LLMConfig(provider="nope", model="m")


def test_parse_json_reply():
    assert parse_json_reply(GOOD).company == "Acme"
    assert parse_json_reply("```json\n" + GOOD + "\n```").stage == "Applied"
    assert parse_json_reply("Sure! " + GOOD) is not None
    assert parse_json_reply('{"stage": "Hired"}') is None
    assert parse_json_reply("") is None


def test_schema_is_strict():
    s = json_schema()
    assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])


def test_openai_adapter_falls_back_to_json_mode(monkeypatch):
    import openai

    calls = []

    class FakeCompletions:
        def create(self, **kw):
            calls.append(kw["response_format"]["type"])
            if kw["response_format"]["type"] == "json_schema":
                raise openai.BadRequestError("unsupported", response=SimpleNamespace(
                    status_code=400, headers={}, request=None), body=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=GOOD))])

    class FakeClient:
        def __init__(self, **kw):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    monkeypatch.setenv("GROQ_API_KEY", "x")
    classify = make_classifier(LLMConfig(provider="groq", model="m"))
    assert classify(EMAIL).company == "Acme"
    assert classify(EMAIL).stage == "Applied"
    assert calls == ["json_schema", "json_object", "json_object"]  # fallback remembered


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        make_classifier(LLMConfig(provider="openai", model="m"))
