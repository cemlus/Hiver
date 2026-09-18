"""The dev-draft run manifest accumulates runs; a cache replay must not erase a live run's cost.

M6: the manifest was a single dict, so re-running with LLM_OFFLINE=1 (0 tokens, because no request
is made) overwrote the record of the live run that actually produced the drafts.
"""
from __future__ import annotations

import json

import pytest

from scripts.draft_dev_replies import append_run


def live(tokens: int = 5440) -> dict:
    return {"started_utc": "2026-09-18T04:32:40+00:00", "tokens": tokens,
            "live_calls": 20, "offline_replay": False, "drafted": 15}


def replay() -> dict:
    return {"started_utc": "2026-09-18T10:21:00+00:00", "tokens": 0,
            "live_calls": 0, "offline_replay": True, "drafted": 15}


def test_a_cache_replay_does_not_erase_the_live_run(tmp_path):
    path = tmp_path / "dev_drafts_run.json"
    append_run(path, live())
    append_run(path, replay())
    runs = json.loads(path.read_text())["runs"]
    assert len(runs) == 2
    assert runs[0]["tokens"] == 5440, "the live run's real cost survived the replay"
    assert runs[1]["tokens"] == 0 and runs[1]["offline_replay"] is True


def test_a_legacy_single_dict_manifest_is_migrated_into_runs(tmp_path):
    path = tmp_path / "dev_drafts_run.json"
    path.write_text(json.dumps(live()) + "\n", encoding="utf-8")   # the old shape
    append_run(path, replay())
    history = json.loads(path.read_text())
    assert list(history) == ["runs"]
    assert len(history["runs"]) == 2
    assert history["runs"][0]["tokens"] == 5440


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "dev_drafts_run.json"
    path.write_text(json.dumps(live()) + "\n", encoding="utf-8")
    for _ in range(3):
        append_run(path, replay())
    runs = json.loads(path.read_text())["runs"]
    assert len(runs) == 4, "re-wrapped the history instead of appending"
    assert runs[0]["tokens"] == 5440


def test_a_missing_manifest_starts_a_fresh_history(tmp_path):
    path = tmp_path / "nested" / "dev_drafts_run.json"
    append_run(path, live())
    assert json.loads(path.read_text())["runs"] == [live()]


@pytest.mark.parametrize("calls,offline", [(0, True), (20, False)])
def test_offline_replays_are_distinguishable_from_live_runs(tmp_path, calls, offline):
    """0 tokens means nothing unless a reader can tell a replay from a genuinely cheap run."""
    path = tmp_path / "m.json"
    append_run(path, {"live_calls": calls, "offline_replay": offline, "tokens": 0 if offline else 99})
    run = json.loads(path.read_text())["runs"][0]
    assert run["offline_replay"] is offline
    assert (run["live_calls"] == 0) is offline
