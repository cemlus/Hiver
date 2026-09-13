"""The ported policy must still be the policy that was frozen.

The strongest check is a replay: the 40 dev items carry the labelled cues the escalation policy was
calibrated on, and the frozen calibration agreed with all 40 of their `escalate` labels
(results/escalation/dev_calibration.md). If this module drifts, that replay stops matching.
"""
import pandas as pd
import pytest

from src.config import resolve
from src.contracts import Intent, ReasonCode, RiskLevel, TriggeredBy
from src.core.escalate import Cues, cue_blind_risk, decide, default_risks

DEV = resolve("data/golden/dev_labeling_sheet.csv")


def dev_rows():
    dev = pd.read_csv(DEV, dtype=str, keep_default_na=False)
    return dev.to_dict("records")


def test_dev_replay_matches_the_frozen_calibration():
    mismatches = []
    for row in dev_rows():
        intent = Intent(row["intent"]) if row["intent"] else None
        cues = Cues.from_mapping({k.removeprefix("cue_"): v for k, v in row.items()
                                  if k.startswith("cue_")} | {"steps_failed": row["cue_steps_already_failed"]})
        decision = decide(intent, cues)
        if decision.escalate != (row["escalate"] == "yes"):
            mismatches.append((row["dev_id"], row["escalate"], decision.escalate, decision.reason_code))
    assert not mismatches, f"policy drifted from the frozen calibration: {mismatches}"


def test_dev_replay_reproduces_the_labelled_risk_levels():
    """Dev also carries a risk_level column, set from the same rules."""
    wrong = []
    for row in dev_rows():
        intent = Intent(row["intent"]) if row["intent"] else None
        cues = Cues.from_mapping({k.removeprefix("cue_"): v for k, v in row.items()
                                  if k.startswith("cue_")} | {"steps_failed": row["cue_steps_already_failed"]})
        expected = row["risk_level"]
        if expected and decide(intent, cues).risk_level.value != expected:
            wrong.append((row["dev_id"], expected, decide(intent, cues).risk_level.value))
    assert not wrong, wrong


def test_default_risks_come_from_the_frozen_spec():
    risks = default_risks()
    assert risks[Intent.PURCHASES_BILLING_ORDERS] is RiskLevel.HIGH
    assert risks[Intent.SUPPORT_PROCESS_COMPLAINT] is RiskLevel.HIGH
    assert risks[Intent.CONNECTIVITY_XBOX_LIVE] is RiskLevel.LOW
    assert len(risks) == 11


@pytest.mark.parametrize("intent", [Intent.PURCHASES_BILLING_ORDERS, Intent.SUPPORT_PROCESS_COMPLAINT])
def test_mandatory_escalation_cannot_be_auto_handled(intent):
    """Rule (b): these escalate whatever the cues say."""
    assert decide(intent).escalate
    assert decide(intent, Cues()).escalate


def test_steps_failed_escalates_every_intent():
    """C1 from the dev calibration: failed steps escalate even with no repeat contact."""
    for intent in Intent:
        assert decide(intent, Cues(steps_failed=True)).escalate


def test_repeat_contact_alone_does_not_escalate():
    assert not decide(Intent.CONNECTIVITY_XBOX_LIVE, Cues(repeat_contact=True)).escalate
    assert decide(Intent.CONNECTIVITY_XBOX_LIVE, Cues(repeat_contact=True)).risk_level is RiskLevel.MEDIUM


def test_anger_escalates_only_medium_and_high_risk_intents():
    assert not decide(Intent.PRODUCT_INFO_FEEDBACK, Cues(strong_anger=True)).escalate   # low risk
    assert decide(Intent.ENFORCEMENT_SAFETY, Cues(strong_anger=True)).escalate          # medium risk


def test_reason_priority_picks_the_most_serious():
    d = decide(Intent.ACCOUNT_ACCESS_PROFILE,
               Cues(account_compromised=True, steps_failed=True, strong_anger=True))
    assert d.reason_code is ReasonCode.SECURITY and d.risk_level is RiskLevel.HIGH


def test_low_confidence_is_attributed_to_the_model():
    d = decide(Intent.SOFTWARE_GAME_APP, low_confidence=True)
    assert d.escalate and d.reason_code is ReasonCode.LOW_CONFIDENCE
    assert d.triggered_by is TriggeredBy.MODEL


def test_cue_blind_risk_is_the_intent_default():
    assert cue_blind_risk(Intent.PURCHASES_BILLING_ORDERS) is RiskLevel.HIGH
    assert cue_blind_risk(Intent.HARDWARE_DEVICES) is RiskLevel.MEDIUM
    assert cue_blind_risk(None) is RiskLevel.LOW
