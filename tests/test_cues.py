"""The cue extractor must implement the frozen codebook, stay deterministic, and never regress
below the performance it was validated at on dev.

It is validated on dev (`scripts/validate_cue_extractor.py`) and never tuned on golden. These tests
pin the dev numbers so a later "improvement" cannot quietly trade recall away.
"""
import pandas as pd
import pytest

from src.config import resolve
from src.contracts import SupportRequest, Turn
from src.core.cues import CUSTOMER_PATTERNS, cues_for, extract
from src.dataprep.loaders import eval_pool

CUE_COLUMNS = {"cue_strong_anger": "strong_anger", "cue_repeat_contact": "repeat_contact",
               "cue_steps_already_failed": "steps_failed",
               "cue_account_specific_action": "account_specific_action",
               "cue_prior_clarification": "prior_clarification",
               "cue_repair_or_replacement": "repair_or_replacement",
               "cue_account_compromised": "account_compromised",
               "cue_harm_or_legal": "harm_or_legal", "cue_money_dispute": "money_dispute"}


def request(text, context=()):
    return SupportRequest(request_id="x", brand="XboxSupport", customer_text=text, context=context)


@pytest.fixture(scope="module")
def dev_scores():
    dev = pd.read_csv(resolve("data/golden/dev_labeling_sheet.csv"), dtype=str, keep_default_na=False)
    pool = eval_pool()
    pool = pool.assign(record_id=pool["record_id"].astype(str)).set_index("record_id")
    tp = fp = fn = 0
    for row in dev.to_dict("records"):
        record = pool.loc[row["record_id"]]
        cues = cues_for(request(record["customer_text_clean"],
                                tuple(Turn(role=str(t["role"]), text=str(t["text"]))
                                      for t in record["context"])))
        for column, field in CUE_COLUMNS.items():
            gold, pred = row[column].strip().lower() == "yes", getattr(cues, field)
            tp += gold and pred
            fp += pred and not gold
            fn += gold and not pred
    return {"precision": tp / (tp + fp), "recall": tp / (tp + fn)}


def test_dev_performance_does_not_regress(dev_scores):
    """Validated at precision 0.74 / recall 0.73 on 2026-09-13; small slack for refactors."""
    assert dev_scores["precision"] >= 0.70, dev_scores
    assert dev_scores["recall"] >= 0.70, dev_scores


def test_every_policy_cue_has_a_pattern():
    from src.core.escalate import Cues
    fields = set(Cues().__dataclass_fields__)
    assert set(CUSTOMER_PATTERNS) | {"prior_clarification"} == fields


def test_extraction_is_deterministic():
    text = "I already contacted support and tried that, still doesn't work"
    assert cues_for(request(text)) == cues_for(request(text))


def test_cues_read_the_customer_s_earlier_turns_but_not_the_brand_s():
    """Cues are statements the customer makes; a brand turn must not create one."""
    from_context = request("ok", context=(Turn(role="customer", text="I already tried that, no luck"),))
    assert cues_for(from_context).steps_failed
    brand_only = request("ok", context=(Turn(role="brand", text="Have you tried a power cycle?"),))
    assert not cues_for(brand_only).steps_failed


def test_prior_clarification_needs_the_brand_to_have_asked():
    asked = request("yes", context=(Turn(role="brand", text="What error code do you see?"),))
    assert cues_for(asked).prior_clarification
    told = request("ok", context=(Turn(role="brand", text="Let's power down the console for 5 mins."),))
    assert not cues_for(told).prior_clarification


def test_a_refund_how_to_is_not_a_money_dispute():
    """The codebook defines money_dispute as charged twice, refund refused or money taken."""
    assert not cues_for(request("how do I initiate a digital refund?")).money_dispute
    assert cues_for(request("they denied my refund and charged me twice")).money_dispute


def test_evidence_records_what_matched():
    cues, evidence = extract(request("my account was hacked, someone else is using it"))
    assert cues.account_compromised
    assert any(e.cue == "account_compromised" and e.source == "message" for e in evidence)
