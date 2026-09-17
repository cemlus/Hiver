"""Embed the train-only grounding corpus once and cache it to disk.

Run from the repo root:   uv run python scripts/build_embeddings.py   (or `make index`)

Reads `loaders.retrieval_corpus()` (train split, substantive replies only) and writes the embedding
matrix to the path in `config.yaml` (`retrieval.embeddings`), row-aligned with the corpus.

The golden and dev sets are never embedded: the corpus is the train split by construction, and this
script asserts that before writing.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import load_config, resolve      # noqa: E402
from src.core.retrieve import TEXT_COLUMN, corpus, encode      # noqa: E402


def main() -> None:
    config = load_config()
    frame = corpus()
    if not (frame["split"] == "train").all():
        sys.exit("the grounding corpus contains non-train rows: refusing to build an index.")
    if not (frame["reply_type"] == "substantive").all():
        sys.exit("the grounding corpus contains non-substantive replies: refusing to build.")

    out = resolve(config["retrieval"]["embeddings"])
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"embedding {len(frame)} train exchanges with {config['embedding_model']} ...", flush=True)

    started = time.time()
    matrix = encode(frame[TEXT_COLUMN].astype(str).tolist())
    np.save(out, matrix)
    print(f"wrote {out.relative_to(ROOT)} {matrix.shape} in {time.time() - started:.1f}s "
          f"({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
