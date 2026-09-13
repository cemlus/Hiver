"""Blind LLM second opinion on the 200 golden items (label layer 2).

Run from the repo root, after the human labels are locked:
    uv run python scripts/llm_second_opinion.py            # all 200, resumable
    uv run python scripts/llm_second_opinion.py --limit 5  # smoke test
    uv run python scripts/llm_second_opinion.py --model anthropic/claude-haiku-4-5 --restart
    LLM_OFFLINE=1 uv run python scripts/llm_second_opinion.py   # replay from the LLM cache

Writes data/golden/golden_llm_labels.csv: one row per item with the model's
conversation_state, intent, escalate, label_confidence and a short rationale, plus the model name
and codebook version.

**Blind by construction:** this script never reads golden_labeling_sheet.csv. It sees the frozen
codebook and the customer message with its context, exactly what the human labeller saw. It refuses
to run until golden.lock exists, so the human labels can never be influenced by these labels.

The model is `models.judge` from config.yaml, not the agent model: the agent will later be scored
on these same items, and a second opinion from the same model and prompt would mostly reproduce the
agent's own predictions.

Every call is cached by (model, system, prompt, params), so reruns are free and resumable, and
`LLM_OFFLINE=1` replays them without an API key.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import load_config  # noqa: E402
from src.dataprep.loaders import eval_pool  # noqa: E402
from src.llm.client import CacheMissError  # noqa: E402
from src.ports.factory import build_deps  # noqa: E402

GOLDEN = ROOT / "data" / "golden"
SPEC = ROOT / "data" / "taxonomy" / "taxonomy_v1.yaml"
OUT = GOLDEN / "golden_llm_labels.csv"
METADATA = GOLDEN / "second_opinion_run.json"
COLUMNS = ["golden_id", "record_id", "conversation_state", "intent", "escalate", "label_confidence",
           "rationale", "model", "codebook_version"]

SYSTEM = ("You are labelling customer support tweets for an evaluation benchmark, following a fixed "
          "codebook. Apply the codebook exactly as written, even where you would decide differently. "
          "Answer only with the requested JSON object.")


class Label(BaseModel):
    """One labelled item. Mirrors the four scored fields the human labeller filled in."""
    conversation_state: Literal["new_issue", "issue_followup", "acknowledgement_closing", "social_offtopic"]
    intent: Literal[
        "connectivity_xbox_live", "install_download_update", "hardware_devices", "software_game_app",
        "account_access_profile", "purchases_billing_orders", "entitlements_subscriptions_codes",
        "enforcement_safety", "product_info_feedback", "support_process_complaint", "needs_more_context", ""
    ] = Field(description="empty string for acknowledgement_closing and social_offtopic")
    escalate: Literal["yes", "no"]
    label_confidence: Literal["high", "medium", "low"]
    rationale: str = Field(description="one sentence, at most 200 characters")


def codebook_prompt(spec: dict) -> str:
    """The labelling rules, rendered from the frozen spec (the same rules the human labeller used)."""
    parts = [
        "# Codebook (frozen v1)", "",
        "## Conversation states (choose exactly one)",
        *[f"- {s['name']}: {s['definition']}" for s in spec["conversation_states"]], "",
        f"States without an intent (leave intent empty): {', '.join(spec['states_without_intent'])}.", "",
        "## Intents (choose exactly one when the state carries an intent)",
    ]
    for it in spec["intents"]:
        parts += [f"- {it['name']}: {it['definition']}",
                  f"    include: {'; '.join(it['include'])}",
                  f"    exclude: {'; '.join(it['exclude'])}",
                  f"    default risk: {it['default_risk']}. escalation: {it['escalation']}"]
    parts += ["", "## Deterministic tie-breaks (apply in order)",
              *[f"- {tb['id']}: {tb['rule']}" for tb in spec["tie_breaks"]], "",
              "## Risk rules (a layer on top of the intent)",
              *[f"- {r[0]} (raises risk to {r[3]}, reason {r[4]}): {r[1]}" for r in spec["risk_rules"]], "",
              "## Escalation decision", *[f"- {line}" for line in spec["escalation_combination"]], "",
              "Rules (h) and (i) never apply here: you are labelling, not running the agent.", "",
              "## label_confidence", "- high / medium / low: how sure you are of this labelling."]
    return "\n".join(parts)


def item_prompt(record: dict) -> str:
    turns = [f"{t['role']}: {str(t['text'])}" for t in record["context"]]
    context = "\n".join(turns) if turns else "(no earlier turns)"
    return (f"# Item to label\n\n## Earlier turns in this conversation (oldest first)\n{context}\n\n"
            f"## The customer message to label\n{record['customer_text_clean']}\n\n"
            "Label this message with the codebook above. The brand's actual reply is not shown and "
            "must not be guessed at: label only what the customer message and its context support.")


def label_item(llm, prompt: str, system: str, attempts: int, backoff: float):
    """Free and free-tier endpoints return transient 429s and 500s; retry with exponential backoff.
    Returns (label, None) or (None, last_error)."""
    for attempt in range(1, attempts + 1):
        try:
            return llm.complete(prompt, system=system, schema=Label), None
        except CacheMissError:
            raise                      # offline replay: a miss is a real error, not a flaky endpoint
        except Exception as error:
            if attempt == attempts:
                return None, error
            time.sleep(backoff * 2 ** (attempt - 1))
    return None, None


def load_done() -> pd.DataFrame:
    if OUT.exists():
        return pd.read_csv(OUT, dtype=str, keep_default_na=False)
    return pd.DataFrame(columns=COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=0, help="label only the first N unlabelled items")
    parser.add_argument("--sleep", type=float, default=1.0, help="seconds between live calls (free-tier rate limits)")
    parser.add_argument("--model", default=None,
                        help="LiteLLM model string for the second opinion (default: models.judge in "
                             "config.yaml). Use another vendor when a free-tier daily quota blocks the run.")
    parser.add_argument("--restart", action="store_true",
                        help="discard existing rows and relabel every item (needed when changing --model)")
    parser.add_argument("--temperature", type=float, default=None,
                        help="override models.judge.temperature (use the value the model was probed with)")
    parser.add_argument("--max-tokens", dest="max_tokens", type=int, default=None,
                        help="override models.judge.max_tokens")
    parser.add_argument("--timeout", type=float, default=None,
                        help="override models.judge.timeout in seconds (long generations need more)")
    parser.add_argument("--attempts", type=int, default=4, help="tries per item before giving up")
    parser.add_argument("--backoff", type=float, default=20.0, help="first retry delay in seconds (doubles)")
    args = parser.parse_args()

    if not (GOLDEN / "golden.lock").exists():
        sys.exit("golden.lock is missing: lock the human labels before collecting a second opinion.")

    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    cfg = load_config()
    overrides = {k: v for k, v in (("name", args.model), ("temperature", args.temperature),
                                   ("max_tokens", args.max_tokens), ("timeout", args.timeout))
                 if v is not None}
    if overrides:                      # a different model family keeps the second opinion independent
        cfg["models"]["judge"] = {**cfg["models"]["judge"], **overrides}
    deps = build_deps(profile="eval", config=cfg)
    llm, model = deps.judge_llm, cfg["models"]["judge"]["name"]
    system = f"{SYSTEM}\n\n{codebook_prompt(spec)}"

    key = pd.read_csv(GOLDEN / "golden_sample_key.csv", dtype=str)
    pool = eval_pool()
    pool = pool.assign(record_id=pool["record_id"].astype(str)).set_index("record_id")
    done = load_done()
    if args.restart:
        done = done.iloc[0:0]
    elif len(done) and set(done["model"]) != {model}:
        sys.exit(f"{OUT.name} already holds labels from {sorted(set(done['model']))}; one second-opinion "
                 f"layer must come from one model. Rerun with --restart to relabel everything with "
                 f"{model} (cached calls are free).")
    todo = key[~key["golden_id"].isin(done["golden_id"])]
    if args.limit:
        todo = todo.head(args.limit)
    print(f"{len(done)} already labelled; labelling {len(todo)} of {len(key)} with {model}")

    rows = done.to_dict("records")
    failed: list[str] = []
    latencies: list[float] = []
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for n, item in enumerate(todo.to_dict("records"), 1):
        record = pool.loc[item["record_id"]]
        t0 = time.time()
        label, error = label_item(llm, item_prompt(record), system, args.attempts, args.backoff)
        if error is not None:                       # one bad item must not lose the finished ones
            failed.append(item["golden_id"])
            print(f"  {item['golden_id']}: FAILED after {args.attempts} attempts "
                  f"({type(error).__name__}: {str(error)[:120]})")
            continue
        latencies.append(time.time() - t0)
        rows.append({"golden_id": item["golden_id"], "record_id": item["record_id"],
                     "conversation_state": label.conversation_state, "intent": label.intent,
                     "escalate": label.escalate, "label_confidence": label.label_confidence,
                     "rationale": " ".join(label.rationale.split())[:200],
                     "model": model, "codebook_version": cfg["codebook_version"]})
        pd.DataFrame(rows, columns=COLUMNS).to_csv(OUT, index=False)   # resumable after any stop
        if n % 20 == 0:
            print(f"  {n}/{len(todo)}")
        time.sleep(args.sleep)

    out = pd.DataFrame(rows, columns=COLUMNS)
    out.to_csv(OUT, index=False)
    metadata = {
        "model": model,
        "route": "gemini-api-direct" if model.startswith("gemini/") else model.split("/")[0],
        "codebook_version": cfg["codebook_version"],
        "model_params": {k: cfg["models"]["judge"].get(k)
                         for k in ("temperature", "max_tokens", "timeout", "reasoning_effort")},
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items_labelled": len(out),
        "items_expected": len(key),
        "failed_ids": failed,
        "attempts_per_item": args.attempts,
        "sleep_seconds": args.sleep,
        "latency_seconds": {"mean": round(sum(latencies) / len(latencies), 1) if latencies else None,
                            "max": round(max(latencies), 1) if latencies else None},
        "note": ("Blind second opinion only. The primary gold labels are the locked human sheet "
                 "(golden.lock); this run never reads them."),
    }
    METADATA.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} of {len(key)} items labelled by {model}")
    print(f"wrote {METADATA.relative_to(ROOT)}")
    if failed:
        print(f"{len(failed)} item(s) failed: {', '.join(failed[:10])}{' …' if len(failed) > 10 else ''}")
    if len(out) < len(key):
        print("rerun to finish the remaining items (cached calls are free)")


if __name__ == "__main__":
    main()
