"""Load the raw Kaggle CSV and rebuild conversation threads. Never writes to the raw file."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.dataprep.text import language


def load_raw(path: str | Path) -> pd.DataFrame:
    # The C engine, not pyarrow: some tweets contain newlines inside quoted fields, which
    # pyarrow's CSV reader rejects ("Expected 7 columns, got 4").
    df = pd.read_csv(path, dtype={"author_id": str, "text": str, "response_tweet_id": str})
    df["created_at"] = pd.to_datetime(df["created_at"], format="%a %b %d %H:%M:%S %z %Y", utc=True)
    df["text"] = df["text"].fillna("")
    df["lower"] = df["text"].str.lower()
    return df


def add_threads(df: pd.DataFrame) -> pd.DataFrame:
    """Give every tweet its parent's row position, the parent's author and its thread root.

    A thread is the tree of tweets linked by in_response_to_tweet_id (response_tweet_id can
    list several children, so threads branch). The root is the first ancestor present in the
    dataset. "Orphans" reply to a tweet that isn't in the dataset.
    """
    ids = pd.Index(df["tweet_id"])
    parent = ids.get_indexer(df["in_response_to_tweet_id"])      # -1 = no parent in the data
    root = np.where(parent >= 0, parent, np.arange(len(df)))
    for _ in range(64):                                            # pointer jumping
        nxt = root[root]
        if np.array_equal(nxt, root):
            break
        root = nxt
    authors = df["author_id"].to_numpy(dtype=object)
    df["parent_pos"] = parent
    df["parent_author"] = np.where(parent >= 0, authors[parent], None)
    df["root"] = df["tweet_id"].to_numpy()[root]
    df["orphan"] = df["in_response_to_tweet_id"].notna().to_numpy() & (parent < 0)
    return df


def add_language(df: pd.DataFrame) -> pd.DataFrame:
    """Estimated language of customer tweets ("en", "other", "undetermined"); None for brands."""
    inbound = df["inbound"].to_numpy()
    df["lang"] = None
    df.loc[inbound, "lang"] = language(df.loc[inbound, "lower"]).to_numpy()
    return df
