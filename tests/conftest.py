"""Shared test setup."""
import pytest


@pytest.fixture(autouse=True)
def _online_by_default(monkeypatch):
    """Tests must not depend on the caller's shell. An exported LLM_OFFLINE=1 (as the README
    suggests for reproducing results) would turn every fake LLM call into a cache miss.
    Tests that need offline mode set it themselves."""
    monkeypatch.delenv("LLM_OFFLINE", raising=False)
