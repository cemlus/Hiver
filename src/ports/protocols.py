"""Interfaces ("ports") for everything outside pure business logic.

Core code depends only on these Protocols. Concrete implementations live in
`src/ports/defaults.py` (local, always available) and `src/integrations/`
(optional services: Postgres, Redis, Slack, ...).
"""
from __future__ import annotations

from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMClient(Protocol):
    model: str

    def complete(
        self, prompt: str, *, system: str | None = None, schema: type[T] | None = None
    ) -> str | T:
        """Return raw text, or a validated `schema` instance when a schema is given."""
        ...


class Cache(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, *, meta: dict[str, Any] | None = None) -> None: ...


class ResultStore(Protocol):
    """Persists agent outputs at runtime (not used during evaluation)."""

    def save(self, record: BaseModel) -> None: ...


class EscalationSink(Protocol):
    """Where escalated tickets are sent for a human (log, Slack, ...)."""

    def notify(self, output: BaseModel) -> None: ...
