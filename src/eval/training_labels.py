"""The labelled corpus the weakly supervised baseline may train on. Never the golden set.

Three sources exist in the repository, none of them independently human-annotated:

| source | items | provenance |
|---|---|---|
| `data/taxonomy/discovery_sample_coding.csv` | 150 | train split, hand-coded by the assistant during taxonomy discovery |
| example ids in `taxonomy_v1.yaml` | 88 intent + 14 state | train split, hand-picked by the assistant while writing the codebook |
| `data/golden/dev_labeling_sheet.csv` | 40 | holdout, ChatGPT-drafted and approved by the project owner |

Any model trained on this is therefore **weakly supervised**, and its ceiling is the quality of
these labels. The corpus never touches a golden record: an assertion below enforces it and
`tests/test_training_labels.py` pins it.

Tie-break example ids in the spec are deliberately excluded: they illustrate a rule, not a settled
label for one message.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
import yaml

from src.config import resolve
from src.dataprep.loaders import load

#: Later sources win when the same record appears twice (human-reviewed beats assistant-coded).
SOURCE_PRIORITY = ("codebook_examples", "discovery_sample", "dev_labels")


def _spec() -> dict:
    return yaml.safe_load(resolve("data/taxonomy/taxonomy_v1.yaml").read_text(encoding="utf-8"))


def _codebook_examples() -> pd.DataFrame:
    spec, rows = _spec(), []
    for it in spec["intents"]:
        rows += [{"record_id": str(rid), "conversation_state": "", "intent": it["name"],
                  "source": "codebook_examples"} for rid in it.get("examples", [])]
    for st in spec["conversation_states"]:
        rows += [{"record_id": str(rid), "conversation_state": st["name"], "intent": "",
                  "source": "codebook_examples"} for rid in st.get("examples", [])]
    return pd.DataFrame(rows)


def _discovery_sample() -> pd.DataFrame:
    df = pd.read_csv(resolve("data/taxonomy/discovery_sample_coding.csv"), dtype=str,
                     keep_default_na=False)
    return df.assign(source="discovery_sample")[["record_id", "conversation_state", "intent", "source"]]


def _dev_labels() -> pd.DataFrame:
    df = pd.read_csv(resolve("data/golden/dev_labeling_sheet.csv"), dtype=str, keep_default_na=False)
    return df.assign(source="dev_labels")[["record_id", "conversation_state", "intent", "source"]]


@lru_cache(maxsize=1)
def training_corpus() -> pd.DataFrame:
    """One row per labelled non-golden record: text, labels (possibly blank) and provenance."""
    frames = {"codebook_examples": _codebook_examples(), "discovery_sample": _discovery_sample(),
              "dev_labels": _dev_labels()}
    labels = pd.concat([frames[s] for s in SOURCE_PRIORITY], ignore_index=True)
    labels["priority"] = labels["source"].map({s: i for i, s in enumerate(SOURCE_PRIORITY)})
    # Keep the highest-priority row per record, but let a lower-priority row fill a blank field.
    labels = labels.sort_values("priority")
    merged = []
    for record_id, group in labels.groupby("record_id", sort=False):
        best = group.iloc[-1].to_dict()
        for field in ("conversation_state", "intent"):
            if not best[field]:
                filled = group[group[field] != ""]
                if len(filled):
                    best[field] = filled.iloc[-1][field]
        best["sources"] = "+".join(sorted(set(group["source"])))
        merged.append(best)

    corpus = pd.DataFrame(merged).drop(columns=["priority", "source"])
    text = pd.concat([load("train"), load("holdout")], ignore_index=True)
    text = text.assign(record_id=text["record_id"].astype(str)).set_index("record_id")
    corpus = corpus[corpus["record_id"].isin(text.index)].copy()
    corpus["text"] = text.loc[corpus["record_id"], "customer_text_clean"].to_numpy()
    corpus["split"] = text.loc[corpus["record_id"], "split"].to_numpy()
    corpus["is_followup"] = text.loc[corpus["record_id"], "is_followup"].to_numpy()

    golden = set(pd.read_csv(resolve("data/golden/golden_sample_key.csv"), dtype=str)["record_id"])
    overlap = set(corpus["record_id"]) & golden
    assert not overlap, f"training corpus touches the golden set: {sorted(overlap)[:5]}"
    return corpus.reset_index(drop=True)


def intent_training_set() -> pd.DataFrame:
    return training_corpus().query("intent != ''").reset_index(drop=True)


def state_training_set() -> pd.DataFrame:
    return training_corpus().query("conversation_state != ''").reset_index(drop=True)


def provenance_summary() -> pd.DataFrame:
    """Per-source counts, for the report's provenance table."""
    corpus = training_corpus()
    return (corpus.groupby("sources")
            .agg(items=("record_id", "size"), with_intent=("intent", lambda s: int((s != "").sum())),
                 with_state=("conversation_state", lambda s: int((s != "").sum())))
            .reset_index())
