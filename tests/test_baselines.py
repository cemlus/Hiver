"""The non-LLM baselines must be deterministic, well-formed, and bound by the frozen policy."""
import pytest

from src.contracts import (AgentOutput, ConversationState, GoldenExample, Intent, STATES_WITHOUT_INTENT,
                           SupportRequest, Turn)
from src.eval.baselines import BASELINES, keyword_cues
from src.eval.training_labels import training_corpus


def example(text, request_id="G001", intent=Intent.HARDWARE_DEVICES,
            state=ConversationState.NEW_ISSUE, escalate=False, context=(), is_followup=False):
    return GoldenExample(
        request=SupportRequest(request_id=request_id, brand="XboxSupport", customer_text=text,
                               context=context, is_followup=is_followup),
        label_conversation_state=state,
        label_intent=None if state in STATES_WITHOUT_INTENT else intent,
        label_escalate=escalate)


@pytest.fixture
def examples():
    return [example("my console won't turn on", "G001"),
            example("how do I initiate a digital refund?", "G002", Intent.PURCHASES_BILLING_ORDERS),
            example("thanks, it works now", "G003", state=ConversationState.ACKNOWLEDGEMENT_CLOSING),
            example("I tried that and it still doesn't work", "G004", is_followup=True,
                    state=ConversationState.ISSUE_FOLLOWUP)]


@pytest.mark.parametrize("name", sorted(BASELINES))
def test_baseline_returns_one_valid_output_per_example(name, examples):
    outputs = BASELINES[name](examples)
    assert len(outputs) == len(examples)
    assert [o.request_id for o in outputs] == [e.request.request_id for e in examples]
    assert all(isinstance(o, AgentOutput) and o.system == name for o in outputs)
    for o in outputs:                      # the contract's own rule, restated as a guarantee
        assert (o.intent is None) == (o.conversation_state in STATES_WITHOUT_INTENT)


@pytest.mark.parametrize("name", sorted(BASELINES))
def test_baselines_are_deterministic(name, examples):
    assert [o.model_dump() for o in BASELINES[name](examples)] == \
           [o.model_dump() for o in BASELINES[name](examples)]


def test_always_and_never_escalate_pin_the_extremes(examples):
    assert all(o.escalate for o in BASELINES["always_escalate"](examples))
    assert not any(o.escalate for o in BASELINES["never_escalate"](examples))


def test_mandatory_escalation_survives_every_baseline(examples):
    """Rule (b): whenever a baseline predicts purchases or support complaints, it must escalate."""
    for name, baseline in BASELINES.items():
        if name in {"always_escalate", "never_escalate"}:
            continue
        for output in baseline(examples):
            if output.intent in {Intent.PURCHASES_BILLING_ORDERS, Intent.SUPPORT_PROCESS_COMPLAINT}:
                assert output.escalate, f"{name} auto-handled a mandatory-escalation intent"


def test_keyword_cues_read_the_customer_and_the_context():
    cues = keyword_cues(example("I already contacted support and tried that, still doesn't work"))
    assert cues.repeat_contact and cues.steps_failed
    asked = example("yes", context=(Turn(role="brand", text="What error code do you see?"),))
    assert keyword_cues(asked).prior_clarification
    assert not keyword_cues(example("my console won't turn on")).steps_failed


def test_tfidf_never_trains_on_golden():
    import pandas as pd
    from src.config import resolve
    golden = set(pd.read_csv(resolve("data/golden/golden_sample_key.csv"), dtype=str)["record_id"])
    assert not set(training_corpus()["record_id"]) & golden
