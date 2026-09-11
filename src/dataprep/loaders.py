"""The only way pipeline code should read the processed records, so the split rules live in
one place. records.parquet holds the "train" and "holdout" splits; dev and golden are written
to data/golden/ in Phase 5."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.config import load_config, resolve

SPLITS = ("train", "holdout")


def load(split: str, path: str | Path | None = None) -> pd.DataFrame:
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; records.parquet has {SPLITS}")
    df = pd.read_parquet(path or resolve(load_config()["data"]["records"]))
    return df[df["split"] == split].reset_index(drop=True)


def retrieval_corpus(path: str | Path | None = None) -> pd.DataFrame:
    """The grounding / RAG corpus: train exchanges whose historical reply is substantive."""
    corpus = load("train", path)
    corpus = corpus[corpus["retrieval_eligible"]].reset_index(drop=True)
    assert (corpus["reply_type"] == "substantive").all()
    return corpus


def eval_pool(path: str | Path | None = None) -> pd.DataFrame:
    """Holdout exchanges that Phase 5 may sample into dev / golden (no near-duplicate in train)."""
    pool = load("holdout", path)
    return pool[pool["eval_eligible"]].reset_index(drop=True)
