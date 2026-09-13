"""A/B two production-model candidates for the routing agent, on the DEV set only.

Run from the repo root:   uv run python scripts/ab_routing_models.py [--sleep 30] [--limit N]

Both candidates get the identical routing prompt, RoutingProposal schema, frozen taxonomy, frozen
escalation policy and context reconstruction. Only the model and its generation parameters differ,
and neither model is allowed to output an escalation decision.

The golden set is never loaded here: this is a model-selection decision, so it must not touch the
evaluation data.

Writes results/eval/ab_routing_models.md and results/eval/ab_routing_models_run.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import load_config, resolve  # noqa: E402
from src.contracts import ConversationState, GoldenExample, Intent, SupportRequest, Turn, finalize  # noqa: E402
from src.contracts.models import AgentState  # noqa: E402
from src.core.classify import classify  # noqa: E402
from src.core.escalate import Cues, decide  # noqa: E402
from src.core.prompts import CLASSIFIER_PROMPT_VERSION  # noqa: E402
from src.dataprep.loaders import eval_pool  # noqa: E402
from src.eval.metrics import evaluate  # noqa: E402
from src.llm.client import LiteLLMClient  # noqa: E402
from src.ports.defaults import SQLiteCache  # noqa: E402

OUT = ROOT / "results" / "eval"
CUE_COLUMNS = {"cue_strong_anger": "strong_anger", "cue_repeat_contact": "repeat_contact",
               "cue_steps_already_failed": "steps_failed",
               "cue_account_specific_action": "account_specific_action",
               "cue_prior_clarification": "prior_clarification",
               "cue_repair_or_replacement": "repair_or_replacement",
               "cue_account_compromised": "account_compromised",
               "cue_harm_or_legal": "harm_or_legal", "cue_money_dispute": "money_dispute"}


def dev_items() -> tuple[list[GoldenExample], dict[str, dict]]:
    dev = pd.read_csv(resolve("data/golden/dev_labeling_sheet.csv"), dtype=str, keep_default_na=False)
    pool = eval_pool()
    pool = pool.assign(record_id=pool["record_id"].astype(str)).set_index("record_id")
    examples, cue_labels = [], {}
    for row in dev.to_dict("records"):
        record = pool.loc[row["record_id"]]
        examples.append(GoldenExample(
            request=SupportRequest(request_id=row["dev_id"], brand=load_config()["brand"],
                                   customer_text=record["customer_text_clean"],
                                   context=tuple(Turn(role=str(t["role"]), text=str(t["text"]))
                                                 for t in record["context"]),
                                   is_followup=bool(record["is_followup"])),
            label_conversation_state=ConversationState(row["conversation_state"]),
            label_intent=Intent(row["intent"]) if row["intent"] else None,
            label_escalate=row["escalate"] == "yes",
            label_confidence=row["label_confidence"], slice="dev"))
        cue_labels[row["dev_id"]] = {field: row[col].strip().lower() == "yes"
                                     for col, field in CUE_COLUMNS.items()}
    return examples, cue_labels


def run_candidate(name: str, model_cfg: dict, examples: list[GoldenExample], cue_labels: dict,
                  sleep: float) -> dict:
    cfg = load_config()
    llm = LiteLLMClient(model_cfg["name"], SQLiteCache(resolve(cfg["cache"]["path"])),
                        temperature=model_cfg.get("temperature"),
                        max_tokens=model_cfg.get("max_tokens", 1024),
                        reasoning_effort=model_cfg.get("reasoning_effort"),
                        timeout=model_cfg.get("timeout", 60))
    outputs, latencies, failures = [], [], []
    tokens = {"prompt": 0, "completion": 0, "total": 0, "live_calls": 0, "cached_calls": 0}
    cue_stats = {field: {"tp": 0, "fp": 0, "fn": 0, "gold": 0} for field in CUE_COLUMNS.values()}
    retries_before = llm.schema_retries

    for example in examples:
        started = time.time()
        classification = cues = None
        last_error: Exception | None = None
        for attempt in range(1, 5):           # Groq's 8k tokens/minute needs patience, not luck
            try:
                classification, cues, _ = classify(example.request, llm)
                last_error = None
                break
            except Exception as error:        # noqa: BLE001 - recorded, never hidden
                last_error = error
                if attempt < 4:
                    time.sleep(20 * attempt)
        if last_error is not None or classification is None:
            failures.append((example.request.request_id,
                             f"{type(last_error).__name__}: {str(last_error)[:140]}"))
            time.sleep(sleep)
            continue
        latencies.append((time.time() - started) * 1000)
        if llm.last_usage:
            tokens["live_calls"] += 1
            tokens["prompt"] += llm.last_usage.get("prompt_tokens", 0)
            tokens["completion"] += llm.last_usage.get("completion_tokens", 0)
            tokens["total"] += llm.last_usage.get("total_tokens", 0)
        else:
            tokens["cached_calls"] += 1
        decision = decide(classification.intent, cues)         # the model never decides this
        state = AgentState(request=example.request, classification=classification,
                           escalation=decision)
        outputs.append(finalize(state, system=name, model_versions={"agent": model_cfg["name"]}))
        gold_cues = cue_labels[example.request.request_id]
        for field, gold in gold_cues.items():
            pred = getattr(cues, field)
            s = cue_stats[field]
            s["gold"] += gold
            s["tp"] += gold and pred
            s["fp"] += pred and not gold
            s["fn"] += gold and not pred
        time.sleep(sleep)

    scored = [e for e in examples if e.request.request_id in {o.request_id for o in outputs}]
    metrics = evaluate(scored, outputs, name, n_boot=2000, seed=cfg["seed"]).metrics if outputs else {}
    tp = sum(s["tp"] for s in cue_stats.values())
    fp = sum(s["fp"] for s in cue_stats.values())
    fn = sum(s["fn"] for s in cue_stats.values())
    return {"name": name, "model": model_cfg["name"], "params": model_cfg, "metrics": metrics,
            "cue_stats": cue_stats,
            "cue_micro": {"precision": tp / (tp + fp) if tp + fp else float("nan"),
                          "recall": tp / (tp + fn) if tp + fn else float("nan")},
            "latency_ms": {"mean": sum(latencies) / len(latencies) if latencies else float("nan"),
                           "max": max(latencies) if latencies else float("nan")},
            "tokens": tokens, "failures": failures, "scored_items": len(outputs),
            "schema_retries": llm.schema_retries - retries_before}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sleep", type=float, default=30.0,
                        help="seconds between calls (Groq free tier is 8k tokens/minute)")
    parser.add_argument("--limit", type=int, default=0, help="use only the first N dev items")
    args = parser.parse_args()

    cfg = load_config()
    examples, cue_labels = dev_items()
    if args.limit:
        examples = examples[: args.limit]
    started = datetime.now(timezone.utc)
    results = [run_candidate(name, model_cfg, examples, cue_labels, args.sleep)
               for name, model_cfg in cfg["models"]["candidates"].items()]

    def cell(r, key):
        m = r["metrics"].get(key)
        return "–" if m is None or m.value != m.value else f"{m.value:.2f}"

    lines = ["# Production model A/B on the dev set", "",
             f"_Generated by `uv run python scripts/ab_routing_models.py` over {len(examples)} dev "
             f"items. Identical prompt (`{CLASSIFIER_PROMPT_VERSION}`), schema, taxonomy, escalation "
             "policy and context for both candidates; only the model differs. Neither model can "
             "output an escalation decision. The golden set is not loaded by this script._", "",
             "Dev labels are ChatGPT drafts approved by the project owner, so these are a selection "
             "signal, not a result.", "",
             "| metric | " + " | ".join(f"`{r['model']}`" for r in results) + " |",
             "|---|" + "---|" * len(results)]
    for key, label in [("state_accuracy", "state accuracy"), ("state_macro_f1", "state macro-F1"),
                       ("intent_macro_f1", "intent macro-F1"),
                       ("escalation_precision", "escalation precision"),
                       ("escalation_recall", "escalation recall"),
                       ("joint_routing_correctness", "joint routing")]:
        lines.append(f"| {label} | " + " | ".join(cell(r, key) for r in results) + " |")
    lines.append("| cue precision (micro) | " +
                 " | ".join(f"{r['cue_micro']['precision']:.2f}" for r in results) + " |")
    lines.append("| cue recall (micro) | " +
                 " | ".join(f"{r['cue_micro']['recall']:.2f}" for r in results) + " |")
    lines.append("| malformed output / schema retries | " +
                 " | ".join(str(r["schema_retries"]) for r in results) + " |")
    lines.append("| hard failures | " + " | ".join(str(len(r["failures"])) for r in results) + " |")
    lines.append("| mean latency (ms) | " +
                 " | ".join(f"{r['latency_ms']['mean']:.0f}" for r in results) + " |")
    lines.append("| prompt / completion tokens | " +
                 " | ".join(f"{r['tokens']['prompt']:,} / {r['tokens']['completion']:,}"
                            for r in results) + " |")
    lines.append("| live / cached calls | " +
                 " | ".join(f"{r['tokens']['live_calls']} / {r['tokens']['cached_calls']}"
                            for r in results) + " |")
    lines += ["", "## Per-cue recall (dev cue labels)", "",
              "| cue | gold | " + " | ".join(f"`{r['name']}`" for r in results) + " |",
              "|---|---|" + "---|" * len(results)]
    for field in CUE_COLUMNS.values():
        gold = results[0]["cue_stats"][field]["gold"]
        cells = []
        for r in results:
            s = r["cue_stats"][field]
            cells.append("–" if not s["gold"] else f"{s['tp'] / s['gold']:.2f}")
        lines.append(f"| `{field}` | {gold} | " + " | ".join(cells) + " |")
    lines.append("")
    for r in results:
        if r["failures"]:
            lines += [f"**{r['name']} failures:** " +
                      ", ".join(f"{i} ({e})" for i, e in r["failures"][:5]), ""]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ab_routing_models.md").write_text("\n".join(lines), encoding="utf-8")
    manifest = {"run": "ab_routing_models", "items": len(examples),
                "prompt_version": CLASSIFIER_PROMPT_VERSION,
                "structured_output": "JSON Schema in the prompt + pydantic validation (P0 decision), "
                                     "not provider-native json_schema",
                "started_utc": started.isoformat(timespec="seconds"),
                "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "sleep_seconds": args.sleep,
                "candidates": [{k: r[k] for k in ("name", "model", "params", "cue_micro",
                                                  "latency_ms", "tokens", "schema_retries",
                                                  "scored_items", "failures")} for r in results]}
    (OUT / "ab_routing_models_run.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n",
                                                    encoding="utf-8")
    print(f"wrote {(OUT / 'ab_routing_models.md').relative_to(ROOT)}")
    for r in results:
        m = r["metrics"]
        print(f"  {r['model']:28s} scored={r['scored_items']:2d} "
              f"state={cell(r, 'state_accuracy')} intentF1={cell(r, 'intent_macro_f1')} "
              f"escP/R={cell(r, 'escalation_precision')}/{cell(r, 'escalation_recall')} "
              f"joint={cell(r, 'joint_routing_correctness')} "
              f"cueP/R={r['cue_micro']['precision']:.2f}/{r['cue_micro']['recall']:.2f} "
              f"retries={r['schema_retries']} fails={len(r['failures'])} "
              f"lat={r['latency_ms']['mean']:.0f}ms")


if __name__ == "__main__":
    main()
