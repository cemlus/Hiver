"""The weakly supervised training corpus must never touch a golden record.

`src/eval/training_labels.py` has always carried an inline assertion to this effect, and its
docstring claimed this file enforced it. The file did not exist until now.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.config import load_config, resolve
from src.eval.training_labels import (intent_training_set, provenance_summary, state_training_set,
                                      training_corpus)

RECORDS = resolve(load_config()["data"]["records"])
pytestmark = pytest.mark.skipif(not RECORDS.exists(), reason="run `python -m src.dataprep.build` first")


@pytest.fixture(scope="module")
def corpus():
    return training_corpus()


def golden_record_ids() -> set[str]:
    key = pd.read_csv(resolve("data/golden/golden_sample_key.csv"), dtype=str)
    return set(key["record_id"])


def test_the_corpus_shares_no_record_with_the_golden_set(corpus):
    """The baseline must never be trained on an item it is later scored against."""
    assert not set(corpus["record_id"]) & golden_record_ids()


def test_the_golden_key_covers_every_locked_sheet_row():
    """The disjointness check is only as good as the id list it compares against."""
    sheet = pd.read_csv(resolve("data/golden/golden_labeling_sheet.csv"), dtype=str)
    assert golden_record_ids() == set(sheet["record_id"])
    assert len(sheet) == 200


def test_the_corpus_is_drawn_only_from_train_and_dev(corpus):
    """Holdout rows may appear only via the 40 dev items, never from the wider eval pool."""
    assert set(corpus["split"]) <= {"train", "holdout"}
    dev = set(pd.read_csv(resolve("data/golden/dev_labeling_sheet.csv"), dtype=str)["record_id"])
    holdout = set(corpus[corpus["split"] == "holdout"]["record_id"])
    assert holdout <= dev


def test_record_ids_are_unique(corpus):
    assert corpus["record_id"].is_unique


def test_the_labelled_subsets_are_subsets_of_the_corpus(corpus):
    assert set(intent_training_set()["record_id"]) <= set(corpus["record_id"])
    assert set(state_training_set()["record_id"]) <= set(corpus["record_id"])
    assert (intent_training_set()["intent"] != "").all()


def test_provenance_is_recorded_for_every_item(corpus):
    """Every label is assistant-coded or LLM-drafted; the report must be able to say so."""
    summary = provenance_summary()
    assert int(summary["items"].sum()) == len(corpus)
    assert not summary["sources"].eq("").any()
