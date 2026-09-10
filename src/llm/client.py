"""Provider-agnostic LLM client: LiteLLM underneath, a cache in front.

- The provider comes from the model string in config.yaml, e.g. "anthropic/claude-haiku-4-5",
  "openai/<model>", "gemini/<model>", "ollama/<model>". API keys come from .env.
- Structured output: the JSON schema goes into the prompt and the reply is validated with
  pydantic, with one retry on failure. This behaves the same on every provider, unlike the
  providers' native JSON modes.
- Every call is cached by (model, system, prompt, params). With LLM_OFFLINE=1 only the cache
  is used and a miss raises an error. That is how results reproduce without an API key.
- Empty replies are never cached (see LLMEmptyReplyError): a cached "" would poison every rerun.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from src.ports.protocols import Cache

T = TypeVar("T", bound=BaseModel)


class CacheMissError(RuntimeError):
    """Offline mode was requested but the prompt is not in the cache."""


class LLMOutputError(RuntimeError):
    """The model's reply could not be parsed into the requested schema, even after a retry."""


class LLMEmptyReplyError(RuntimeError):
    """The provider returned no text, e.g. Gemini spent all of max_tokens on thinking."""


def is_offline() -> bool:
    return os.getenv("LLM_OFFLINE", "0").strip().lower() in {"1", "true", "yes"}


def cache_key(model: str, system: str | None, prompt: str, params: dict[str, Any]) -> str:
    payload = json.dumps(
        {"model": model, "system": system, "prompt": prompt, "params": params}, sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LiteLLMClient:
    def __init__(
        self,
        model: str,
        cache: Cache,
        *,
        temperature: float | None = None,
        max_tokens: int = 1024,
        reasoning_effort: str | None = None,
        timeout: float = 60,
    ):
        self.model = model
        self.cache = cache
        # None = don't send it. Some models (e.g. claude-sonnet-5) reject sampling params.
        self.temperature = temperature
        self.max_tokens = max_tokens
        # None = provider default. LiteLLM maps e.g. "disable"/"low" to Gemini's thinking budget.
        self.reasoning_effort = reasoning_effort
        # Seconds per request. LiteLLM's own default is 6000 s, far too long for bulk jobs.
        self.timeout = timeout

    def complete(
        self, prompt: str, *, system: str | None = None, schema: type[T] | None = None
    ) -> str | T:
        if schema is None:
            return self._cached_call(system, prompt)

        prompt = f"{prompt}\n\n{_schema_instructions(schema)}"
        text = self._cached_call(system, prompt)
        try:
            return _parse(text, schema)
        except (ValueError, ValidationError) as first_error:
            retry_prompt = (
                f"{prompt}\n\nYour previous reply was not valid for this schema:\n{text}\n"
                f"Error: {_describe(first_error)}\nReply again with only the corrected JSON object."
            )
            retry_text = self._cached_call(system, retry_prompt)
            try:
                return _parse(retry_text, schema)
            except (ValueError, ValidationError) as e:
                raise LLMOutputError(
                    f"{self.model} returned invalid JSON for {schema.__name__}: {e}"
                ) from e

    def _cached_call(self, system: str | None, prompt: str) -> str:
        params: dict[str, Any] = {"max_tokens": self.max_tokens, "temperature": self.temperature}
        if self.reasoning_effort is not None:  # only when set, so existing cache keys stay valid
            params["reasoning_effort"] = self.reasoning_effort
        key = cache_key(self.model, system, prompt, params)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if is_offline():
            raise CacheMissError(
                f"LLM_OFFLINE=1 and no cached reply for model={self.model} (key {key[:12]})"
            )
        text = self._call(system, prompt)  # raises instead of returning "", so "" is never cached
        self.cache.set(key, text, meta={"model": self.model})
        return text

    def _call(self, system: str | None, prompt: str) -> str:
        import litellm  # lazy: offline runs never pay litellm's import time

        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "num_retries": 3,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.reasoning_effort is not None:
            kwargs["reasoning_effort"] = self.reasoning_effort
        choice = litellm.completion(**kwargs).choices[0]
        text = choice.message.content or ""
        if not text.strip():
            raise LLMEmptyReplyError(
                f"{self.model} returned an empty reply (finish_reason={choice.finish_reason}). "
                "Raise max_tokens or lower reasoning_effort in config.yaml."
            )
        return text


def _schema_instructions(schema: type[BaseModel]) -> str:
    return (
        "Respond with a single JSON object that matches this JSON Schema. "
        "Output only the JSON object: no prose, no code fences.\n"
        + json.dumps(schema.model_json_schema(), sort_keys=True)
    )


def _parse(text: str, schema: type[T]) -> T:
    """Validate the outermost {...} in the reply (tolerates code fences or stray prose)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object found in reply")
    return schema.model_validate_json(text[start : end + 1])


def _describe(error: Exception) -> str:
    """Short error text for the retry prompt. The retry prompt is part of the cache key, so this
    must not contain pydantic's version-specific help URLs (errors.pydantic.dev/2.13/...)."""
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, e['loc'])) or '<root>'}: {e['msg']}"
            for e in error.errors(include_url=False)
        )
    return str(error)
