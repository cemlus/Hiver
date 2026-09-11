"""Phase 2: build the canonical exchange dataset for the configured brand.

Run from the repo root:   uv run python -m src.dataprep.build
                          uv run python -m src.dataprep.build --suggest-split-date

Reads data/raw/twcs.csv (read-only) and writes:
  data/processed/records.parquet      one row per usable customer -> brand exchange
  results/phase2_data_report.md       funnel, splits, leakage checks, weak signals,
                                      data dictionary and every cleaning decision
  results/reconstruction_samples.md   36 reconstructed exchanges for hand inspection
The hand-written blocks between <!-- manual:start --> / <!-- manual:end --> in the two
results files are kept when this is re-run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import load_config, resolve
from src.dataprep.exchanges import (
    CANNED_MIN_REPEATS, MAX_CONTEXT_AGE, MAX_CONTEXT_TURNS, MAX_PARTS, MERGE_WINDOW, MIN_WORDS,
    apply_filters, build_exchanges,
)
from src.dataprep.raw import add_language, add_threads, load_raw
from src.dataprep.splits import NEAR_DUP_THRESHOLD, assign_splits, leakage, suggest_split_date
from src.dataprep.weak_signals import (
    OUTCOME_RULES, WEAK_OUTCOME_SOURCE, brand_escalation_evidence, customer_escalation_signals,
    weak_outcome,
)

# Derived from the brand's reply or the customer's next tweet: weak labels, train split only.
TRAIN_ONLY = ["next_customer_text", "weak_outcome", "outcome_confidence", "weak_outcome_source",
              "brand_escalation_evidence"]

# The Phase 1 validation funnel (results/brand_validation.md) this rebuild is checked against.
PHASE1_FUNNEL = [20_213, 20_008, 18_741, 18_692, 18_549]

MERGE_MIN = int(MERGE_WINDOW / np.timedelta64(1, "m"))
MAX_CONTEXT_AGE_DAYS = int(MAX_CONTEXT_AGE / np.timedelta64(1, "D"))

# Column order of records.parquet, with the description used in the data dictionary.
COLUMNS = {
    "record_id": "Tweet ID of the customer tweet the brand answered",
    "thread_id": "Tweet ID of the thread's root. Splits are assigned per thread",
    "thread_started_at": "Time of the thread's root tweet (UTC). Decides the split",
    "split": "`train` (thread and exchange before `data.split_date`), `holdout` (thread started on/after it; Phase 5 samples dev/golden from it) or `excluded` (written after the split date in a thread that started before it)",
    "created_at": "Time of the customer tweet (UTC)",
    "customer_id": "Anonymised customer ID",
    "customer_prior_threads": "Earlier threads this customer had with the brand",
    "is_followup": "The message answers an earlier brand tweet (`False` = first contact)",
    "context": "Earlier turns as `[{role, text, created_at}]`, oldest first. Roles: customer, brand, other_customer, other_brand",
    "context_turns": "Number of context turns kept",
    "context_truncated": f"Context was cut: more than {MAX_CONTEXT_TURNS} earlier turns (kept the opener and the last {MAX_CONTEXT_TURNS - 1}) and/or turns older than {MAX_CONTEXT_AGE_DAYS} days dropped",
    "customer_tweet_ids": "Customer tweets merged into the message",
    "n_customer_parts": "How many customer tweets were merged",
    "customer_text": "Customer message, raw",
    "customer_text_clean": "Customer message for models: entities decoded, handles → `@user`, URLs → `<URL>`",
    "lang": "Estimated language of the message (`en` or `undetermined`; `other` is dropped)",
    "n_words": "Alphabetic words in the message (handles and URLs excluded)",
    "customer_escalation_signals": "Weak cues in the message: anger, legal_threat, security, billing_dispute, repeat_contact_cue, prior_contact",
    "reply_tweet_ids": "Brand tweets merged into the reply",
    "n_reply_parts": "How many brand tweets were merged (split replies)",
    "brand_reply": "Brand reply, raw",
    "brand_reply_clean": "Brand reply without handles, agent sign-off (`^XS`) or split markers. URLs → `<URL>`",
    "reply_created_at": "Time of the reply's first tweet (UTC)",
    "reply_delay_min": "Minutes from the customer tweet to the reply",
    "reply_type": "`substantive` (actionable, not canned), `dm_deflection` (DM request, no guidance) or `other`",
    "reply_is_canned": f"Every part of the reply is a template the brand used ≥ {CANNED_MIN_REPEATS} times",
    "reply_template": "Normalised template of the reply, for the canned and leakage checks",
    "retrieval_eligible": "May enter the grounding/RAG corpus: train split **and** substantive reply",
    "max_train_similarity": "Holdout only: highest TF-IDF cosine between this message and any train message",
    "eval_eligible": f"Holdout only: may be sampled into dev/golden (no train near-duplicate ≥ {NEAR_DUP_THRESHOLD})",
    "reply_template_in_train": "Holdout only: the same reply template also occurs in train",
    "next_customer_text": "Train only: the same customer's first answer to the reply",
    "weak_outcome": "Train only: resolved / unresolved / acknowledged / deflected / unknown (heuristic)",
    "outcome_confidence": "Train only: high / medium / low / none. How far to trust `weak_outcome`",
    "weak_outcome_source": f"Train only: `{WEAK_OUTCOME_SOURCE}`",
    "brand_escalation_evidence": "Train only: what the historical reply did: dm_request, handoff_other_channel, policy_enforcement (weak)",
}

CLEANING_DECISIONS = [
    "**Scope.** Only exchanges where the configured brand replied to a customer tweet. Brand "
    "tweets that answer nobody (announcements) are ignored.",
    f"**Split brand replies are one response.** A brand tweet answering the brand's own reply "
    f"within {MERGE_MIN} min is a continuation (`1/2`, `2/2`, trailing ` 1`). Every brand tweet "
    f"answering the same customer tweet is merged in time order, up to {MAX_PARTS} tweets.",
    f"**Split customer messages are one message.** The customer's own tweets directly before the "
    f"answered tweet (each within {MERGE_MIN} min) are merged into it, unless the brand answered "
    f"the earlier tweet separately.",
    f"**Context for follow-ups.** The parent chain before the message becomes logical turns "
    f"(consecutive tweets by one author = one turn). A brand turn shows the brand's whole merged "
    f"reply, even if the customer answered only one of its parts. Threads with more than "
    f"{MAX_CONTEXT_TURNS} earlier turns keep the opener and the last {MAX_CONTEXT_TURNS - 1}, so the "
    f"original issue survives. Turns more than {MAX_CONTEXT_AGE_DAYS} days older than the message "
    "(revived old threads) are dropped. Both cuts set `context_truncated`.",
    "**Follow-up vs first contact.** `is_followup` = the message answers an earlier brand *reply*. "
    "Answering a brand announcement (a brand tweet that replies to nobody) is a first contact, "
    "though the announcement still appears as context.",
    "**Dropped: non-English messages** (function-word estimate; see `src/dataprep/text.py`). "
    "`undetermined` messages are kept if they pass the next filter.",
    f"**Dropped: messages with < {MIN_WORDS} alphabetic words** after removing handles and URLs "
    "(\"Yes\", \"Done\", bare links). They state no issue.",
    "**Dropped: DM hand-off messages** (< 8 words mentioning DM/sent, e.g. \"DM sent\").",
    "**Dropped: exact duplicates** of the customer message (letters only, case-folded). The "
    "earliest copy is kept.",
    "**Clean text keeps the raw text next to it.** Clean text: HTML entities decoded (`&amp;` → "
    "`&`), leading @handles removed, other handles → `@user`, URLs → `<URL>`. Brand text also "
    "loses agent sign-offs (`^XS`) and split markers. Emoji and casing are kept.",
    "**reply_type.** `substantive` = a troubleshooting/guidance cue in a sentence that is not "
    "itself a DM request, and the reply is not wholly canned. `dm_deflection` = a DM request "
    "with no such guidance. `other` = the rest (clarifying questions, hand-offs, info, "
    "pleasantries, canned guidance). This is stricter than Phase 1, whose rule counted \"Can you "
    "DM us what you see when you try …\" as substantive: a hand check found about 70% of the 488 "
    "substantive-plus-DM replies were really DM requests. Phrases describing the customer's own "
    "attempts (\"when you try\", \"you've tried\") are not guidance.",
    "**Grounding corpus.** Only `retrieval_eligible` rows (train + substantive) may enter the "
    "retrieval index. DM deflections and `other` replies never do.",
    "**Split per thread, by time.** A thread whose root tweet is on/after `data.split_date` goes "
    "wholly to `holdout`. An earlier thread goes to `train`, except for exchanges written on/after "
    "the split date (revived threads). Those are `excluded` from both, so every train exchange "
    "strictly precedes every holdout thread and no thread is in both train and holdout.",
    f"**Leakage.** Holdout messages with a train near-duplicate (char TF-IDF cosine ≥ "
    f"{NEAR_DUP_THRESHOLD}) are not `eval_eligible`. Holdout replies whose template also occurs "
    "in train are flagged (`reply_template_in_train`).",
    "**Weak labels stay in train.** `weak_outcome`, `outcome_confidence`, `next_customer_text` "
    "and `brand_escalation_evidence` come from the future or from the reference reply, so they "
    "are null outside train. `customer_escalation_signals` come from the model's input and are "
    "kept everywhere.",
    "**No intent labels yet.** The Phase 1 keyword draft intents are not stored: 42% of "
    "messages match none, mostly vague requests and follow-ups that need context. Intents come "
    "from the hand-written codebook in Phase 3.",
]


def assemble(ex: pd.DataFrame, split_date: pd.Timestamp) -> pd.DataFrame:
    r = ex.copy()
    r["split"] = assign_splits(r["thread_started_at"], r["created_at"], split_date)
    train = r["split"] == "train"
    r["retrieval_eligible"] = train & (r["reply_type"] == "substantive")
    r = r.join(leakage(r))
    r["customer_escalation_signals"] = customer_escalation_signals(r["customer_text"], r["customer_prior_threads"])
    r = r.join(weak_outcome(r["next_customer_text"], r["reply_type"]))
    r["weak_outcome_source"] = WEAK_OUTCOME_SOURCE
    r["brand_escalation_evidence"] = brand_escalation_evidence(r["brand_reply"])
    for col in TRAIN_ONLY:
        r[col] = r[col].astype(object).where(train, None)
    return r[list(COLUMNS)]


# --------------------------------------------------------------------------- reports

MANUAL_START, MANUAL_END = "<!-- manual:start -->", "<!-- manual:end -->"


def _manual(path: Path, default: str) -> str:
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if MANUAL_START in text and MANUAL_END in text:
            return text[text.index(MANUAL_START): text.index(MANUAL_END) + len(MANUAL_END)]
    return f"{MANUAL_START}\n{default}\n{MANUAL_END}"


def _table(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def _counts(values: pd.Series) -> pd.DataFrame:
    exploded = values.explode().dropna()
    vc = exploded.value_counts()
    return pd.DataFrame({"code": vc.index, "exchanges": vc.to_numpy()})


def write_report(path: Path, records: pd.DataFrame, ex_all: pd.DataFrame,
                 waterfall: list[tuple[str, int]], split_date: pd.Timestamp, cfg: dict) -> None:
    funnel = pd.DataFrame(waterfall, columns=["step", "phase 2"])
    funnel["phase 1 (brand_validation.md)"] = PHASE1_FUNNEL
    funnel["difference"] = funnel["phase 2"] - funnel["phase 1 (brand_validation.md)"]

    split_rows = []
    for split, g in records.groupby("split"):
        split_rows.append({
            "split": split, "exchanges": len(g), "threads": g["thread_id"].nunique(),
            "first_contact": int((~g["is_followup"]).sum()), "followup": int(g["is_followup"].sum()),
            "substantive": int((g["reply_type"] == "substantive").sum()),
            "dm_deflection": int((g["reply_type"] == "dm_deflection").sum()),
            "other": int((g["reply_type"] == "other").sum()),
            "retrieval_eligible": int(g["retrieval_eligible"].sum()),
            "eval_eligible": int(g["eval_eligible"].sum()),
            "first_day": g["created_at"].min().date(), "last_day": g["created_at"].max().date(),
        })
    split_table = pd.DataFrame(split_rows)

    train, holdout = records[records["split"] == "train"], records[records["split"] == "holdout"]
    excluded = records[records["split"] == "excluded"]
    threads_in_both = len(set(train["thread_id"]) & set(holdout["thread_id"]))
    time_ok = train["created_at"].max() < split_date <= holdout["thread_started_at"].min()
    sim = holdout["max_train_similarity"]
    tmpl = holdout.groupby("reply_type")["reply_template_in_train"].agg(["sum", "count"]).reset_index()
    tmpl.columns = ["reply_type", "template_also_in_train", "holdout_exchanges"]
    outcome = pd.crosstab(train["weak_outcome"], train["outcome_confidence"]).reset_index()
    rules = pd.DataFrame(OUTCOME_RULES, columns=["weak_outcome", "rule", "outcome_confidence", "basis"])
    dictionary = pd.DataFrame({"column": [f"`{c}`" for c in COLUMNS], "meaning": list(COLUMNS.values())})

    usable = records
    parts = [
        f"# Phase 2 data report: {cfg['brand']}",
        "",
        "_Generated by `python -m src.dataprep.build` from `data/raw/twcs.csv`. Numbers are "
        "regenerated on each run; the notes block is hand-written and kept._",
        "",
        _manual(path, "## Notes\n\n_To be written after inspecting the samples._"),
        "",
        "## 1. Funnel (checked against Phase 1)",
        "",
        _table(funnel),
        "",
        "Phase 2 also merges split customer messages, so a few merged messages pass the word "
        "filter that failed as single tweets, and duplicates are judged on the merged text.",
        "",
        f"- Brand replies merged from 2+ tweets: {int((ex_all['n_reply_parts'] > 1).sum()):,} of "
        f"{len(ex_all):,} exchanges ({int((usable['n_reply_parts'] > 1).sum()):,} usable).",
        f"- Customer messages merged from 2+ tweets: {int((usable['n_customer_parts'] > 1).sum()):,} usable.",
        f"- Follow-ups: {int(usable['is_followup'].sum()):,}, of which "
        f"{int((usable['is_followup'] & (usable['context_turns'] == 0)).sum())} have no context left "
        f"(their earlier turns were more than {MAX_CONTEXT_AGE_DAYS} days old).",
        f"- Contexts cut (more than {MAX_CONTEXT_TURNS} turns, or stale turns dropped): "
        f"{int(usable['context_truncated'].sum()):,}.",
        "",
        "## 2. Splits",
        "",
        f"`data.split_date` = {split_date.date()}. Threads starting on/after it → `holdout`; "
        "earlier threads → `train`, except exchanges written on/after it → `excluded`.",
        "",
        _table(split_table),
        "",
        f"- Threads in both train and holdout: **{threads_in_both}**",
        f"- Every train exchange was written before the split date and every holdout thread starts "
        f"on or after it: **{'yes' if time_ok else 'NO'}**",
        f"- Excluded: {len(excluded):,} exchanges ({excluded['thread_id'].nunique():,} threads) "
        "written after the split date in threads that started before it.",
        f"- Train share of train + holdout: {len(train) / (len(train) + len(holdout)):.1%}",
        "",
        "## 3. Leakage checks (holdout vs train)",
        "",
        f"- Holdout messages with a train near-duplicate (cosine ≥ {NEAR_DUP_THRESHOLD}): "
        f"**{int((sim >= NEAR_DUP_THRESHOLD).sum()):,}**. These are not `eval_eligible`.",
        f"- For reference: ≥ 0.9: {int((sim >= 0.9).sum()):,}; ≥ 0.8: {int((sim >= 0.8).sum()):,}; "
        f"median: {sim.median():.2f}.",
        "- Holdout replies whose template also occurs in train (a retriever could copy them; "
        "reply-quality results on these must be read with care):",
        "",
        _table(tmpl),
        "",
        "## 4. Weak outcomes (train only)",
        "",
        _table(outcome),
        "",
        _table(rules),
        "",
        "## 5. Escalation signals",
        "",
        "Customer-side cues (all splits; derived from the model's input):",
        "",
        _table(_counts(records["customer_escalation_signals"])),
        "",
        "Brand-side evidence (train only; describes what the historical reply did):",
        "",
        _table(_counts(train["brand_escalation_evidence"])),
        "",
        "## 6. Cleaning decisions",
        "",
        *[f"{i}. {d}" for i, d in enumerate(CLEANING_DECISIONS, 1)],
        "",
        "## 7. Data dictionary (`data/processed/records.parquet`)",
        "",
        _table(dictionary),
        "",
    ]
    path.write_text("\n".join(parts), encoding="utf-8")


SAMPLE_BUCKETS = [
    ("Merged split brand reply (2+ tweets)", lambda r: r["n_reply_parts"] >= 2, 8),
    ("Merged customer message (2+ tweets)", lambda r: r["n_customer_parts"] >= 2, 6),
    ("Follow-up with truncated context", lambda r: r["is_followup"] & r["context_truncated"], 3),
    ("Follow-up with full context", lambda r: r["is_followup"] & ~r["context_truncated"], 5),
    ("First contact, substantive reply", lambda r: ~r["is_followup"] & (r["reply_type"] == "substantive"), 5),
    ("First contact, DM deflection", lambda r: ~r["is_followup"] & (r["reply_type"] == "dm_deflection"), 5),
    ("Holdout, eval-eligible", lambda r: r["eval_eligible"], 4),
]


def _one_line(text: str) -> str:
    return str(text).replace("\n", " ⏎ ")


def write_samples(path: Path, records: pd.DataFrame, df: pd.DataFrame, seed: int) -> None:
    raw = df.set_index("tweet_id")[["created_at", "text"]]
    rng = np.random.default_rng(seed)
    chosen: set[str] = set()
    parts = [
        "# Reconstructed exchanges: samples for hand inspection",
        "",
        f"_Generated by `python -m src.dataprep.build` (seed {seed}). Each sample shows the raw "
        "tweets that were merged and the resulting clean record. The inspection block is "
        "hand-written and kept on re-runs._",
        "",
        _manual(path, "## Hand inspection\n\n_To be filled in after reading the samples below._"),
        "",
    ]
    n = 0
    for title, mask, k in SAMPLE_BUCKETS:
        pool = records[mask(records) & ~records["record_id"].isin(chosen)]
        picks = pool.iloc[np.sort(rng.choice(len(pool), size=min(k, len(pool)), replace=False))]
        parts += [f"## {title}", ""]
        for r in picks.to_dict("records"):
            n += 1
            chosen.add(r["record_id"])
            parts += [f"### S{n:02d} · record {r['record_id']} · thread {r['thread_id']} · {r['split']} · "
                      f"{'follow-up' if r['is_followup'] else 'first contact'} · reply_type={r['reply_type']}", ""]
            if r["context_turns"]:
                note = " (truncated: opener + last turns)" if r["context_truncated"] else ""
                parts.append(f"**Context**{note}:")
                parts += [f"- _{t['role']}_ `{t['created_at']}`: {_one_line(t['text'])}" for t in r["context"]]
            parts.append(f"**Customer message**, {r['n_customer_parts']} tweet(s):")
            for tid in r["customer_tweet_ids"]:
                t = raw.loc[int(tid)]
                parts.append(f"- raw `{t['created_at']:%m-%d %H:%M}`: {_one_line(t['text'])}")
            parts.append(f"- **clean:** {_one_line(r['customer_text_clean'])}")
            parts.append(f"**Brand reply**, {r['n_reply_parts']} tweet(s), {r['reply_delay_min']} min later:")
            for tid in r["reply_tweet_ids"]:
                t = raw.loc[int(tid)]
                parts.append(f"- raw `{t['created_at']:%m-%d %H:%M}`: {_one_line(t['text'])}")
            parts.append(f"- **clean:** {_one_line(r['brand_reply_clean'])}")
            facts = [f"canned={r['reply_is_canned']}", f"retrieval_eligible={r['retrieval_eligible']}",
                     f"customer_signals={list(r['customer_escalation_signals'])}"]
            if r["split"] == "train":
                facts += [f"weak_outcome={r['weak_outcome']} ({r['outcome_confidence']})",
                          f"brand_evidence={list(r['brand_escalation_evidence'])}"]
            else:
                facts += [f"eval_eligible={r['eval_eligible']}", f"max_train_similarity={r['max_train_similarity']}",
                          f"reply_template_in_train={r['reply_template_in_train']}"]
            parts.append("- " + " · ".join(facts))
            if r["split"] == "train" and isinstance(r["next_customer_text"], str):
                parts.append(f"- next customer tweet: {_one_line(r['next_customer_text'])}")
            parts.append("")
    path.write_text("\n".join(parts), encoding="utf-8")


# --------------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--suggest-split-date", action="store_true",
                        help="print the day that puts --train-fraction of exchanges in train, then exit")
    parser.add_argument("--train-fraction", type=float, default=0.7)
    args = parser.parse_args()
    cfg = load_config()
    brand, seed, split_cfg = cfg["brand"], cfg["seed"], cfg["data"].get("split_date")

    print(f"loading raw CSV, building {brand} exchanges ...")
    df = add_language(add_threads(load_raw(resolve(cfg["data"]["raw_csv"]))))
    ex_all = build_exchanges(df, brand)
    ex, waterfall = apply_filters(ex_all)

    if args.suggest_split_date or not split_cfg:
        day = suggest_split_date(ex, args.train_fraction)
        share = (ex["thread_started_at"] < day).mean()
        print(f"suggested data.split_date: {day.date()} ({share:.1%} of usable exchanges in train)")
        if not split_cfg:
            sys.exit("data.split_date is not set in config.yaml; set it and re-run")
        return

    split_date = pd.Timestamp(split_cfg, tz="UTC")
    records = assemble(ex, split_date)
    out = resolve(cfg["data"]["records"])
    out.parent.mkdir(parents=True, exist_ok=True)
    records.to_parquet(out, index=False)
    results = resolve("results")
    write_report(results / "phase2_data_report.md", records, ex_all, waterfall, split_date, cfg)
    write_samples(results / "reconstruction_samples.md", records, df, seed)
    print(f"wrote {out} ({len(records):,} records) and results/phase2_data_report.md, "
          "results/reconstruction_samples.md")


if __name__ == "__main__":
    main()
