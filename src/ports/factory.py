"""Builds the bundle of dependencies the pipeline runs with.

profile="eval"    -> always local defaults (SQLite cache, no result store, NullSink), whatever
                     the `integrations` section of config.yaml says. Evaluation can never
                     depend on Postgres, Redis or Slack.
profile="runtime" -> honours `integrations`. If an optional adapter can't be imported or
                     connected, it logs a warning and falls back to the local default.
"""
from __future__ import annotations

import importlib
import logging
import warnings
from dataclasses import dataclass
from typing import Any, Literal

from src.config import load_config, resolve
from src.llm.client import LiteLLMClient
from src.ports.defaults import JsonlResultStore, LogSink, NullSink, SQLiteCache
from src.ports.protocols import Cache, EscalationSink, LLMClient, ResultStore

log = logging.getLogger(__name__)

Profile = Literal["eval", "runtime"]


@dataclass(frozen=True)
class Deps:
    profile: Profile
    agent_llm: LLMClient
    judge_llm: LLMClient
    store: ResultStore | None
    sink: EscalationSink


def build_deps(profile: Profile = "eval", config: dict[str, Any] | None = None) -> Deps:
    cfg = config or load_config()
    integrations = cfg.get("integrations", {}) if profile == "runtime" else {}

    cache: Cache = SQLiteCache(resolve(cfg["cache"]["path"]))
    if integrations.get("cache") == "redis":
        cache = _optional("src.integrations.redis_cache", "RedisCache", cache, cfg)

    agent_cfg, judge_cfg = cfg["models"]["agent"], cfg["models"]["judge"]
    if agent_cfg["name"] == judge_cfg["name"]:
        warnings.warn("models.judge equals models.agent; the judge may favour its own outputs")

    if profile == "eval":
        store, sink = None, NullSink()
    else:
        store = JsonlResultStore(resolve(cfg["results_store"]["path"]))
        if integrations.get("store") == "postgres":
            store = _optional("src.integrations.postgres_store", "PostgresResultStore", store, cfg)
        sink = {"log": LogSink(), "slack": LogSink()}.get(integrations.get("escalation_sink"), NullSink())
        if integrations.get("escalation_sink") == "slack":
            sink = _optional("src.integrations.slack_sink", "SlackEscalationSink", sink, cfg)

    return Deps(
        profile=profile,
        agent_llm=_llm(agent_cfg, cache),
        judge_llm=_llm(judge_cfg, cache),
        store=store,
        sink=sink,
    )


def _llm(model_cfg: dict[str, Any], cache: Cache) -> LiteLLMClient:
    return LiteLLMClient(
        model_cfg["name"],
        cache,
        temperature=model_cfg.get("temperature"),
        max_tokens=model_cfg.get("max_tokens", 1024),
        reasoning_effort=model_cfg.get("reasoning_effort"),
        timeout=model_cfg.get("timeout", 60),
    )


def _optional(module: str, attr: str, fallback: Any, cfg: dict[str, Any]) -> Any:
    """Instantiate an optional adapter, or return `fallback` if anything goes wrong."""
    try:
        return getattr(importlib.import_module(module), attr)(config=cfg)
    except Exception as e:  # missing package, missing module, bad config, connection refused
        log.warning(
            "optional integration %s.%s unavailable (%s); using %s",
            module, attr, e, type(fallback).__name__,
        )
        return fallback
