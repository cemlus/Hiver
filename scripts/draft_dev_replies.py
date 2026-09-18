"""Draft replies for the auto-handled dev items, resumably, under the Groq free tier.

Run from the repo root:   uv run python scripts/draft_dev_replies.py

Dev only. The golden set is never drafted for in this phase, and never used as retrieval data,
prompt examples or tuning input.

Only items the frozen policy AUTO-HANDLES get a draft: escalated cases hand off to a human with a
reason code and no customer-facing reply, so they cost no tokens. Every reply is cached by the LLM
client, so a rerun skips finished work; quota waits are recorded the way the routing run recorded
them.

Writes:
  results/eval/dev_drafts.md            one row per item: decision, draft, validation result
  results/eval/dev_drafts.jsonl         the FULL reply text and evidence ids, one JSON per line
  results/eval/dev_drafts_run.json      run manifest + quota stages

The markdown truncates each draft to 150 characters for readability, so it cannot feed a judge or a
human rater. The JSONL is the machine-readable copy: full reply, retrieved ids, and the reference
reply and slice columns a reply-quality pass needs.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import load_config, resolve                       # noqa: E402
from src.contracts import SupportRequest, Turn                     # noqa: E402
from src.core.draft import DRAFT_PROMPT_VERSION                    # noqa: E402
from src.core.prompts import CLASSIFIER_PROMPT_VERSION             # noqa: E402
from src.core.respond import respond                               # noqa: E402
from src.core.retrieve import default_retriever                    # noqa: E402
from src.core.route import route                                   # noqa: E402
from src.dataprep.loaders import eval_pool                         # noqa: E402
from src.llm.client import LiteLLMClient                           # noqa: E402
from src.ports.defaults import SQLiteCache                         # noqa: E402

OUT = ROOT / "results" / "eval"
DEV = ROOT / "data" / "golden" / "dev_labeling_sheet.csv"
WAIT_RE = re.compile(r"try again in ([0-9hms.]+)")
TPD_RE = re.compile(r"tokens per day \(TPD\): Limit (\d+), Used (\d+), Requested (\d+)")


def parse_wait(message: str) -> float | None:
    found = WAIT_RE.search(message)
    if not found:
        return None
    total, number = 0.0, ""
    for char in found.group(1):
        if char.isdigit() or char == ".":
            number += char
        elif char == "h":
            total, number = total + float(number or 0) * 3600, ""
        elif char == "m":
            total, number = total + float(number or 0) * 60, ""
        elif char == "s":
            total, number = total + float(number or 0), ""
    return total + float(number or 0)


def pool_row(dev_id: str):
    """The holdout record behind one dev item: reference reply and the quality slice columns."""
    sheet = pd.read_csv(DEV, dtype=str, keep_default_na=False).set_index("dev_id")
    pool = eval_pool().assign(record_id=lambda d: d["record_id"].astype(str)).set_index("record_id")
    return pool.loc[str(sheet.at[dev_id, "record_id"])]


def append_run(path: Path, session: dict) -> dict:
    """Append a run to the manifest, never overwrite it.

    The manifest used to be a single dict, so a later `LLM_OFFLINE=1` replay -- which reports 0
    tokens because it makes no request -- silently erased the real cost of the live run that
    produced the drafts. Legacy single-dict files are migrated into `runs[0]` on first append, and
    the migration is idempotent.
    """
    history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"runs": []}
    if "runs" not in history:
        history = {"runs": [history]}
    history["runs"].append(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    return history


def dev_requests() -> list[SupportRequest]:
    sheet = pd.read_csv(DEV, dtype=str, keep_default_na=False)
    pool = eval_pool().assign(record_id=lambda d: d["record_id"].astype(str)).set_index("record_id")
    requests = []
    for row in sheet.to_dict("records"):
        record = pool.loc[str(row["record_id"])]
        # `context` is a numpy object array, so test its size: `or []` truth-tests the array
        # and raises for an empty one.
        turns = record["context"]
        turns = list(turns) if turns is not None and len(turns) else []
        context = tuple(Turn(role=str(t["role"]), text=str(t["text"])) for t in turns)
        requests.append(SupportRequest(request_id=row["dev_id"], brand=load_config()["brand"],
                                       customer_text=str(record["customer_text_clean"]),
                                       context=context, is_followup=bool(record["is_followup"])))
    return requests


def main() -> None:
    cfg = load_config()
    model = cfg["models"]["agent"]
    cache = SQLiteCache(resolve(cfg["cache"]["path"]))
    llm = LiteLLMClient(model["name"], cache, temperature=model.get("temperature"),
                        max_tokens=model.get("max_tokens", 4096),
                        reasoning_effort=model.get("reasoning_effort"),
                        timeout=model.get("timeout", 120))
    retriever = default_retriever()
    started = datetime.now(timezone.utc)
    session = {"started_utc": started.isoformat(timespec="seconds"), "model": llm.model,
               "prompt_versions": {"routing": CLASSIFIER_PROMPT_VERSION, "draft": DRAFT_PROMPT_VERSION},
               "params": {k: model.get(k) for k in ("temperature", "max_tokens", "reasoning_effort")},
               "drafted": 0, "escalated": 0, "failed_validation": 0, "tokens": 0,
               "live_calls": 0, "offline_replay": None,
               "quota_waits": [], "failures": []}
    rows = []

    for request in dev_requests():
        while True:
            try:
                state = route(request, llm, confidence_threshold=cfg["thresholds"]["intent_confidence"],
                              union_cues=True)
                state = respond(state, llm, retriever=retriever,
                                max_attempts=cfg["drafting"]["max_attempts"],
                                max_chars=cfg["drafting"]["max_reply_chars"])
                if llm.last_usage:
                    session["tokens"] += llm.last_usage.get("total_tokens", 0)
                    session["live_calls"] += 1
                    time.sleep(8)
                break
            except Exception as error:                                  # noqa: BLE001
                message = str(error)[:400]
                tpd = TPD_RE.search(message)
                wait = parse_wait(message)
                if tpd or wait:
                    pause = min(wait or 600, 1800) + 20
                    session["quota_waits"].append(
                        {"at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "limit": "tokens_per_day" if tpd else "tokens_per_minute",
                         "used": tpd.group(2) if tpd else None, "waited_seconds": round(pause)})
                    print(f"  quota reached; waiting {pause / 60:.1f} min", flush=True)
                    time.sleep(pause)
                    continue
                session["failures"].append({"id": request.request_id, "error": message})
                print(f"  {request.request_id} FAILED: {message[:120]}", flush=True)
                state = None
                break
        if state is None:
            continue

        escalated = state.escalation.escalate
        failed = state.escalation.reason_code.value == "REPLY_FAILED_CHECKS"
        session["escalated"] += int(escalated and not failed)
        session["failed_validation"] += int(failed)
        session["drafted"] += int(bool(state.draft))
        record = pool_row(request.request_id)
        rows.append({"id": request.request_id, "message": request.customer_text,
                     "reference_reply": str(record.get("brand_reply_clean", "") or ""),
                     "reply_template_in_train": bool(record.get("reply_template_in_train", False)),
                     "reply_type": str(record.get("reply_type", "") or ""),
                     "retrieved_ids": [e.record_id for e in state.retrieved],
                     "state": state.classification.conversation_state.value,
                     "intent": state.classification.intent.value if state.classification.intent else "",
                     "escalate": "yes" if escalated else "no",
                     "reason": state.escalation.reason_code.value,
                     "retrieved": len(state.retrieved), "attempts": state.draft_attempts,
                     "draft": state.draft,
                     "validation": "; ".join(state.validation_errors)})
        print(f"  {request.request_id}: {'ESCALATE' if escalated else 'auto'} "
              f"({state.escalation.reason_code.value})"
              + (f" | draft in {state.draft_attempts} attempt(s)" if state.draft else ""), flush=True)

    session["finished_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # A run with no live call is a cache replay: its 0 tokens say nothing about what the drafts cost.
    session["offline_replay"] = session["live_calls"] == 0
    OUT.mkdir(parents=True, exist_ok=True)
    lines = ["# Dev drafts (Phase 10)", "",
             "_Generated by `uv run python scripts/draft_dev_replies.py` over the 40 dev items. Dev "
             "only: the golden set is never drafted for, and is never used as retrieval data, prompt "
             "examples or tuning input. Dev labels are ChatGPT-assisted, so nothing here is a "
             "reported result — it is a smoke test of the response pipeline._", "",
             f"Model `{llm.model}`, routing prompt `{CLASSIFIER_PROMPT_VERSION}`, draft prompt "
             f"`{DRAFT_PROMPT_VERSION}`.", "",
             f"{session['drafted']} drafted, {session['escalated']} escalated by policy (no reply "
             f"drafted), {session['failed_validation']} escalated after failing validation.", "",
             "| id | decision | reason | retrieved | attempts | draft | validation |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        draft = (r["draft"] or "—").replace("|", "/")[:150]
        bad = (r["validation"] or "—").replace("|", "/")[:90]
        lines.append(f"| {r['id']} | {r['escalate']} | `{r['reason']}` | {r['retrieved']} | "
                     f"{r['attempts']} | {draft} | {bad} |")
    (OUT / "dev_drafts.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (OUT / "dev_drafts.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    append_run(OUT / "dev_drafts_run.json", session)
    print(f"\nwrote {(OUT / 'dev_drafts.md').relative_to(ROOT)}: {session['drafted']} drafted, "
          f"{session['escalated']} escalated, {session['failed_validation']} failed validation, "
          f"{session['tokens']} tokens")


if __name__ == "__main__":
    main()
