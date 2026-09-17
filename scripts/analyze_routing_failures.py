"""Failure analysis for the frozen routing evaluation (Phase 9).

Run from the repo root:
    uv run python scripts/analyze_routing_failures.py

Reads (never writes) the locked golden labels and the predictions written by
`scripts/run_routing_eval.py`. Writes:
  results/eval/routing_failures.md   confusion matrices, error counts, escalation breakdown

Nothing here tunes anything: the golden set is evaluation-only, and no model, prompt,
policy, threshold or cue rule is touched. This script only reads committed artifacts.

The join key is `request_id` (the field the predictions actually carry). An earlier
ad-hoc pass joined on `golden_id`, matched nothing, and silently reported zero errors;
this script exits non-zero unless every golden item is matched, so that cannot recur.
"""
from __future__ import annotations

import collections
import io
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "data" / "golden"
EVAL = ROOT / "results" / "eval"
OUT = EVAL / "routing_failures.md"

INTENT_BEARING = {"new_issue", "issue_followup"}
DIVERGENCES = {"G064", "G079", "G179"}      # deliberate human-vs-policy divergences


def read_csv(path: Path) -> pd.DataFrame:
    """Read a label file exactly as written (invalid bytes replaced, never rewritten)."""
    text = path.read_bytes().decode("utf-8", errors="replace")
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)


def predictions(system: str) -> list[dict]:
    path = EVAL / "predictions" / f"{system}.jsonl"
    if not path.exists():
        sys.exit(f"{path.relative_to(ROOT)} is missing: run scripts/run_routing_eval.py first.")
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def score(preds: list[dict], gold: dict[str, dict]) -> dict:
    """Compare predictions to one label layer, keyed by request_id."""
    rows, matched = [], 0
    for p in preds:
        gid = p["request_id"]
        g = gold.get(gid)
        if g is None:
            continue
        matched += 1
        gs, gi = g["conversation_state"].strip(), g["intent"].strip()
        ge = g["escalate"].strip()
        ps, pi = (p.get("conversation_state") or "").strip(), (p.get("intent") or "").strip()
        pe = "yes" if p.get("escalate") is True else "no"
        rows.append({"id": gid, "gold_state": gs, "pred_state": ps, "gold_intent": gi,
                     "pred_intent": pi, "gold_esc": ge, "pred_esc": pe,
                     "reason": p.get("reason_code") or "", "scored_intent": gs in INTENT_BEARING})
    if matched != len(gold):
        sys.exit(f"join failed: matched {matched} of {len(gold)} golden items on `request_id`. "
                 "Refusing to report a failure breakdown from an incomplete join.")
    return {"rows": rows, "matched": matched}


