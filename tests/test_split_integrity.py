"""Split and leakage rules, checked on the committed data/processed/records.parquet."""
import pandas as pd
import pytest

from src.config import load_config, resolve
from src.dataprep.loaders import retrieval_corpus
from src.dataprep.splits import NEAR_DUP_THRESHOLD, max_similarity

CFG = load_config()
RECORDS = resolve(CFG["data"]["records"])
SPLIT_DATE = pd.Timestamp(CFG["data"]["split_date"], tz="UTC")
pytestmark = pytest.mark.skipif(not RECORDS.exists(), reason="run `python -m src.dataprep.build` first")


@pytest.fixture(scope="module")
def records():
    return pd.read_parquet(RECORDS)


def part(records, split):
    return records[records["split"] == split]


def test_record_ids_are_unique(records):
    assert records["record_id"].is_unique
    assert set(records["split"]) == {"train", "holdout", "excluded"}


def test_no_thread_is_in_both_train_and_holdout(records):
    holdout_threads = set(part(records, "holdout")["thread_id"])
    assert not holdout_threads & set(part(records, "train")["thread_id"])
    assert not holdout_threads & set(part(records, "excluded")["thread_id"])


def test_train_strictly_precedes_holdout(records):
    train, holdout, excluded = (part(records, s) for s in ["train", "holdout", "excluded"])
    assert train["created_at"].max() < SPLIT_DATE and train["thread_started_at"].max() < SPLIT_DATE
    assert holdout["thread_started_at"].min() >= SPLIT_DATE
    assert ((excluded["thread_started_at"] < SPLIT_DATE) & (excluded["created_at"] >= SPLIT_DATE)).all()


def test_retrieval_corpus_is_train_substantive_only(records):
    eligible = records[records["retrieval_eligible"]]
    assert (eligible["split"] == "train").all() and (eligible["reply_type"] == "substantive").all()
    assert len(retrieval_corpus(RECORDS)) == len(eligible)


def test_weak_labels_exist_only_on_train(records):
    other = records[records["split"] != "train"]
    for col in ["weak_outcome", "outcome_confidence", "weak_outcome_source", "next_customer_text",
                "brand_escalation_evidence"]:
        assert other[col].isna().all(), col
    assert part(records, "train")["weak_outcome"].notna().all()


def test_eval_pool_is_holdout_with_no_near_duplicate_in_train(records):
    pool = records[records["eval_eligible"]]
    assert (pool["split"] == "holdout").all()
    sim = max_similarity(part(records, "train")["customer_text_clean"], pool["customer_text_clean"])
    assert sim.max() < NEAR_DUP_THRESHOLD


def test_split_replies_leave_no_markers_in_clean_text(records):
    assert (records["n_reply_parts"] > 1).any()
    leftover = records["brand_reply_clean"].str.contains(r"(?:\^[A-Za-z]{1,3}|\b[1-4]/[2-4])\s*$", regex=True)
    assert leftover.mean() < 0.005


def test_count_matches_the_brand_validation_funnel(records):
    assert 18_000 <= len(records) <= 19_500      # Phase 1 funnel: 18,549 usable exchanges
