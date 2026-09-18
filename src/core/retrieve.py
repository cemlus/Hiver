"""Retrieval over the train-only grounding corpus.

The corpus is `loaders.retrieval_corpus()`: 2,711 train exchanges whose historical brand reply is
`substantive`. The golden and dev sets are never part of it, by construction — the corpus is drawn
from the train split only, and a test asserts the disjointness rather than trusting that.

`substantive` is a keyword heuristic with roughly 60% hand-sample precision ([P2] in DECISIONS.md),
so this module re-ranks by similarity rather than trusting the flag, and deduplicates by
`reply_template` so one canned template cannot fill the whole result set (52% of held-out DM
deflections reuse a train template).

`retrieve()` takes its corpus, embeddings and encoder as arguments, so tests can exercise it with a
deterministic stub and no model download. `default_retriever()` wires the real ones.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Callable

import numpy as np
import pandas as pd

from src.config import load_config, resolve
from src.contracts import RetrievedExample
from src.dataprep.loaders import retrieval_corpus

TEXT_COLUMN = "customer_text_clean"
REPLY_COLUMN = "brand_reply_clean"


def unit(matrix: np.ndarray) -> np.ndarray:
    """Row-normalise, leaving all-zero rows alone so cosine stays defined."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


@lru_cache(maxsize=1)
def corpus() -> pd.DataFrame:
    """The train-only grounding corpus, loaded once."""
    return retrieval_corpus()


@lru_cache(maxsize=1)
def encoder(name: str | None = None):
    """The sentence-transformers model. Imported lazily: tests never load it."""
    from sentence_transformers import SentenceTransformer      # noqa: PLC0415

    return SentenceTransformer(name or load_config()["embedding_model"])


def encode(texts: list[str], name: str | None = None) -> np.ndarray:
    return np.asarray(encoder(name).encode(texts, show_progress_bar=False), dtype=np.float32)


def embeddings_path() -> str:
    return load_config()["retrieval"]["embeddings"]


def load_embeddings(path: str | None = None) -> np.ndarray:
    file = resolve(path or embeddings_path())
    if not file.exists():
        raise FileNotFoundError(f"{file} is missing: run `uv run python scripts/build_embeddings.py`.")
    return np.load(file)


def retrieve(text: str, *, frame: pd.DataFrame, matrix: np.ndarray,
             encode_query: Callable[[list[str]], np.ndarray], k: int = 5,
             min_similarity: float = 0.5) -> tuple[RetrievedExample, ...]:
    """Top-k most similar historical exchanges, deduplicated by reply template.

    `matrix` must be row-aligned with `frame`. Similarity is cosine; anything below
    `min_similarity` is dropped rather than returned as weak evidence.
    """
    if len(frame) == 0:
        return ()
    if len(frame) != len(matrix):
        raise ValueError(f"corpus has {len(frame)} rows but the embedding matrix has {len(matrix)}")

    query = unit(np.asarray(encode_query([text]), dtype=np.float32).reshape(1, -1))[0]
    scores = unit(matrix.astype(np.float32)) @ query

    examples: list[RetrievedExample] = []
    seen: set[str] = set()
    for position in np.argsort(-scores):
        score = float(scores[position])
        if score < min_similarity or len(examples) >= k:
            break
        row = frame.iloc[int(position)]
        # One template may only contribute its single best match, so a canned reply that happens to
        # be similar to many messages cannot crowd out genuinely different evidence.
        template = str(row.get("reply_template", "") or "")
        if template and template in seen:
            continue
        seen.add(template)
        weak = row.get("weak_outcome", None)
        examples.append(RetrievedExample(
            record_id=str(row["record_id"]),
            customer_text=str(row[TEXT_COLUMN]),
            brand_reply=str(row[REPLY_COLUMN]),
            similarity=score,
            weak_outcome=str(weak) if isinstance(weak, str) and weak else None))
    return tuple(examples)


@lru_cache(maxsize=1)
def _by_record_id() -> dict[str, tuple[str, str]]:
    """record_id -> (customer message, brand reply) over the train-only grounding corpus."""
    return {str(row["record_id"]): (str(row[TEXT_COLUMN]), str(row[REPLY_COLUMN]))
            for row in corpus().to_dict("records")}


def examples_by_id(record_ids, *, similarity: float = 0.0) -> tuple[RetrievedExample, ...]:
    """Rebuild retrieved examples from their ids, WITH their text.

    Downstream consumers (the judge) only ever persist `retrieved_ids`, so the evidence has to be
    resolved back from the corpus rather than carried around. A missing id raises: silently
    dropping evidence is exactly the failure this function exists to prevent.
    """
    lookup = _by_record_id()
    ids = [str(rid) for rid in record_ids]
    missing = [rid for rid in ids if rid not in lookup]
    if missing:
        raise KeyError(f"{len(missing)} retrieved id(s) are not in the grounding corpus: "
                       f"{missing[:3]}. The corpus is train-only; ids from elsewhere cannot be "
                       "used as evidence.")
    return tuple(RetrievedExample(record_id=rid, customer_text=lookup[rid][0],
                                  brand_reply=lookup[rid][1], similarity=similarity)
                 for rid in ids)


def default_retriever(k: int | None = None, min_similarity: float | None = None
                      ) -> Callable[[str], tuple[RetrievedExample, ...]]:
    """The production retriever: real corpus, cached embeddings, real encoder."""
    config = load_config()
    frame, matrix = corpus(), load_embeddings()
    top_k = k if k is not None else config["retrieval"]["k"]
    floor = (min_similarity if min_similarity is not None
             else config["thresholds"]["retrieval_similarity"])

    def run(text: str) -> tuple[RetrievedExample, ...]:
        return retrieve(text, frame=frame, matrix=matrix, encode_query=encode, k=top_k,
                        min_similarity=floor)

    return run


__all__ = ["retrieve", "default_retriever", "examples_by_id", "corpus", "load_embeddings", "encode", "unit"]
