"""LLM client behaviour without any network: `_call` (or the litellm module) is replaced by a fake."""
import sys
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from src.llm.client import (
    CacheMissError,
    LiteLLMClient,
    LLMEmptyReplyError,
    LLMOutputError,
    cache_key,
)
from src.ports.defaults import SQLiteCache


class Label(BaseModel):
    intent: str
    confidence: float


def make_client(tmp_path, replies):
    client = LiteLLMClient("fake/model", SQLiteCache(tmp_path / "cache.sqlite"))
    calls = []

    def fake_call(system, prompt):
        calls.append(prompt)
        return replies[len(calls) - 1]

    client._call = fake_call
    return client, calls


class FakeLiteLLM:
    """Stands in for the litellm module, so the real `_call` runs without a network."""

    def __init__(self):
        self.content, self.finish_reason, self.kwargs = "ok", "stop", None

    def completion(self, **kwargs):
        self.kwargs = kwargs
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=self.finish_reason)])


@pytest.fixture
def fake_litellm(monkeypatch):
    fake = FakeLiteLLM()
    monkeypatch.setitem(sys.modules, "litellm", fake)
    return fake


def test_second_identical_call_hits_cache(tmp_path):
    client, calls = make_client(tmp_path, ["hello"])
    assert client.complete("hi") == "hello"
    assert client.complete("hi") == "hello"
    assert len(calls) == 1


def test_cache_persists_across_client_instances(tmp_path):
    client, _ = make_client(tmp_path, ["hello"])
    client.complete("hi")
    reopened, calls = make_client(tmp_path, [])
    assert reopened.complete("hi") == "hello"
    assert calls == []


def test_different_model_is_a_different_cache_entry(tmp_path):
    client, _ = make_client(tmp_path, ["from model A"])
    client.complete("hi")
    other = LiteLLMClient("fake/other-model", client.cache)
    other._call = lambda system, prompt: "from model B"
    assert other.complete("hi") == "from model B"


def test_offline_mode_serves_cache_and_fails_on_miss(tmp_path, monkeypatch):
    client, calls = make_client(tmp_path, ["hello"])
    client.complete("hi")
    monkeypatch.setenv("LLM_OFFLINE", "1")
    assert client.complete("hi") == "hello"
    with pytest.raises(CacheMissError):
        client.complete("a prompt that was never cached")
    assert len(calls) == 1


def test_schema_reply_is_parsed_even_inside_code_fences(tmp_path):
    client, _ = make_client(tmp_path, ['```json\n{"intent": "billing", "confidence": 0.9}\n```'])
    assert client.complete("classify", schema=Label) == Label(intent="billing", confidence=0.9)


def test_invalid_json_is_retried_once(tmp_path):
    client, calls = make_client(tmp_path, ["not json", '{"intent": "billing", "confidence": 0.5}'])
    assert client.complete("classify", schema=Label).intent == "billing"
    assert len(calls) == 2


def test_invalid_json_twice_raises(tmp_path):
    client, calls = make_client(tmp_path, ["not json", '{"intent": "billing"}'])
    with pytest.raises(LLMOutputError):
        client.complete("classify", schema=Label)
    assert len(calls) == 2


def test_retry_prompt_has_no_version_specific_text(tmp_path):
    # The retry prompt is part of a cache key, so it must not change when pydantic is upgraded.
    client, calls = make_client(tmp_path, ['{"intent": "billing"}', '{"intent": "billing", "confidence": 0.5}'])
    client.complete("classify", schema=Label)
    assert "confidence: Field required" in calls[1]
    assert "errors.pydantic.dev" not in calls[1]


def test_call_sends_only_the_params_that_are_set(tmp_path, fake_litellm):
    client = LiteLLMClient("fake/model", SQLiteCache(tmp_path / "c.sqlite"), max_tokens=64, timeout=5)
    assert client.complete("hi") == "ok"
    assert fake_litellm.kwargs["max_tokens"] == 64
    assert fake_litellm.kwargs["timeout"] == 5
    assert "temperature" not in fake_litellm.kwargs
    assert "reasoning_effort" not in fake_litellm.kwargs


def test_reasoning_effort_is_sent_and_only_keys_the_cache_when_set(tmp_path, fake_litellm):
    cache = SQLiteCache(tmp_path / "c.sqlite")
    LiteLLMClient("fake/model", cache).complete("hi")
    # Unset reasoning_effort keeps the original key format, so existing cache rows still hit.
    assert cache.get(cache_key("fake/model", None, "hi", {"max_tokens": 1024, "temperature": None})) == "ok"

    fake_litellm.content = "thought about it"
    thinking = LiteLLMClient("fake/model", cache, reasoning_effort="low")
    assert thinking.complete("hi") == "thought about it"
    assert fake_litellm.kwargs["reasoning_effort"] == "low"
    assert len(cache) == 2


def test_empty_reply_raises_and_is_not_cached(tmp_path, fake_litellm):
    fake_litellm.content, fake_litellm.finish_reason = None, "length"
    cache = SQLiteCache(tmp_path / "c.sqlite")
    with pytest.raises(LLMEmptyReplyError, match="length"):
        LiteLLMClient("fake/model", cache).complete("hi")
    assert len(cache) == 0
