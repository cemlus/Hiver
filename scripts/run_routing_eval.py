"""Score every routing system against the locked golden set.

Run from the repo root:   uv run python scripts/run_routing_eval.py [--systems majority,tfidf_lr]

Primary reference: `data/golden/golden_final.csv` (human labels + adjudication).
Sensitivity cross-check: `data/golden/golden_labeling_sheet.csv` (the primary human labels alone).
Neither file is ever written to, and nothing here tunes anything: the golden set is evaluation-only.

Writes:
  results/eval/routing_baselines.md          the report
  results/eval/predictions/<system>.jsonl    one AgentOutput per line, per system
  results/eval/routing_baselines_run.json    run manifest (versions, hashes, provenance, timing)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import load_config, resolve  # noqa: E402
from src.contracts import ConversationState, GoldenExample, Intent, SupportRequest, Turn  # noqa: E402
from src.dataprep.loaders import eval_pool  # noqa: E402
from src.eval.baselines import BASELINES  # noqa: E402
from src.eval.metrics import MUST_ESCALATE_LIMITATION, RoutingResult, evaluate  # noqa: E402
from src.eval.training_labels import provenance_summary, training_corpus  # noqa: E402

GOLDEN = ROOT / "data" / "golden"
OUT = ROOT / "results" / "eval"
HEADLINE = ["state_accuracy", "state_macro_f1", "intent_macro_f1", "escalation_precision",
            "escalation_recall", "must_escalate_recall_cue_blind", "joint_routing_correctness"]


def load_examples(labels_file: Path) -> list[GoldenExample]:
    labels = pd.read_csv(labels_file, dtype=str, keep_default_na=False)
    key = pd.read_csv(GOLDEN / "golden_sample_key.csv", dtype=str).set_index("golden_id")
    pool = eval_pool()
    pool = pool.assign(record_id=pool["record_id"].astype(str)).set_index("record_id")
    examples = []
    for row in labels.to_dict("records"):
        record = pool.loc[row["record_id"]]
        context = tuple(Turn(role=str(t["role"]), text=str(t["text"])) for t in record["context"])
        request = SupportRequest(request_id=row["golden_id"], brand=load_config()["brand"],
                                 customer_text=record["customer_text_clean"], context=context,
                                 is_followup=bool(record["is_followup"]))
        examples.append(GoldenExample(
            request=request,
            label_conversation_state=ConversationState(row["conversation_state"]),
            label_intent=Intent(row["intent"]) if row["intent"] else None,
            label_escalate=row["escalate"] == "yes",
            label_confidence=row.get("label_confidence", ""),
            slice=key.loc[row["golden_id"], "slice"]))
    return examples


def metric_table(results: list[RoutingResult]) -> list[str]:
    head = ["system", *[k.replace("_", " ") for k in HEADLINE]]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in results:
        cells = []
        for key in HEADLINE:
            m = r.metrics[key]
            cells.append("–" if m.value != m.value else f"{m.value:.2f} [{m.lo:.2f}–{m.hi:.2f}]")
        lines.append(f"| `{r.system}` | " + " | ".join(cells) + " |")
    return lines + [""]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--systems", default=",".join(BASELINES), help="comma-separated system names")
    parser.add_argument("--boot", type=int, default=10_000, help="bootstrap resamples")
    args = parser.parse_args()
    systems = [s for s in args.systems.split(",") if s]
    unknown = [s for s in systems if s not in BASELINES]
    if unknown:
        sys.exit(f"unknown system(s): {unknown}. Available: {sorted(BASELINES)}")

    cfg = load_config()
    started = datetime.now(timezone.utc)
    final = load_examples(GOLDEN / "golden_final.csv")
    human = load_examples(GOLDEN / "golden_labeling_sheet.csv")
    (OUT / "predictions").mkdir(parents=True, exist_ok=True)

    results, human_results, slice_results, timings = [], [], {}, {}
    for name in systems:
        t0 = time.time()
        predictions = BASELINES[name](final)
        timings[name] = round(time.time() - t0, 3)
        with (OUT / "predictions" / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for p in predictions:
                fh.write(p.model_dump_json() + "\n")
        results.append(evaluate(final, predictions, name, n_boot=args.boot, seed=cfg["seed"]))
        human_results.append(evaluate(human, predictions, name, n_boot=args.boot, seed=cfg["seed"]))
        for slice_name in ("random", "stratified"):
            subset = [e for e in final if e.slice.startswith(slice_name)]
            ids = {e.request.request_id for e in subset}
            slice_results.setdefault(slice_name, []).append(
                evaluate(subset, [p for p in predictions if p.request_id in ids], name,
                         n_boot=max(args.boot // 5, 1000), seed=cfg["seed"]))

    best = max(results, key=lambda r: r.metrics["joint_routing_correctness"].value)
    corpus = training_corpus()
    lines = [
        "# Routing baselines on the golden set", "",
        f"_Generated by `uv run python scripts/run_routing_eval.py`. Primary reference: "
        f"`golden_final.csv` (human labels + adjudication), {len(final)} items. No LLM calls: these "
        "are the non-LLM floor the agent must beat. Nothing here is tuned on the golden set._", "",
        "## Headline (primary reference: final adjudicated labels)", "",
        *metric_table(results),
        f"> **{MUST_ESCALATE_LIMITATION}**", "",
        "## Sensitivity: the same systems against the primary human labels only", "",
        *metric_table(human_results),
        "Differences between the two tables come from the 39 fields adjudication changed across 29 "
        "items, not from the systems.", "",
    ]
    for slice_name, rows in slice_results.items():
        n = len([e for e in final if e.slice.startswith(slice_name)])
        lines += [f"## Slice: {slice_name} ({n} items)", "", *metric_table(rows)]
    lines += [
        f"## Per-intent F1 — best system by joint routing (`{best.system}`)", "",
        "| intent | precision | recall | F1 | gold support |", "|---|---|---|---|---|",
    ]
    for intent, scores in sorted(best.per_intent.items(), key=lambda kv: -kv[1]["support"]):
        flag = " ⚠ too few items" if scores["support"] < 10 else ""
        lines.append(f"| `{intent}` | {scores['precision']:.2f} | {scores['recall']:.2f} | "
                     f"{scores['f1']:.2f} | {scores['support']}{flag} |")
    lines += ["", "⚠ marks intents with fewer than 10 gold items, where per-intent F1 is too "
              "unstable to report as a result.", "",
              "## Training data for the weakly supervised baseline", "",
              f"`tfidf_lr` trains on {len(corpus)} labelled non-golden records "
              f"({int((corpus['intent'] != '').sum())} with an intent, "
              f"{int((corpus['conversation_state'] != '').sum())} with a state); zero overlap with "
              "the golden set is asserted in code.", "",
              "| sources | items | with intent | with state |", "|---|---|---|---|"]
    for row in provenance_summary().to_dict("records"):
        lines.append(f"| {row['sources']} | {row['items']} | {row['with_intent']} | {row['with_state']} |")
    lines += ["", "**Every label above is assistant-coded or LLM-drafted, never independent human "
              "annotation, so `tfidf_lr` is weakly supervised and its ceiling is the quality of "
              "those labels.**", ""]

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "routing_baselines.md").write_text("\n".join(lines), encoding="utf-8")

    manifest = {
        "run": "routing_baselines",
        "systems": systems,
        "llm_calls": 0,
        "started_utc": started.isoformat(timespec="seconds"),
        "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds_per_system": timings,
        "bootstrap_resamples": args.boot,
        "seed": cfg["seed"],
        "codebook_version": cfg["codebook_version"],
        "taxonomy_status": "frozen", "escalation_status": "frozen",
        "golden_lock_sha256": (GOLDEN / "golden.lock").read_text().split()[0],
        "golden_final_sha256": hashlib.sha256((GOLDEN / "golden_final.csv").read_bytes()).hexdigest(),
        "training_corpus": {"items": int(len(corpus)),
                            "with_intent": int((corpus["intent"] != "").sum()),
                            "sources": provenance_summary().to_dict("records"),
                            "weakly_supervised": True},
        "must_escalate_limitation": MUST_ESCALATE_LIMITATION,
    }
    (OUT / "routing_baselines_run.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                                    encoding="utf-8")
    print(f"wrote {(OUT / 'routing_baselines.md').relative_to(ROOT)} and the run manifest")
    for r in results:
        print(f"  {r.system:16s} joint={r.metrics['joint_routing_correctness'].value:.3f} "
              f"state={r.metrics['state_accuracy'].value:.3f} "
              f"intentF1={r.metrics['intent_macro_f1'].value:.3f} "
              f"escP/R={r.metrics['escalation_precision'].value:.2f}/"
              f"{r.metrics['escalation_recall'].value:.2f}")


if __name__ == "__main__":
    main()