def matrix(rows: list[dict], gold_key: str, pred_key: str, title: str,
           only_scored: bool = False) -> list[str]:
    pairs = [(r[gold_key] or "(none)", r[pred_key] or "(none)") for r in rows
             if not only_scored or r["scored_intent"]]
    labels = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    counts = collections.Counter(pairs)
    head = ["gold \\ predicted", *[f"`{c}`" for c in labels], "**total**"]
    lines = [f"**{title}**", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for g in labels:
        cells = []
        for p in labels:
            n = counts[(g, p)]
            cells.append(f"**{n}**" if n and g == p else (str(n) if n else "·"))
        total = sum(counts[(g, p)] for p in labels)
        lines.append(f"| `{g}` | " + " | ".join(cells) + f" | {total} |")
    lines.append("")
    return lines


def report(rows: list[dict], label: str) -> list[str]:
    st = [r for r in rows if r["pred_state"] != r["gold_state"]]
    it = [r for r in rows if r["scored_intent"] and r["pred_intent"] != r["gold_intent"]]
    es = [r for r in rows if r["pred_esc"] != r["gold_esc"]]
    kinds: collections.Counter = collections.Counter()
    for r in rows:
        bad = []
        if r["pred_state"] != r["gold_state"]:
            bad.append("state")
        if r["scored_intent"] and r["pred_intent"] != r["gold_intent"]:
            bad.append("intent")
        if r["pred_esc"] != r["gold_esc"]:
            bad.append("escalate")
        kinds["+".join(bad) or "correct"] += 1

    over = [r for r in es if r["gold_esc"] == "no"]
    under = [r for r in es if r["gold_esc"] == "yes"]
    n = len(rows)
    lines = [f"## {label}", "",
             f"{n} items. **{kinds['correct']} fully correct "
             f"({kinds['correct'] / n:.1%})**; {n - kinds['correct']} with at least one error.", "",
             "| error | count |", "|---|---|",
             f"| state | {len(st)} |",
             f"| intent (scored on intent-bearing gold states only) | {len(it)} |",
             f"| escalation | {len(es)} |", "",
             "**Joint failure composition** (an item may fail on more than one field)", "",
             "| pattern | items |", "|---|---|"]
    for k, v in kinds.most_common():
        lines.append(f"| {k} | {v} |")
    lines += ["", "**Escalation direction**", "",
              "| direction | count |", "|---|---|",
              f"| over-escalation (gold `no` → predicted `yes`) | {len(over)} |",
              f"| under-escalation (gold `yes` → predicted `no`) | {len(under)} |", ""]
    if under:
        lines += [f"Under-escalated items: {', '.join(sorted(r['id'] for r in under))}.", ""]
    if over:
        by_reason = collections.Counter(r["reason"] or "(none)" for r in over)
        by_intent = collections.Counter(r["gold_intent"] or "(none)" for r in over)
        lines += ["Over-escalation by policy reason code: "
                  + ", ".join(f"`{k}` {v}" for k, v in by_reason.most_common()) + ".", "",
                  "Over-escalation by gold intent: "
                  + ", ".join(f"`{k}` {v}" for k, v in by_intent.most_common()) + ".", ""]
        hit = sorted({r["id"] for r in over} & DIVERGENCES)
        lines += [f"Of the three documented human-vs-policy divergences "
                  f"({', '.join(sorted(DIVERGENCES))}), these appear as over-escalations: "
                  f"{', '.join(hit) if hit else 'none'}. They are expected: the agent follows the "
                  "frozen policy and is scored wrong against the human label. Reported as a policy "
                  "over-escalation finding, never reconciled away.", ""]
    lines += matrix(rows, "gold_state", "pred_state", "Conversation-state confusion")
    lines += matrix(rows, "gold_intent", "pred_intent",
                    "Intent confusion (gold intent-bearing states only)", only_scored=True)
    return lines


def main() -> None:
    final = read_csv(GOLDEN / "golden_final.csv")
    human = read_csv(GOLDEN / "golden_labeling_sheet.csv")
    preds = predictions("agent")

    by_id_final = {r["golden_id"]: r for r in final.to_dict("records")}
    by_id_human = {r["golden_id"]: r for r in human.to_dict("records")}

    scored_final = score(preds, by_id_final)
    scored_human = score(preds, by_id_human)

    lines = ["# Routing agent: failure analysis", "",
             "_Generated by `uv run python scripts/analyze_routing_failures.py`. Read-only: it scores "
             "the committed predictions from `scripts/run_routing_eval.py` against the locked golden "
             "labels. Nothing is tuned here, and no model, prompt, policy, threshold or cue rule is "
             "touched._", "",
             f"Predictions: `results/eval/predictions/agent.jsonl` ({len(preds)} items), joined to the "
             f"golden labels on `request_id`; all {scored_final['matched']} items matched.", ""]
    lines += report(scored_final["rows"], "Against the final adjudicated labels (primary reference)")
    lines += report(scored_human["rows"], "Sensitivity: against the primary human labels alone")
    lines += ["---", "",
              "Intents with fewer than 10 gold items (`needs_more_context`, "
              "`support_process_complaint`, `install_download_update`) cannot support a stable "
              "per-intent read; their rows here are counts, not estimates.", ""]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} "
          f"({scored_final['matched']} items matched on request_id)")


if __name__ == "__main__":
    main()
