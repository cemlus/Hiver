"""Draw the 40-item dev set from the holdout eval pool, for escalation calibration.

Run once from the repo root:   uv run python scripts/sample_dev.py   (--force to redraw)

Writes, into data/golden/:
  dev_labeling_sheet.csv   one row per item; label and cue columns left blank for a human.
                           Blind: it doesn't say which slice an item came from.
  dev_labeling_sheet.md    the same items with their context, to read while labelling
  dev_sample_key.csv       each item's slice and thread. Golden sampling must exclude these threads.

Dev is for tuning only (escalation calibration, later thresholds). It is never a reported result,
never few-shot, and never in the retrieval index. The golden set is NOT sampled here: it waits
until the taxonomy and the escalation policy are both frozen.

Targeted items are found with input-side fields only (the message, its context,
customer_escalation_signals). These are weak hints for finding candidates, not labels.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import load_config  # noqa: E402
from src.dataprep.loaders import eval_pool  # noqa: E402

OUT = ROOT / "data" / "golden"
N_RANDOM = 16
PER_BEHAVIOUR = 4

ACCOUNT = re.compile(r"\b(?:account|sign(?:ed)? ?in|log ?in|password|e-?mail|gamertag|hacked|recover\w*)\b", re.I)
REPAIR = re.compile(r"\b(?:repair\w*|replace\w*|warranty|broken|won'?t turn on|dead|no signal|disc drive|overheat\w*)\b", re.I)


def has(signals, code: str) -> bool:
    return code in list(signals)


def brand_asked_last(context) -> bool:
    """The last context turn is a brand question: the customer is answering a clarification."""
    turns = list(context)
    return bool(turns) and turns[-1]["role"] == "brand" and "?" in turns[-1]["text"]


# The escalation behaviours the codebook's calibration plan lists, and how to find candidates.
BEHAVIOURS = {
    "strong_anger": lambda d: d["customer_escalation_signals"].map(lambda s: has(s, "anger")),
    "repeat_contact": lambda d: d["customer_escalation_signals"].map(
        lambda s: has(s, "repeat_contact_cue") or has(s, "prior_contact")),
    "account_specific": lambda d: d["customer_text_clean"].map(lambda t: bool(ACCOUNT.search(t))),
    "vague_low_confidence": lambda d: (d["n_words"] <= 6) & ~d["is_followup"],
    "after_clarification": lambda d: d["is_followup"] & d["context"].map(brand_asked_last),
    "repair_replacement": lambda d: d["customer_text_clean"].map(lambda t: bool(REPAIR.search(t))),
}

LABEL_COLUMNS = [
    "conversation_state", "intent", "secondary_intents", "risk_level", "escalate", "reason_code",
    "label_confidence",
    "cue_strong_anger", "cue_repeat_contact", "cue_steps_already_failed", "cue_account_specific_action",
    "cue_prior_clarification", "cue_repair_or_replacement", "cue_account_compromised",
    "cue_harm_or_legal", "cue_money_dispute", "notes", "labeler",
]


def draw(pool: pd.DataFrame, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    pool = pool.iloc[rng.permutation(len(pool))].reset_index(drop=True)   # seeded order
    taken: set[str] = set()                                               # one item per thread
    picks = []
    for name, find in BEHAVIOURS.items():
        candidates = pool[find(pool) & ~pool["thread_id"].isin(taken)].drop_duplicates("thread_id")
        chosen = candidates.head(PER_BEHAVIOUR)
        assert len(chosen) == PER_BEHAVIOUR, f"not enough candidates for {name}"
        taken |= set(chosen["thread_id"])
        picks.append(chosen.assign(slice=f"targeted:{name}"))
    rest = pool[~pool["thread_id"].isin(taken)].drop_duplicates("thread_id").head(N_RANDOM)
    picks.append(rest.assign(slice="random"))
    dev = pd.concat(picks)
    dev = dev.iloc[rng.permutation(len(dev))].reset_index(drop=True)      # blind order
    dev.insert(0, "dev_id", [f"D{i:02d}" for i in range(1, len(dev) + 1)])
    return dev


def write_sheet_md(dev: pd.DataFrame, path: Path) -> None:
    lines = [
        "# Dev labelling sheet (40 items)",
        "",
        "_Label with `data/codebook.md` and write labels in `dev_labeling_sheet.csv`. Use the message "
        "and its context only; the historical brand reply is deliberately not shown. Cue columns are "
        "`yes` / `no`. `label_confidence` is `high` / `medium` / `low`. No model pre-fill._",
        "",
    ]
    for r in dev.to_dict("records"):
        kind = "follow-up" if r["is_followup"] else "first contact"
        lines.append(f"**{r['dev_id']}** · `{r['record_id']}` · {kind}")
        lines += [f"  - _{t['role']}_: {str(t['text']).replace(chr(10), ' ')}" for t in r["context"]]
        lines += [f"  - **customer:** {r['customer_text_clean'].replace(chr(10), ' ')}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--force", action="store_true", help="overwrite an existing dev sample")
    args = parser.parse_args()
    sheet = OUT / "dev_labeling_sheet.csv"
    if sheet.exists() and not args.force:
        sys.exit(f"{sheet} exists; the dev set is drawn once. Use --force to redraw.")

    dev = draw(eval_pool(), load_config()["seed"])
    assert dev["thread_id"].is_unique and (dev["split"] == "holdout").all() and dev["eval_eligible"].all()
    OUT.mkdir(parents=True, exist_ok=True)
    blank = pd.DataFrame("", index=dev.index, columns=LABEL_COLUMNS)
    pd.concat([dev[["dev_id", "record_id"]], blank], axis=1).to_csv(sheet, index=False)
    dev[["dev_id", "record_id", "thread_id", "slice", "is_followup", "created_at"]].to_csv(
        OUT / "dev_sample_key.csv", index=False)
    write_sheet_md(dev, OUT / "dev_labeling_sheet.md")
    print(f"wrote {sheet}, dev_labeling_sheet.md and dev_sample_key.csv "
          f"({len(dev)} items: {dev['slice'].value_counts().to_dict()})")


if __name__ == "__main__":
    main()
