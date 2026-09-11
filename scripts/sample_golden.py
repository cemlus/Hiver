"""Draw the 200-item golden set from the holdout eval pool and write the blind labelling sheet.

Run once from the repo root:   uv run python scripts/sample_golden.py   (--force to redraw)

Writes, into data/golden/:
  golden_labeling_sheet.csv  one row per item. The scored columns (conversation_state, intent,
                             escalate, label_confidence) and the optional reference columns are
                             left blank for the human labeller. Blind: no slice, no model labels.
  golden_labeling_sheet.md   the same items with their context, plus a quick reference to the
                             frozen codebook, to read while labelling
  golden_sample_key.csv      each item's slice, thread and analysis fields

Sampling runs only once the taxonomy and the escalation policy are both frozen:
  - pool: loaders.eval_pool() (holdout, and no near-duplicate of a train message)
  - minus every dev thread, and every message that is a near-duplicate of a dev message
  - one item per thread, and no two golden messages that are near-duplicates of each other
  - 120 random first (an unbiased slice of the pool), then 80 stratified: 10 per stratum below,
    found with input-side fields only. Strata are candidate finders, not labels.

The golden set is for evaluation only: never for training, few-shot examples, retrieval, or
prompt, threshold or rule tuning. The labelling protocol is in data/golden/LABELING.md.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import load_config  # noqa: E402
from src.dataprep.loaders import eval_pool  # noqa: E402
from src.dataprep.splits import NEAR_DUP_THRESHOLD, char_vectorizer  # noqa: E402

OUT = ROOT / "data" / "golden"
SPEC = ROOT / "data" / "taxonomy" / "taxonomy_v1.yaml"
N_RANDOM = 120
PER_STRATUM = 10

SCORED = ["conversation_state", "intent", "escalate", "label_confidence"]
CUES = ["cue_strong_anger", "cue_repeat_contact", "cue_steps_already_failed", "cue_account_specific_action",
        "cue_prior_clarification", "cue_repair_or_replacement", "cue_account_compromised",
        "cue_harm_or_legal", "cue_money_dispute"]
REFERENCE = ["secondary_intents", "risk_level", "reason_code", *CUES, "notes"]


def text_has(pattern: str):
    rx = re.compile(pattern, re.I)
    return lambda d: d["customer_text_clean"].map(lambda t: bool(rx.search(t)))


def signal(code: str):
    return lambda d: d["customer_escalation_signals"].map(lambda s: code in list(s))


# Rarest first, so the rare strata get first pick of shared candidates.
STRATA = {
    "account_security": lambda d: signal("security")(d) | text_has(
        r"\b(?:hack\w*|compromis\w*|unauthori[sz]ed|stolen|someone (?:else )?(?:has|is using|logged|changed))\b")(d),
    "enforcement": text_has(r"\b(?:bann?(?:ed)?|suspen\w*|enforcement|reported|gamerpic|harass\w*|cheat\w*|code of conduct)\b"),
    "support_complaint": text_has(
        r"\b(?:no ?one|nobody|still waiting|ignor\w*|(?:chat|phone) (?:team|support|agent)s?|customer (?:service|support)"
        r"|support team|useless|unhelpful|no response|never (?:replied|responded|got back))\b"),
    "purchases_billing": text_has(r"\b(?:refund\w*|charg(?:e|ed|ing)|payment|billing|credit card|paypal|pre-?order\w*|purchas\w*|bought)\b"),
    "codes_subscriptions": text_has(r"\b(?:codes?|redeem\w*|gift ?card|game ?pass|gold|subscription|season pass|dlc|trial)\b"),
    "vague": lambda d: (d["n_words"] <= 6) & ~d["is_followup"],
    "anger": signal("anger"),
    "steps_failed_followup": lambda d: d["is_followup"] & text_has(
        r"\b(?:still|tried|didn'?t work|doesn'?t work|not working|same (?:thing|issue|error|problem)|already)\b")(d),
}


def draw(pool: pd.DataFrame, dev_texts: pd.Series, seed: int) -> tuple[pd.DataFrame, int]:
    rng = np.random.default_rng(seed)
    vec = char_vectorizer().fit(pd.concat([pool["customer_text_clean"], dev_texts]))
    X = vec.transform(pool["customer_text_clean"])
    near_dev = (X @ vec.transform(dev_texts).T).max(axis=1).toarray().ravel() >= NEAR_DUP_THRESHOLD
    order = rng.permutation(len(pool))                                    # seeded order
    threads = pool["thread_id"].to_numpy()
    picked: list[int] = []
    slices: list[str] = []
    taken: set[str] = set()

    def ok(i: int) -> bool:
        if near_dev[i] or threads[i] in taken:
            return False
        return not picked or (X[picked] @ X[i].T).max() < NEAR_DUP_THRESHOLD

    def fill(mask: np.ndarray, n: int, name: str) -> None:
        got = 0
        for i in order:
            if got == n:
                break
            if mask[i] and ok(i):
                picked.append(i)
                slices.append(name)
                taken.add(threads[i])
                got += 1
        assert got == n, f"only {got} candidates for {name}"

    fill(np.ones(len(pool), dtype=bool), N_RANDOM, "random")             # random first: unbiased
    for name, find in STRATA.items():
        fill(find(pool).to_numpy(dtype=bool), PER_STRATUM, f"stratified:{name}")
    gold = pool.iloc[picked].assign(slice=slices)
    gold = gold.iloc[rng.permutation(len(gold))].reset_index(drop=True)  # blind order
    gold.insert(0, "golden_id", [f"G{i:03d}" for i in range(1, len(gold) + 1)])
    return gold, int(near_dev.sum())


def quick_reference(spec: dict) -> list[str]:
    no_intent = ", ".join(f"`{s}`" for s in spec["states_without_intent"])
    lines = [
        "## Quick reference (frozen codebook v1; the full rules and examples are in `data/codebook.md`)", "",
        "**Scored: fill these for every item.**", "",
        "- `conversation_state`: " + ", ".join(f"`{s['name']}`" for s in spec["conversation_states"])
        + f". Leave `intent` blank for {no_intent}.",
        "- `intent`: exactly one primary intent (T0 picks it when a message raises several issues).",
        "- `escalate`: `yes` / `no`, from the escalation rules below.",
        "- `label_confidence`: `high` / `medium` / `low`.", "",
        "**Optional reference columns** (never scored; fill them only if they help you): "
        "`secondary_intents`, `risk_level`, `reason_code`, the `cue_*` columns (`yes` / `no`) and `notes`.", "",
        "**States**", "", *[f"- `{s['name']}`: {s['definition']}" for s in spec["conversation_states"]], "",
        "**Intents**", "", *[f"- `{it['name']}`: {it['definition']}" for it in spec["intents"]], "",
        "**Risk rules**", "", *[f"- `{r[0]}` → {r[3]}: {r[1]}" for r in spec["risk_rules"]], "",
        "**Escalation (frozen)**", "", *[f"- {x}" for x in spec["escalation_combination"]], "",
    ]
    return lines


def write_sheet_md(gold: pd.DataFrame, spec: dict, path: Path) -> None:
    lines = [
        "# Golden labelling sheet (200 items)", "",
        "_Write labels in `golden_labeling_sheet.csv`, one row per item, using the frozen codebook. Use the "
        "context and the message only: the historical brand reply is deliberately not shown. **Don't look at "
        "any Claude or ChatGPT labels for these items until all 200 are done** (protocol: `LABELING.md`). "
        "Don't reorder rows or edit the IDs._", "",
        *quick_reference(spec),
        "## Items", "",
    ]
    for r in gold.to_dict("records"):
        kind = "follow-up" if r["is_followup"] else "first contact"
        lines.append(f"**{r['golden_id']}** · `{r['record_id']}` · {kind}")
        lines += [f"  - _{t['role']}_: {str(t['text']).replace(chr(10), ' ')}" for t in r["context"]]
        lines += [f"  - **customer:** {r['customer_text_clean'].replace(chr(10), ' ')}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--force", action="store_true", help="overwrite an unlabelled golden sample")
    args = parser.parse_args()
    sheet = OUT / "golden_labeling_sheet.csv"
    if (OUT / "golden.lock").exists():
        sys.exit("golden.lock exists: the human labels are locked, and the golden set is never redrawn.")
    if sheet.exists() and not args.force:
        sys.exit(f"{sheet} exists; the golden set is drawn once. Use --force to redraw an unlabelled sample.")
    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    assert spec["taxonomy_status"] == "frozen" and spec["escalation_status"] == "frozen", \
        "freeze the taxonomy and the escalation policy before sampling golden"

    pool = eval_pool()
    pool = pool.assign(record_id=pool["record_id"].astype(str), thread_id=pool["thread_id"].astype(str))
    dev = pd.read_csv(OUT / "dev_sample_key.csv", dtype=str)
    dev_texts = pool.loc[pool["record_id"].isin(dev["record_id"]), "customer_text_clean"]
    assert len(dev_texts) == len(dev), "every dev item must be in the eval pool"
    pool = pool[~pool["thread_id"].isin(dev["thread_id"])].reset_index(drop=True)

    gold, n_near_dev = draw(pool, dev_texts, load_config()["seed"])
    assert len(gold) == N_RANDOM + PER_STRATUM * len(STRATA) and gold["thread_id"].is_unique
    assert not set(gold["thread_id"]) & set(dev["thread_id"])

    blank = pd.DataFrame("", index=gold.index, columns=SCORED + REFERENCE)
    pd.concat([gold[["golden_id", "record_id"]], blank], axis=1).to_csv(sheet, index=False)
    gold[["golden_id", "record_id", "thread_id", "slice", "is_followup", "created_at", "lang",
          "reply_template_in_train"]].to_csv(OUT / "golden_sample_key.csv", index=False)
    write_sheet_md(gold, spec, OUT / "golden_labeling_sheet.md")
    print(f"pool after excluding dev threads: {len(pool)}; near-duplicates of dev messages skipped: {n_near_dev}")
    print(f"wrote {sheet.relative_to(ROOT)}, golden_labeling_sheet.md and golden_sample_key.csv "
          f"({len(gold)} items: {gold['slice'].value_counts().to_dict()})")


if __name__ == "__main__":
    main()
