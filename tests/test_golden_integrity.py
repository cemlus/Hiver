"""The golden set is a clean evaluation set, and the human labels are locked once finished.

Checks: 200 eval-pool items (120 random + 80 stratified), one per thread, no dev thread, no
near-duplicate of a dev message; the sheet matches the key; once golden.lock exists, the human
label file must match its SHA-256 (the primary human labels are never overwritten).
"""
import hashlib

import pandas as pd
import pytest

from src.config import resolve
from src.dataprep.loaders import eval_pool
from src.dataprep.splits import NEAR_DUP_THRESHOLD, max_similarity

GOLDEN = resolve("data/golden")
SHEET = GOLDEN / "golden_labeling_sheet.csv"
KEY = GOLDEN / "golden_sample_key.csv"
LOCK = GOLDEN / "golden.lock"

pytestmark = pytest.mark.skipif(not KEY.exists(), reason="golden set not sampled yet")


def read(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def texts(record_ids):
    pool = eval_pool()
    pool = pool.assign(record_id=pool["record_id"].astype(str)).set_index("record_id")
    return pool.loc[list(record_ids), "customer_text_clean"]


def test_golden_is_200_eval_items_one_per_thread():
    key = read(KEY)
    assert len(key) == 200 and key["thread_id"].is_unique and key["golden_id"].is_unique
    assert (key["slice"] == "random").sum() == 120
    assert len(texts(key["record_id"])) == 200   # every item is in the eval pool


def test_golden_shares_no_thread_or_near_duplicate_with_dev():
    key, dev = read(KEY), read(GOLDEN / "dev_sample_key.csv")
    assert not set(key["thread_id"]) & set(dev["thread_id"])
    sim = max_similarity(texts(dev["record_id"]), texts(key["record_id"]))
    assert (sim < NEAR_DUP_THRESHOLD).all()


def test_sheet_matches_the_key():
    sheet, key = read(SHEET), read(KEY)
    assert list(sheet["golden_id"]) == list(key["golden_id"])
    assert list(sheet["record_id"]) == list(key["record_id"])


def test_locked_human_labels_are_unchanged():
    if not LOCK.exists():
        pytest.skip("human labels not locked yet")
    assert hashlib.sha256(SHEET.read_bytes()).hexdigest() == LOCK.read_text().split()[0]
