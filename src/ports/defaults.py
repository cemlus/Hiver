"""Local implementations of the ports. Standard library only, so they always work
offline with no services running. The eval profile uses nothing else."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

log = logging.getLogger(__name__)


class SQLiteCache:
    """Key-value cache in a single SQLite file.

    The LLM cache is committed to git, which is what lets reviewers reproduce
    results without an API key (see LLM_OFFLINE in src/llm/client.py).
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            " key TEXT PRIMARY KEY, value TEXT NOT NULL, meta TEXT, created_at TEXT NOT NULL)"
        )
        self._conn.commit()

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set(self, key: str, value: str, *, meta: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?)",
                (key, value, json.dumps(meta or {}), datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()

    def __len__(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]


class JsonlResultStore:
    """Appends each record as one JSON line."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, record: BaseModel) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")


class NullSink:
    """Drops escalations. Used during evaluation so no side effects happen."""

    def notify(self, output: BaseModel) -> None:
        return None


class LogSink:
    """Logs escalations. The zero-setup stand-in for Slack."""

    def notify(self, output: BaseModel) -> None:
        log.warning("ESCALATION %s", output.model_dump_json())
