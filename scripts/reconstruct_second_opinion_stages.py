"""Recover the staged generation budgets of the Gemma second-opinion run (audit repair, one-off).

The second-opinion pass was **staged**: items whose reply hit `finish_reason=length` at one
`max_tokens` were relabelled at a larger budget. Nothing else changed, and no successful item was
ever relabelled. Each rerun overwrote `second_opinion_run.json`, so the earlier stages' metadata
was lost; this script recovers it from evidence still on disk.

Stage membership comes from the run logs, which recorded exactly which items failed at each
budget: an item belongs to the first budget at which it did not fail. Those lists are embedded
below so the repair stays reproducible after the session's log directory is cleared.

The LLM cache (`sha256(model, system, prompt, params)`, with `max_tokens` inside `params`) supplies
the timing via `created_at`. The cache alone cannot identify the stage: an empty reply raises before
caching, but a reply that was cached and then failed schema parsing leaves an entry at a budget that
produced no label. Those cases are reported as `cache_log_discrepancies` rather than silently
resolved.

Writes:
  data/golden/golden_llm_labels.csv       adds `max_tokens` (the labels themselves are untouched)
  data/golden/second_opinion_stages.json  per-stage manifest: params, item ids, windows, timing
  data/golden/second_opinion_run.json     rewritten to describe the whole staged run

Never reads or writes the locked human labels.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from llm_second_opinion import SYSTEM, Label, codebook_prompt, item_prompt  # noqa: E402
from src.config import load_config  # noqa: E402
from src.dataprep.loaders import eval_pool  # noqa: E402
from src.llm.client import _schema_instructions, cache_key  # noqa: E402

GOLDEN = ROOT / "data" / "golden"
LABELS = GOLDEN / "golden_llm_labels.csv"
STAGES_OUT = GOLDEN / "second_opinion_stages.json"
RUN_OUT = GOLDEN / "second_opinion_run.json"
MODEL = "gemini/gemma-4-26b-a4b-it"
TEMPERATURE = 0.0
# Budgets tried, smallest first. Timeouts: the default 120 s judge timeout, raised to 600 s only
# for the final item, whose generation exceeded 120 s at 16384.
BUDGETS = [(2048, 120), (4096, 120), (8192, 120), (16384, 600)]
# Items that failed at each budget, from the run logs of 2026-09-12. An item's stage is the first
# budget where it does not appear here.
STAGE_FAILURES = {
    2048: ["G004", "G016", "G018", "G019", "G028", "G032", "G051", "G054", "G060", "G066", "G105",
           "G106", "G107", "G110", "G113", "G116", "G119", "G127", "G133", "G141", "G145", "G147",
           "G152", "G156", "G159", "G170", "G181", "G190", "G200"],
    4096: ["G054", "G060", "G105", "G107", "G113", "G119"],
    8192: ["G119"],
    16384: [],
}
# Attempts that produced no label, recorded from the run logs of 2026-09-12 for the audit trail.
KNOWN_FAILED_ATTEMPTS = [
    {"stage_max_tokens": 2048, "items": 29, "error": "LLMEmptyReplyError (finish_reason=length)",
     "note": "4 attempts each; deterministic at temperature 0, so every retry failed identically"},
    {"stage_max_tokens": 4096, "items": 6, "error": "LLMEmptyReplyError (finish_reason=length)",
     "note": "3 attempts each"},
    {"stage_max_tokens": 8192, "items": 1, "error": "APIConnectionError (DNS resolution)",
     "note": "G119, transient; unrelated to the model"},
    {"stage_max_tokens": 4096, "items": 1, "error": "LLMEmptyReplyError (finish_reason=length)",
     "note": "G119 retried at a budget already known too small (operator error)"},
    {"stage_max_tokens": 16384, "items": 1, "error": "Timeout (120 s)",
     "note": "G119; the generation needed longer than the default judge timeout"},
]


def main() -> None:
    cfg = load_config()
    spec = yaml.safe_load((ROOT / "data" / "taxonomy" / "taxonomy_v1.yaml").read_text(encoding="utf-8"))
    system = f"{SYSTEM}\n\n{codebook_prompt(spec)}"
    schema_suffix = _schema_instructions(Label)

    labels = pd.read_csv(LABELS, dtype=str, keep_default_na=False)
    pool = eval_pool()
    pool = pool.assign(record_id=pool["record_id"].astype(str)).set_index("record_id")

    cache = sqlite3.connect(ROOT / cfg["cache"]["path"])
    created = dict(cache.execute("select key, created_at from cache"))

    found: dict[str, tuple[int, int, str | None]] = {}
    discrepancies = []
    for row in labels.to_dict("records"):
        gid = row["golden_id"]
        prompt = f"{item_prompt(pool.loc[row['record_id']])}\n\n{schema_suffix}"
        keys = {b: cache_key(MODEL, system, prompt, {"max_tokens": b, "temperature": TEMPERATURE})
                for b, _ in BUDGETS}
        stage = next((b for b, t in BUDGETS if gid not in STAGE_FAILURES[b]), None)
        if stage is None:
            sys.exit(f"{gid} is recorded as failing at every budget")
        timeout = dict(BUDGETS)[stage]
        found[gid] = (stage, timeout, created.get(keys[stage]))
        cached_at = next((b for b, _ in BUDGETS if keys[b] in created), None)
        if cached_at != stage:
            discrepancies.append({"item": gid, "label_from_budget": stage,
                                  "smallest_cached_budget": cached_at,
                                  "why": "a reply was cached at the smaller budget but failed schema "
                                         "parsing, so it produced no label"})

    no_timing = [g for g, v in found.items() if v[2] is None]

    labels["max_tokens"] = [str(found[g][0]) for g in labels["golden_id"]]
    labels["temperature"] = str(TEMPERATURE)
    labels["request_timeout_s"] = [str(found[g][1]) for g in labels["golden_id"]]
    labels.to_csv(LABELS, index=False)

    stages = []
    for budget, timeout in BUDGETS:
        ids = sorted(g for g, (b, _, _) in found.items() if b == budget)
        if not ids:
            continue
        times = sorted(datetime.fromisoformat(found[g][2]) for g in ids if found[g][2])
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
        if not times:
            stages.append({"max_tokens": budget, "request_timeout_s": timeout,
                           "items_labelled": len(ids), "item_ids": ids, "timing": "not in cache"})
            continue
        stages.append({
            "max_tokens": budget,
            "request_timeout_s": timeout,
            "items_labelled": len(ids),
            "item_ids": ids,
            "first_call_utc": times[0].isoformat(timespec="seconds"),
            "last_call_utc": times[-1].isoformat(timespec="seconds"),
            "seconds_between_calls": {
                "mean": round(sum(gaps) / len(gaps), 1) if gaps else None,
                "median": round(sorted(gaps)[len(gaps) // 2], 1) if gaps else None,
                "max": round(max(gaps), 1) if gaps else None,
            },
        })

    all_times = sorted(datetime.fromisoformat(v[2]) for v in found.values() if v[2])
    wall = (all_times[-1] - all_times[0]).total_seconds()
    run = {
        "model": MODEL,
        "route": "gemini-api-direct",
        "model_family_note": ("Gemma 4 26B is a different model family from the gemini-2.5-flash "
                              "production agent, but the same vendor (Google), so this is a partially "
                              "independent second opinion, not vendor-independent validation."),
        "codebook_version": cfg["codebook_version"],
        "temperature": TEMPERATURE,
        "reasoning_effort": None,
        "staged_generation_budget": True,
        "why_staged": ("max_tokens was raised only for items whose reply hit finish_reason=length "
                       "before closing its JSON. No successfully labelled item was ever relabelled, "
                       "so the budgets differ per item. Greedy decoding at temperature 0 makes a "
                       "truncation deterministic, so retrying at the same budget cannot succeed."),
        "stages": stages,
        "items_labelled": len(found),
        "items_expected": len(labels),
        "failed_ids": [],
        "known_failed_attempts": KNOWN_FAILED_ATTEMPTS,
        "run_window_utc": {"first_call": all_times[0].isoformat(timespec="seconds"),
                           "last_call": all_times[-1].isoformat(timespec="seconds"),
                           "elapsed_hours": round(wall / 3600, 2)},
        "timing_caveat": ("Per-call latency was recorded only for the first stage (mean 26.1 s, max "
                          "78.2 s over 171 items) before later reruns overwrote that metadata. The "
                          "per-stage figures here are intervals between cached calls, which include "
                          "the configured sleep and any retries, so they are an upper bound on latency."),
        "per_item_parameters": "data/golden/golden_llm_labels.csv (max_tokens, temperature, request_timeout_s)",
        "stage_source": ("run logs of 2026-09-12: an item's budget is the first at which it did not "
                         "fail (failure lists embedded in scripts/reconstruct_second_opinion_stages.py)"),
        "cache_log_discrepancies": discrepancies,
        "items_without_cached_timing": no_timing,
        "note": ("Blind second opinion only. The primary gold labels are the locked human sheet "
                 "(golden.lock); this run never reads them."),
    }
    STAGES_OUT.write_text(json.dumps({"model": MODEL, "stages": stages}, indent=2) + "\n", encoding="utf-8")
    RUN_OUT.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    print(f"per-item budgets: " + ", ".join(f"{s['max_tokens']}: {s['items_labelled']}" for s in stages))
    print(f"wrote {LABELS.relative_to(ROOT)} (+max_tokens, temperature, request_timeout_s)")
    print(f"wrote {STAGES_OUT.relative_to(ROOT)} and {RUN_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
