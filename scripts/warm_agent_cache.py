"""Classify the golden items with the frozen router, populating the LLM cache. Nothing else.

Run from the repo root:   uv run python scripts/warm_agent_cache.py [--max-hours 6]

Quota-aware and fully resumable. Groq's free tier caps this model at 200,000 tokens per day (a
rolling window) and 8,000 per minute, and one routing call costs about 4.2k, so roughly 47 items fit
in a day. When the API reports the daily limit this script **waits for the window it names** rather
than retrying into a wall; when it reports the per-minute limit it backs off briefly.

Deliberately import-light (no sklearn, no metrics, no baselines) so it holds minimal memory, and it
only classifies: it computes no metrics and writes no report, so it cannot influence the evaluation.
Cached items are never re-requested.

Progress and every quota wait are appended to results/eval/agent_golden_progress.json, which the
evaluation run folds into its manifest.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import load_config, resolve  # noqa: E402
from src.contracts import SupportRequest, Turn  # noqa: E402
from src.core.classify import RoutingProposal, classify  # noqa: E402
from src.llm.client import LiteLLMClient, _schema_instructions, cache_key  # noqa: E402
from src.core.prompts import system_prompt, user_prompt  # noqa: E402
from src.ports.defaults import SQLiteCache  # noqa: E402

GOLDEN = ROOT / "data" / "golden"
PROGRESS = ROOT / "results" / "eval" / "agent_golden_progress.json"
WAIT_RE = re.compile(r"try again in ([0-9hms.]+)")
TPD_RE = re.compile(r"tokens per day \(TPD\): Limit (\d+), Used (\d+), Requested (\d+)")


def parse_wait(message: str) -> float | None:
    """Seconds from a Groq message like 'Please try again in 11m17.376s'."""
    found = WAIT_RE.search(message)
    if not found:
        return None
    total, number = 0.0, ""
    for char in found.group(1):
        if char.isdigit() or char == ".":
            number += char
        elif char in "hms" and number:
            total += float(number) * {"h": 3600, "m": 60, "s": 1}[char]
            number = ""
    return total or None


def requests_for_golden(cfg: dict) -> list[SupportRequest]:
    labels = pd.read_csv(GOLDEN / "golden_final.csv", dtype=str, keep_default_na=False)
    records = pd.read_parquet(resolve(cfg["data"]["records"]),
                              columns=["record_id", "split", "eval_eligible", "customer_text_clean",
                                       "context", "is_followup"])
    records = records[(records["split"] == "holdout") & records["eval_eligible"]]
    records = records.assign(record_id=records["record_id"].astype(str)).set_index("record_id")
    out = []
    for row in labels.to_dict("records"):
        record = records.loc[row["record_id"]]
        out.append(SupportRequest(
            request_id=row["golden_id"], brand=cfg["brand"],
            customer_text=record["customer_text_clean"],
            context=tuple(Turn(role=str(t["role"]), text=str(t["text"])) for t in record["context"]),
            is_followup=bool(record["is_followup"])))
    return out


def is_cached(request: SupportRequest, llm: LiteLLMClient, cache: SQLiteCache) -> bool:
    """Exactly the key `complete(schema=...)` would use, so nothing successful is ever re-requested."""
    prompt = f"{user_prompt(request)}\n\n{_schema_instructions(RoutingProposal)}"
    params = {"max_tokens": llm.max_tokens, "temperature": llm.temperature}
    if llm.reasoning_effort is not None:
        params["reasoning_effort"] = llm.reasoning_effort
    return cache.get(cache_key(llm.model, system_prompt(), prompt, params)) is not None


def save_progress(state: dict) -> None:
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sleep", type=float, default=40.0, help="seconds between live calls")
    parser.add_argument("--max-hours", type=float, default=6.0,
                        help="stop after this long; rerun to continue where it left off")
    parser.add_argument("--max-wait", type=float, default=1800.0,
                        help="longest single quota wait before re-checking")
    args = parser.parse_args()

    cfg = load_config()
    model = cfg["models"]["agent"]
    cache = SQLiteCache(resolve(cfg["cache"]["path"]))
    llm = LiteLLMClient(model["name"], cache, temperature=model.get("temperature"),
                        max_tokens=model.get("max_tokens", 4096),
                        reasoning_effort=model.get("reasoning_effort"), timeout=model.get("timeout", 120))
    items = requests_for_golden(cfg)
    todo = [r for r in items if not is_cached(r, llm, cache)]
    started = datetime.now(timezone.utc)
    state = json.loads(PROGRESS.read_text()) if PROGRESS.exists() else {"sessions": []}
    session = {"started_utc": started.isoformat(timespec="seconds"), "model": llm.model,
               "params": {k: model.get(k) for k in ("temperature", "max_tokens", "reasoning_effort")},
               "cached_at_start": len(items) - len(todo), "total_items": len(items),
               "classified": 0, "live_calls": 0, "tokens": 0, "quota_waits": [], "failures": []}
    state["sessions"].append(session)
    save_progress(state)
    print(f"{len(todo)} of {len(items)} still to classify with {llm.model}", flush=True)

    deadline = time.time() + args.max_hours * 3600
    for request in todo:
        while time.time() < deadline:
            try:
                classify(request, llm)
                session["classified"] += 1
                if llm.last_usage:
                    session["live_calls"] += 1
                    session["tokens"] += llm.last_usage.get("total_tokens", 0)
                    time.sleep(args.sleep)
                break
            except Exception as error:                          # noqa: BLE001
                message = str(error)
                daily = TPD_RE.search(message)
                if daily or "tokens per day" in message:
                    wait = min(parse_wait(message) or 900, args.max_wait) + 20
                    used = daily.group(2) if daily else "?"
                    limit = daily.group(1) if daily else "?"
                    session["quota_waits"].append(
                        {"at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "limit": "tokens_per_day", "used": used, "cap": limit,
                         "waited_seconds": round(wait)})
                    save_progress(state)
                    print(f"  daily quota reached ({used}/{limit}); waiting {wait / 60:.1f} min",
                          flush=True)
                    time.sleep(wait)
                    continue                                     # the item has not been attempted yet
                if "rate_limit" in message or "Rate limit" in message:
                    wait = min(parse_wait(message) or 70, 300) + 5
                    session["quota_waits"].append(
                        {"at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "limit": "tokens_per_minute", "waited_seconds": round(wait)})
                    time.sleep(wait)
                    continue
                session["failures"].append({"item": request.request_id,
                                            "error": f"{type(error).__name__}: {message[:300]}"})
                print(f"  {request.request_id}: FAILED {type(error).__name__}", flush=True)
                break
        else:
            print("  time budget reached; rerun to continue", flush=True)
            break
        if session["classified"] % 10 == 0 and session["classified"]:
            save_progress(state)
            print(f"  {session['classified']}/{len(todo)} this session "
                  f"({session['live_calls']} live, {session['tokens']:,} tokens)", flush=True)

    session["finished_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    session["elapsed_minutes"] = round((time.time() - started.timestamp()) / 60, 1)
    remaining = [r for r in items if not is_cached(r, llm, cache)]
    session["remaining_after"] = len(remaining)
    save_progress(state)
    print(f"session done: {session['classified']} classified, {session['tokens']:,} tokens, "
          f"{len(session['quota_waits'])} quota waits, {len(remaining)} items remaining", flush=True)


if __name__ == "__main__":
    main()
