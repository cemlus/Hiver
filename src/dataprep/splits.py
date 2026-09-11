"""Thread-level, time-based splits and leakage checks.

A thread that starts on or after data.split_date goes wholly to "holdout". A thread that
started before it goes to "train", except for exchanges written on or after the split date
(a thread revived later): those are "excluded", so every train exchange strictly precedes every
holdout thread and no thread is in both train and holdout. Phase 5 samples the dev and golden
threads from the holdout pool; the rest of the holdout is never used.

Leakage checks between train and holdout:
- near-duplicate customer messages (TF-IDF cosine ≥ NEAR_DUP_THRESHOLD): such holdout exchanges
  are not eval_eligible, so copy-pasted tweets can't be in train and in the golden set;
- reply templates: a holdout reply whose template also occurs in train is flagged
  (reply_template_in_train), because a retriever could copy it verbatim.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

NEAR_DUP_THRESHOLD = 0.95


def suggest_split_date(ex: pd.DataFrame, train_fraction: float) -> pd.Timestamp:
    """The day boundary that puts about `train_fraction` of the exchanges in train."""
    return ex["thread_started_at"].quantile(train_fraction).floor("D")


def assign_splits(thread_started_at: pd.Series, created_at: pd.Series, split_date: pd.Timestamp) -> np.ndarray:
    return np.select([thread_started_at >= split_date, created_at < split_date],
                     ["holdout", "train"], default="excluded")


def char_vectorizer() -> TfidfVectorizer:
    """The near-duplicate representation: character 3-5-gram TF-IDF, so "won't"/"wont" or extra
    "!!!" barely matter. Rows come out L2-normalised, so a dot product is a cosine. max_df drops
    n-grams in > 20% of texts ("the ", "xbox"): they say nothing about duplication and would make
    the similarity matrix dense and slow. Fit it on a large corpus, not on a handful of texts."""
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), max_df=0.2, sublinear_tf=True)


def max_similarity(train_texts: pd.Series, other_texts: pd.Series, chunk: int = 500) -> np.ndarray:
    """For each text in `other_texts`, its highest cosine similarity to any text in
    `train_texts` (see char_vectorizer)."""
    if len(other_texts) == 0 or len(train_texts) == 0:
        return np.zeros(len(other_texts))
    vec = char_vectorizer()
    vec.fit(pd.concat([train_texts, other_texts]))
    train_t = vec.transform(train_texts).T.tocsr()
    other = vec.transform(other_texts)
    best = np.zeros(other.shape[0])
    for i in range(0, other.shape[0], chunk):
        best[i:i + chunk] = (other[i:i + chunk] @ train_t).max(axis=1).toarray().ravel()
    return best


def leakage(records: pd.DataFrame) -> pd.DataFrame:
    """max_train_similarity, eval_eligible and reply_template_in_train for each record."""
    train = (records["split"] == "train").to_numpy()
    holdout = (records["split"] == "holdout").to_numpy()
    sim = np.full(len(records), np.nan)
    sim[holdout] = max_similarity(records.loc[train, "customer_text_clean"],
                                  records.loc[holdout, "customer_text_clean"])
    train_templates = set(records.loc[train, "reply_template"]) - {""}
    return pd.DataFrame({
        "max_train_similarity": np.round(sim, 3),
        "eval_eligible": holdout & (np.nan_to_num(sim, nan=1.0) < NEAR_DUP_THRESHOLD),
        "reply_template_in_train": holdout & records["reply_template"].isin(train_templates).to_numpy(),
    }, index=records.index)
