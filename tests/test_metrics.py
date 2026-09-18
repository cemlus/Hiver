"""Metrics must match hand-computed values on a small fixture."""
import numpy as np
import pytest

from src.contracts import (AgentOutput, ConversationState, GoldenExample, Intent, ReasonCode,
                           SupportRequest)
from src.eval.metrics import MUST_ESCALATE_LIMITATION, evaluate

C = ConversationState


def gold(rid, state, intent, escalate):
    return GoldenExample(request=SupportRequest(request_id=rid, brand="b", customer_text="t"),
                         label_conversation_state=state, label_intent=intent, label_escalate=escalate)


def pred(rid, state, intent, escalate):
    return AgentOutput(request_id=rid, system="s", conversation_state=state, intent=intent,
                       intent_confidence=0.5, escalate=escalate,
                       reason_code=ReasonCode.ACCOUNT_SPECIFIC if escalate else ReasonCode.GENERAL_INFO)


@pytest.fixture
def fixture():
    #  id  gold state/intent/esc            predicted state/intent/esc
    g = [gold("1", C.NEW_ISSUE, Intent.HARDWARE_DEVICES, False),
         gold("2", C.NEW_ISSUE, Intent.PURCHASES_BILLING_ORDERS, True),
         gold("3", C.SOCIAL_OFFTOPIC, None, False),
         gold("4", C.ISSUE_FOLLOWUP, Intent.HARDWARE_DEVICES, True)]
    p = [pred("1", C.NEW_ISSUE, Intent.HARDWARE_DEVICES, False),      # fully correct
         pred("2", C.NEW_ISSUE, Intent.PURCHASES_BILLING_ORDERS, True),  # fully correct
         pred("3", C.NEW_ISSUE, Intent.SOFTWARE_GAME_APP, False),     # wrong state and intent
         pred("4", C.ISSUE_FOLLOWUP, Intent.SOFTWARE_GAME_APP, False)]  # wrong intent, missed escalation
    return g, p


def test_headline_metrics_match_hand_computation(fixture):
    g, p = fixture
    m = evaluate(g, p, "test", n_boot=200).metrics
    assert m["state_accuracy"].value == pytest.approx(3 / 4)
    assert m["intent_accuracy"].value == pytest.approx(2 / 3)       # 3 intent-bearing gold items
    assert m["escalation_precision"].value == pytest.approx(1 / 1)  # one predicted escalation, correct
    assert m["escalation_recall"].value == pytest.approx(1 / 2)     # two gold escalations, one found
    assert m["joint_routing_correctness"].value == pytest.approx(2 / 4)


def test_must_escalate_proxy_counts_only_high_risk_intents(fixture):
    g, p = fixture
    m = evaluate(g, p, "test", n_boot=200).metrics["must_escalate_recall_cue_blind"]
    assert m.support == 1                     # only item 2 (purchases, gold escalate)
    assert m.value == pytest.approx(1.0)      # and it was caught
    assert "PROXY" in m.note and MUST_ESCALATE_LIMITATION == m.note


def test_intent_metrics_ignore_states_that_carry_no_intent(fixture):
    g, p = fixture
    result = evaluate(g, p, "test", n_boot=200)
    assert result.metrics["intent_macro_f1"].support == 3
    assert "social_offtopic" not in result.confusion_intent


def test_bootstrap_interval_brackets_the_point_estimate(fixture):
    g, p = fixture
    m = evaluate(g, p, "test", n_boot=500).metrics["state_accuracy"]
    assert m.lo <= m.value <= m.hi and not np.isnan(m.lo)


def test_missing_prediction_is_an_error(fixture):
    g, p = fixture
    with pytest.raises(ValueError, match="no prediction"):
        evaluate(g, p[:-1], "test", n_boot=10)


def test_per_intent_table_reports_support(fixture):
    g, p = fixture
    per_intent = evaluate(g, p, "test", n_boot=200).per_intent
    assert per_intent["hardware_devices"]["support"] == 2
    assert per_intent["purchases_billing_orders"]["f1"] == pytest.approx(1.0)


def test_macro_f1_reports_how_often_the_bootstrap_denominator_shrank(fixture):
    """M3: a resample can lose a rare class, so the interval is not over a fixed denominator."""
    g, p = fixture
    result = evaluate(g, p, "test", n_boot=500)
    for key in ("state_macro_f1", "intent_macro_f1"):
        note = result.metrics[key].note
        assert "classes at the point estimate" in note, key
        assert "% of bootstrap draws averaged over fewer" in note, key


def test_the_class_count_diagnostics_are_not_reported_as_metrics(fixture):
    """They exist to compute the note; they must not leak into the results table."""
    g, p = fixture
    result = evaluate(g, p, "test", n_boot=200)
    assert "intent_macro_f1_classes" not in result.metrics
    assert "state_macro_f1_classes" not in result.metrics


def test_macro_f1_skips_a_class_absent_from_both_rather_than_scoring_it_zero(fixture):
    """Scoring an unobserved class 0 would punish a system for a class nobody saw."""
    from src.eval.metrics import _macro_f1
    import numpy as np

    truth = np.array(["a", "a", "b"])
    pred = np.array(["a", "b", "b"])
    score, classes = _macro_f1(truth, pred, ("a", "b", "c"))
    assert classes == 2, "class c is absent from both and must be skipped, not scored"
    assert 0.0 < score <= 1.0
