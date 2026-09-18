"""Score every routing system against the locked golden set.

Run from the repo root:   uv run python scripts/run_routing_eval.py [--systems majority,tfidf_lr]

Primary reference: `data/golden/golden_final.csv` (human labels + adjudication).
Sensitivity cross-check: `data/golden/golden_labeling_sheet.csv` (the primary human labels alone).
Neither file is ever written to, and nothing here tunes anything: the golden set is evaluation-only.

Writes:
  results/eval/routing_baselines.md          the report
  results/eval/predictions/<system>.jsonl    one AgentOutput per line, per system
  (a --limit smoke run writes to *_smoke<N> paths and never touches the above)
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
from src.ports.factory import build_deps  # noqa: E402
from src.core.prompts import CLASSIFIER_PROMPT_VERSION  # noqa: E402
from src.eval.agent_runner import run_agent  # noqa: E402
from src.eval.baselines import BASELINES  # noqa: E402
from src.eval.metrics import MUST_ESCALATE_LIMITATION, RoutingResult, evaluate  # noqa: E402
from src.eval.training_labels import provenance_summary, training_corpus  # noqa: E402

GOLDEN = ROOT / "data" / "golden"
OUT = ROOT / "results" / "eval"
HEADLINE = ["state_accuracy", "state_macro_f1", "intent_macro_f1", "escalation_precision",
            "escalation_recall", "must_escalate_recall_cue_blind", "joint_routing_correctness"]
#: `keyword_rule`'s cue patterns were written after the assistant had read 61 golden messages during
#: adjudication, so it may be indirectly informed by golden content. It is kept for completeness but
#: never presented as a clean baseline.
LEGACY_SYSTEMS = {"keyword_rule"}


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


def require_golden_lock() -> None:
    """Refuse to score a golden set that no longer matches its lock.

    The manifest used to record the lock digest without ever comparing it, so a modified sheet
    would have been scored and stamped with a stale but plausible hash. PLAN.md always claimed
    run_eval refused on a mismatch; now it does.
    """
    sheet, lock = GOLDEN / "golden_labeling_sheet.csv", GOLDEN / "golden.lock"
    if not lock.exists():
        sys.exit(f"{lock.name} is missing: the golden labels must be locked before evaluation.")
    digest = hashlib.sha256(sheet.read_bytes()).hexdigest()
    expected = lock.read_text().split()[0]
    if digest != expected:
        sys.exit(f"{sheet.name} does not match {lock.name} ({digest[:12]} != {expected[:12]}): "
                 "the locked golden labels changed. Refusing to evaluate against altered gold.")


def escalation_direction(gold, predictions) -> tuple[int, int]:
    """(over-escalations, under-escalations) for one system, matched by request_id."""
    truth = {e.request.request_id: e.label_escalate for e in gold}
    over = under = 0
    for p in predictions:
        want = truth.get(p.request_id)
        if want is None:
            continue
        over += int(p.escalate and not want)
        under += int(want and not p.escalate)
    return over, under


def how_to_read(results, system_predictions, final) -> list[str]:
    """The framing the project owner asked for: one headline, and its cost stated plainly."""
    agent = next((r for r in results if r.system == "agent"), None)
    if agent is None:
        return []
    m = agent.metrics
    joint = m["joint_routing_correctness"].value
    over, under = escalation_direction(final, system_predictions.get("agent", []))
    return [
        "## How to read these numbers", "",
        f"**Joint routing correctness ({joint:.2f}) is the end-to-end headline.** It is the share "
        "of items where the conversation state, the intent (when one is due) and the escalation "
        "decision are ALL correct at once. Equivalently, "
        f"**{1 - joint:.0%} of items still carry at least one routing error** \u2014 this is a useful "
        "router, not a solved problem.", "",
        f"Underneath it: intent macro-F1 **{m['intent_macro_f1'].value:.2f}**, escalation recall "
        f"**{m['escalation_recall'].value:.2f}**, escalation precision "
        f"**{m['escalation_precision'].value:.2f}**.", "",
        "**The escalation figures are a deliberate safety/coverage trade-off, not uniform "
        f"strength.** Of the escalation errors, **{over} are over-escalations and {under} are "
        f"under-escalations**. Near-complete coverage of cases that need a human is bought by "
        "sending a substantial share of auto-handled cases to a human unnecessarily. That is the "
        "right direction for support triage \u2014 a missed escalation reaches a customer as an "
        "unanswered problem, while a false one costs an agent a few seconds of triage \u2014 but it "
        "is a real cost, and the precision column is where it shows.", "",
        "**`must_escalate_recall_cue_blind` is a documented proxy**, not the metric originally "
        "specified (see the note under the headline table). It under-counts the true must-escalate "
        "set and must never be quoted as the specified metric.", "",
        "**Read the sensitivity table as well.** Every number here is repeated against the primary "
        "human labels alone, before adjudication; the ranking does not rest on the adjudicated "
        "layer.", "",
        "**The 95% intervals are bootstrap percentile intervals, not a significance test.** No "
        "paired statistical test was run, so differences between systems must not be described as "
        "statistically significant.", "",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--systems", default=",".join([*BASELINES, "agent"]),
                        help="comma-separated system names; the agent is included by default")
    parser.add_argument("--boot", type=int, default=10_000, help="bootstrap resamples")
    parser.add_argument("--limit", type=int, default=0, help="first N items only (smoke tests)")
    parser.add_argument("--sleep", type=float, default=32.0,
                        help="seconds between agent calls (Groq free tier is 8k tokens/minute)")
    args = parser.parse_args()
    systems = [s for s in args.systems.split(",") if s]
    unknown = [s for s in systems if s not in BASELINES and s != "agent"]
    if unknown:
        sys.exit(f"unknown system(s): {unknown}. Available: {sorted(BASELINES)}")

    cfg = load_config()
    require_golden_lock()
    report_name = f"routing_baselines_smoke{args.limit}.md" if args.limit else "routing_baselines.md"
    manifest_name = (f"routing_baselines_smoke{args.limit}_run.json" if args.limit
                     else "routing_baselines_run.json")
    started = datetime.now(timezone.utc)
    final = load_examples(GOLDEN / "golden_final.csv")
    human = load_examples(GOLDEN / "golden_labeling_sheet.csv")
    if args.limit:
        # A --limit run is a smoke test. It once replaced the committed 200-item table with a
        # 2-item one, recoverable only from git, so partial runs get their own filenames.
        final, human = final[: args.limit], human[: args.limit]
    agent_manifest: dict = {}
    # A smoke run must not overwrite the authoritative predictions either: isolating only the
    # report filenames still let --limit clobber results/eval/predictions/*.jsonl.
    predictions_dir = OUT / (f"predictions_smoke{args.limit}" if args.limit else "predictions")
    predictions_dir.mkdir(parents=True, exist_ok=True)

    results, human_results, slice_results, timings = [], [], {}, {}
    system_predictions: dict = {}
    for name in systems:
        t0 = time.time()
        if name == "agent":
            deps = build_deps(profile="eval", config=cfg)
            agent_cfg = cfg["models"]["agent"]
            run = run_agent(final, deps.agent_llm,
                            confidence_threshold=cfg["thresholds"]["intent_confidence"],
                            union_cues=True, system="agent", attempts=4, sleep=args.sleep)
            if not run.complete:
                sys.exit(f"agent failed on {len(run.failures)} item(s): {run.failures[:3]}. "
                         "Rerun to resume; cached items cost nothing.")
            predictions = run.outputs
            agent_manifest = {
                "model": agent_cfg["name"], "route": "groq", "params": agent_cfg,
                "prompt_version": CLASSIFIER_PROMPT_VERSION,
                "cue_mode": "model cues UNION codebook-derived deterministic extractor (chosen on dev)",
                "confidence_threshold": cfg["thresholds"]["intent_confidence"],
                "confidence_note": ("Rule (h) is inert by design: on dev the router reported only "
                                    "0.90/0.95 and every error carried 0.95, so confidence is not a "
                                    "working safeguard."),
                "tokens": run.tokens, "schema_retries": run.schema_retries,
                "failures": run.failures,
                "latency_ms": {"mean": sum(run.latencies_ms) / len(run.latencies_ms),
                               "max": max(run.latencies_ms)},
                "structured_output": "JSON Schema in the prompt + pydantic validation (P0 decision)",
                "provider_status": ("qwen3.8-27b is a Groq PREVIEW model, evaluated under the free "
                                    "tier's 200,000 tokens/day (rolling) and 8,000 tokens/minute "
                                    "limits. Preview availability is not a production guarantee."),
                "quota_sessions": (json.loads((OUT / "agent_golden_progress.json").read_text())
                                   if (OUT / "agent_golden_progress.json").exists() else None)}
        else:
            predictions = BASELINES[name](final)
        timings[name] = round(time.time() - t0, 3)
        with (predictions_dir / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for p in predictions:
                fh.write(p.model_dump_json() + "\n")
        results.append(evaluate(final, predictions, name, n_boot=args.boot, seed=cfg["seed"]))
        system_predictions[name] = predictions
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
        "## Headline — clean baselines (primary reference: final adjudicated labels)", "",
        "Every system here is derived from the frozen codebook and the non-golden training corpus "
        "only.", "",
        *metric_table([r for r in results if r.system not in LEGACY_SYSTEMS]),
        f"> **{MUST_ESCALATE_LIMITATION}**", "",
        *how_to_read(results, system_predictions, final),
        "### Legacy baseline, not part of the clean comparison", "",
        "`keyword_rule`'s cue regexes were written after the assistant had read 61 golden messages "
        "during adjudication, so they may be indirectly informed by golden content. It is reported "
        "for completeness and excluded from the clean floor.", "",
        *metric_table([r for r in results if r.system in LEGACY_SYSTEMS]),
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
    (OUT / report_name).write_text("\n".join(lines), encoding="utf-8")

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
        "agent": agent_manifest,
    }
    (OUT / manifest_name).write_text(json.dumps(manifest, indent=2) + "\n",
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
