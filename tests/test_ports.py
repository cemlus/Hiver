"""The eval profile must never depend on optional integrations."""
import subprocess
import sys

import pytest

from src.config import ROOT
from src.ports.defaults import JsonlResultStore, LogSink, NullSink, SQLiteCache
from src.ports.factory import build_deps


@pytest.fixture
def config(tmp_path):
    return {
        "models": {
            "agent": {"name": "fake/agent", "temperature": 0, "max_tokens": 64},
            "judge": {"name": "fake/judge", "temperature": None, "max_tokens": 64},
        },
        "cache": {"path": str(tmp_path / "cache.sqlite")},
        "results_store": {"path": str(tmp_path / "outputs.jsonl")},
        # Every optional integration switched on -- none of them is installed or running.
        "integrations": {"store": "postgres", "cache": "redis", "escalation_sink": "slack"},
    }


def test_eval_profile_ignores_integrations(config):
    deps = build_deps("eval", config=config)
    assert deps.store is None
    assert isinstance(deps.sink, NullSink)
    assert isinstance(deps.agent_llm.cache, SQLiteCache)


def test_runtime_profile_falls_back_when_integrations_unavailable(config):
    deps = build_deps("runtime", config=config)
    assert isinstance(deps.store, JsonlResultStore)
    assert isinstance(deps.sink, LogSink)
    assert isinstance(deps.agent_llm.cache, SQLiteCache)


def test_same_agent_and_judge_model_warns(config):
    config["models"]["judge"]["name"] = config["models"]["agent"]["name"]
    with pytest.warns(UserWarning, match="judge"):
        build_deps("eval", config=config)


def test_importing_the_llm_layer_loads_no_optional_or_heavy_packages():
    code = (
        "import sys, src.ports.factory, src.llm.client\n"
        "loaded = [m for m in ('psycopg', 'redis', 'slack_sdk', 'fastapi', 'langsmith', 'litellm')"
        " if m in sys.modules]\n"
        "print(loaded); sys.exit(1 if loaded else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
