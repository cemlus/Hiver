"""Retrieval returns train-only evidence, respects the similarity floor, and dedupes templates.

The encoder is stubbed throughout: these tests never download a model and never touch the network.
The one test that reads the real corpus is skipped when the parquet is absent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.config import load_config, resolve
from src.core.retrieve import retrieve

RECORDS = resolve(load_config()["data"]["records"])


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def rows() -> list[dict]:
    return [
        {"record_id": "A", "customer_text_clean": "controller drift", "brand_reply_clean": "try recalibrating",
         "reply_template": "t1", "weak_outcome": "resolved"},
        {"record_id": "B", "customer_text_clean": "controller drift again", "brand_reply_clean": "same canned",
         "reply_template": "t1", "weak_outcome": None},
        {"record_id": "C", "customer_text_clean": "billing question", "brand_reply_clean": "check your order",
         "reply_template": "t2", "weak_outcome": None},
    ]


def encoder(vectors: dict[str, list[float]]):
    """A stub encoder: exact text lookup, so similarity is fully determined by the test."""
    def encode(texts: list[str]) -> np.ndarray:
        return np.asarray([vectors[t] for t in texts], dtype=np.float32)
    return encode


def test_returns_the_most_similar_example():
    matrix = np.asarray([[1, 0], [0.9, 0.1], [0, 1]], dtype=np.float32)
    found = retrieve("q", frame=frame(rows()), matrix=matrix,
                     encode_query=encoder({"q": [1.0, 0.0]}), k=5, min_similarity=0.0)
    assert found[0].record_id == "A"
    assert found[0].similarity == pytest.approx(1.0, abs=1e-6)


def test_one_template_contributes_only_its_best_match():
    """A canned reply must not fill the result set: A and B share template t1."""
    matrix = np.asarray([[1, 0], [0.99, 0.01], [0, 1]], dtype=np.float32)
    found = retrieve("q", frame=frame(rows()), matrix=matrix,
                     encode_query=encoder({"q": [1.0, 0.0]}), k=5, min_similarity=0.0)
    assert [e.record_id for e in found] == ["A", "C"]


def test_the_similarity_floor_drops_weak_evidence():
    matrix = np.asarray([[1, 0], [0.9, 0.1], [0, 1]], dtype=np.float32)
    found = retrieve("q", frame=frame(rows()), matrix=matrix,
                     encode_query=encoder({"q": [1.0, 0.0]}), k=5, min_similarity=0.95)
    assert [e.record_id for e in found] == ["A"]


def test_k_caps_the_result_set():
    matrix = np.asarray([[1, 0], [0.9, 0.1], [0.8, 0.2]], dtype=np.float32)
    corpus = frame([{**r, "reply_template": f"t{i}"} for i, r in enumerate(rows())])
    found = retrieve("q", frame=corpus, matrix=matrix, encode_query=encoder({"q": [1.0, 0.0]}),
                     k=2, min_similarity=0.0)
    assert len(found) == 2


def test_an_empty_corpus_returns_nothing():
    assert retrieve("q", frame=pd.DataFrame(), matrix=np.zeros((0, 2), dtype=np.float32),
                    encode_query=encoder({"q": [1.0, 0.0]})) == ()


def test_a_misaligned_matrix_is_an_error():
    with pytest.raises(ValueError, match="embedding matrix"):
        retrieve("q", frame=frame(rows()), matrix=np.zeros((2, 2), dtype=np.float32),
                 encode_query=encoder({"q": [1.0, 0.0]}))


@pytest.mark.skipif(not RECORDS.exists(), reason="processed records are not built")
def test_the_grounding_corpus_is_train_only_and_never_touches_dev_or_golden():
    """The evaluation sets must never be retrievable as evidence."""
    from src.core.retrieve import corpus

    from src.dataprep.loaders import eval_pool

    grounding = corpus()
    assert (grounding["split"] == "train").all()
    assert (grounding["reply_type"] == "substantive").all()
    assert set(grounding["record_id"].astype(str)) & set(eval_pool()["record_id"].astype(str)) == set()
