"""Judge the drafted dev replies, then measure agreement with the human ratings.

Run from the repo root:
    uv run python scripts/run_judge_calibration.py --lock    # after you finish rating: lock the sheet
    uv run python scripts/run_judge_calibration.py           # run the judge and report agreement

Human-first, and enforced rather than promised: this refuses to run the judge until
`data/golden/dev_human_judgments.csv` is locked by SHA-256, exactly as `golden.lock` gates the
second-opinion pass. The judge is never given the human ratings -- it only ever sees the customer
message, the retrieved evidence, the drafted reply and the historical reference.

Judge: groq/openai/gpt-oss-120b. Drafter: groq/qwen/qwen3.8-27b. Never the same model.

Dev only; the golden set is never loaded. Writes into results/eval/judge_calibration/.
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
from src.config import load_config                                          # noqa: E402
from src.contracts import SupportRequest                                    # noqa: E402
from src.core.retrieve import examples_by_id                             # noqa: E402
from src.eval.agreement import agreement_table, score_agreement             # noqa: E402
from src.eval.judge import (DIMENSIONS, JUDGE_RUBRIC_VERSION, judge_reply)  # noqa: E402
from src.eval.quota import classify                                         # noqa: E402
from src.ports.factory import build_deps                                    # noqa: E402

GOLDEN = ROOT / "data" / "golden"
SHEET = GOLDEN / "dev_human_judgments.csv"
LOCK = GOLDEN / "dev_human_judgments.lock"
DRAFTS = ROOT / "results" / "eval" / "dev_drafts.jsonl"
OUT = ROOT / "results" / "eval" / "judge_calibration"
FLAGS = ("unsupported_claims", "escalation_appropriate")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def human_ratings() -> pd.DataFrame:
    if not SHEET.exists():
        sys.exit(f"{SHEET.relative_to(ROOT)} is missing: run scripts/make_rating_sheet.py first.")
    frame = pd.read_csv(SHEET, dtype=str, keep_default_na=False)
    blank = [r["dev_id"] for r in frame.to_dict("records")
             if any(str(r[d]).strip() == "" for d in DIMENSIONS)]
    if blank:
        sys.exit(f"{len(blank)} item(s) are not rated yet: {', '.join(blank)}")
    for d in DIMENSIONS:
        bad = [r["dev_id"] for r in frame.to_dict("records")
               if str(r[d]).strip() not in {"1", "2", "3", "4", "5"}]
        if bad:
            sys.exit(f"`{d}` must be 1-5; check {', '.join(bad)}")
    return frame


def lock_sheet() -> None:
    human_ratings()                                    # refuses to lock a half-finished sheet
    LOCK.write_text(f"{digest(SHEET)}  {SHEET.name}\n", encoding="utf-8")
    print(f"locked {SHEET.relative_to(ROOT)} -> {LOCK.relative_to(ROOT)}\n"
          "The judge may now run; the ratings can no longer change without the lock failing.")


def require_lock() -> None:
    if not LOCK.exists():
        sys.exit("the human ratings are not locked. Finish rating, then run with --lock. "
                 "The judge must not run first: locking is what makes 'the judge never saw the "
                 "human scores' a guarantee rather than a claim.")
    if digest(SHEET) != LOCK.read_text().split()[0]:
        sys.exit(f"{SHEET.name} no longer matches {LOCK.name}: the human ratings changed after "
                 "locking. Refusing to report agreement against altered ratings.")


def drafted() -> list[dict]:
    rows = [json.loads(line) for line in DRAFTS.open(encoding="utf-8")]
    return [r for r in rows if (r.get("draft") or "").strip()]


def run_judge(rows: list[dict], llm, sleep: float) -> tuple[list[dict], list[dict]]:
    scored, failures = [], []
    for row in rows:
        while True:
            started = time.time()
            try:
                # Resolved from the train-only grounding corpus, never fabricated empty.
                retrieved = examples_by_id(row.get("retrieved_ids", []))
                request = SupportRequest(request_id=row["id"], brand=load_config()["brand"],
                                         customer_text=row["message"])
                result = judge_reply(request, row["draft"], retrieved, llm,
                                     reference=row.get("reference_reply", ""))
                usage = llm.last_usage or {}
                scored.append({"dev_id": row["id"], **result.scores(),
                               "unsupported_claims": result.unsupported_claims,
                               "escalation_appropriate": result.escalation_appropriate,
                               "rationale": result.rationale,
                               "reply_template_in_train": bool(row.get("reply_template_in_train")),
                               "tokens": usage.get("total_tokens"),
                               "latency_s": round(time.time() - started, 2)})
                print(f"  {row['id']}: {result.scores()}", flush=True)
                if llm.last_usage:
                    time.sleep(sleep)
                break
            except Exception as error:                              # noqa: BLE001
                message = str(error)[:400]
                limit = classify(message)
                if limit:
                    print(f"  {limit.kind}; waiting {limit.wait_seconds / 60:.1f} min", flush=True)
                    time.sleep(limit.wait_seconds)
                    continue
                failures.append({"dev_id": row["id"], "error": message})
                print(f"  {row['id']} FAILED: {message[:140]}", flush=True)
                break
    return scored, failures


def report(human: pd.DataFrame, judge: pd.DataFrame, manifest: dict) -> list[str]:
    merged = human.merge(judge, on="dev_id", suffixes=("_human", "_judge"))
    rows = [score_agreement(d, [int(v) for v in merged[f"{d}_human"]],
                            [int(v) for v in merged[f"{d}_judge"]]) for d in DIMENSIONS]
    lines = [f"# Judge calibration on dev ({JUDGE_RUBRIC_VERSION})", "",
             "_Generated by `uv run python scripts/run_judge_calibration.py`. Dev only: the golden "
             "set is not loaded, and nothing here tunes the router, the retrieval, the drafting "
             "prompt or the escalation policy._", "",
             f"Judge `{manifest['judge_model']}` rating replies drafted by "
             f"`{manifest['drafter_model']}` — different models, so nothing grades its own work.",
             "",
             f"**{len(merged)} items.** The project owner rated every reply first; the sheet was "
             "then locked by SHA-256, and the judge was never shown those ratings.", "",
             "## Agreement per dimension", ""]
    lines += agreement_table(rows)
    lines += ["",
              "Quadratic weighting means a 5-vs-4 disagreement costs far less than 5-vs-1. "
              "`bias` is the judge's mean minus the human's: positive means the judge is the more "
              "generous of the two.", "",
              f"**These intervals are wide because n={len(merged)}.** A dimension where the human or "
              "the judge used a single value throughout has no defined kappa and is shown as `–`; "
              "that is a real result about the rubric, not a gap to be filled in.", ""]

    slices = [("reply_template_in_train = True", merged[merged["reply_template_in_train"]]),
              ("reply_template_in_train = False", merged[~merged["reply_template_in_train"]])]
    lines += ["## Sliced by template reuse", "",
              "Held-out DM deflections reuse a train template 52% of the time ([P2]), so a judge "
              "anchored to the historical reply would look different on these two slices.", ""]
    for name, part in slices:
        if len(part) < 2:
            lines += [f"**{name}** — {len(part)} item(s), too few to score.", ""]
            continue
        sliced = [score_agreement(d, [int(v) for v in part[f"{d}_human"]],
                                  [int(v) for v in part[f"{d}_judge"]], n_boot=2000)
                  for d in DIMENSIONS]
        lines += [f"**{name}** ({len(part)} items)", "", *agreement_table(sliced), ""]

    lines += ["## Per-item disagreement", "",
              "| item | dimension | human | judge | gap |", "|---|---|---|---|---|"]
    for row in merged.to_dict("records"):
        for d in DIMENSIONS:
            gap = int(row[f"{d}_judge"]) - int(row[f"{d}_human"])
            if abs(gap) >= 2:
                lines.append(f"| {row['dev_id']} | `{d}` | {row[f'{d}_human']} | "
                             f"{row[f'{d}_judge']} | {gap:+d} |")
    lines.append("")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--lock", action="store_true", help="lock the finished human ratings")
    parser.add_argument("--sleep", type=float, default=8.0, help="seconds between live judge calls")
    args = parser.parse_args()
    if args.lock:
        lock_sheet()
        return

    require_lock()
    human = human_ratings()
    cfg = load_config()
    agent_name = cfg["models"]["agent"]["name"]
    llm = build_deps(profile="eval", config=cfg).judge_llm
    if llm.model == agent_name:
        sys.exit(f"judge and drafter are both {agent_name}: a model must not grade its own replies.")

    rows = [r for r in drafted() if r["id"] in set(human["dev_id"])]
    started = datetime.now(timezone.utc)
    print(f"judging {len(rows)} replies with {llm.model} (rubric {JUDGE_RUBRIC_VERSION})", flush=True)
    scored, failures = run_judge(rows, llm, args.sleep)
    if failures:
        sys.exit(f"{len(failures)} item(s) failed; rerun to resume (cached items cost nothing): "
                 f"{[f['dev_id'] for f in failures][:3]}")

    OUT.mkdir(parents=True, exist_ok=True)
    judge = pd.DataFrame(scored)
    judge.to_csv(OUT / f"judge_ratings_{JUDGE_RUBRIC_VERSION}.csv", index=False)

    manifest = {
        "rubric_version": JUDGE_RUBRIC_VERSION,
        "judge_model": llm.model,
        "drafter_model": agent_name,
        "models_are_distinct": llm.model != agent_name,
        "judge_params": {k: cfg["models"]["judge"].get(k) for k in
                         ("temperature", "max_tokens", "reasoning_effort", "timeout")},
        "items": len(scored),
        "human_sheet_sha256": digest(SHEET),
        "started_utc": started.isoformat(timespec="seconds"),
        "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_tokens": int(judge["tokens"].fillna(0).sum()),
        "failures": failures,
        "note": "Human ratings were locked before the judge ran; the judge never saw them.",
    }
    (OUT / "calibration_run.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    text = report(human, judge, manifest)
    (OUT / f"agreement_{JUDGE_RUBRIC_VERSION}.md").write_text("\n".join(text), encoding="utf-8")
    print(f"\nwrote {(OUT / f'agreement_{JUDGE_RUBRIC_VERSION}.md').relative_to(ROOT)} "
          f"({len(scored)} items, {manifest['total_tokens']} tokens)")


if __name__ == "__main__":
    main()
