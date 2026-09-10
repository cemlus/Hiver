"""Loads config.yaml and .env. Every module reads settings through `load_config()`."""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Return a fresh copy of the config, so one caller's changes can't leak into another's."""
    return copy.deepcopy(_load(path))


@lru_cache(maxsize=None)
def _load(path: str | Path | None) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    with open(path or ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve(relative: str | Path) -> Path:
    """Resolve a repo-relative path from config into an absolute path."""
    return ROOT / relative
