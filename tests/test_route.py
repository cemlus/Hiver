"""The routing agent: the LLM proposes, the system decides.

These use a scripted fake LLM, so they run offline and pin the contract between the two halves.
"""
import pytest

from src.contracts import (ConversationState, Intent, ReasonCode, SupportRequest, TriggeredBy, Turn,
                           finalize)
from src.core.classify import RoutingProposal, classify, classify_with_fallback_cues
from src.core.route import route


class FakeLLM:
    """Returns scripted proposals and records what it was asked."""

    def __init__(self, proposal: RoutingProposal):
        self.proposal = proposal
        self.model = "fake/model"
        self.calls: list[dict] = []

    def complete(self, prompt, *, system=None, schema=None):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema})
        return self.proposal


def proposal(**kwargs) -> RoutingProposal:
    base = {"conversation_state": "new_issue", "intent": "hardware_devices", "confidence": 0.9,
            "rationale": "console fault"}
    return RoutingProposal(**{**base, **kwargs})


def request(text="my console won't turn on", context=(), request_id="G001"):
    return SupportRequest(request_id=request_id, brand="XboxSupport", customer_text=text,
                          context=context)


def test_the_model_is_never_asked_for_an_escalation_decision():
    assert "escalate" not in RoutingProposal.model_fields
    llm = FakeLLM(proposal())
    route(request(), llm)
    assert "do NOT decide whether a case is escalated" in llm.calls[0]["system"]


def test_mandatory_escalation_holds_whatever_the_model_says():
    """Rule (b): purchases always escalates, even at high confidence with no cues."""
    state = route(request("I want a refund"), FakeLLM(proposal(intent="purchases_billing_orders")))
    assert state.escalation.escalate
    assert state.escalation.reason_code is ReasonCode.ACCOUNT_SPECIFIC


def test_cues_from_the_model_drive_the_policy():
    state = route(request(), FakeLLM(proposal(steps_failed=True)))
    assert state.escalation.escalate and state.escalation.reason_code is ReasonCode.STEPS_FAILED
    assert not route(request(), FakeLLM(proposal())).escalation.escalate


def test_low_confidence_escalates_through_policy_rule_h():
    state = route(request(), FakeLLM(proposal(confidence=0.2)), confidence_threshold=0.6)
    assert state.escalation.escalate
    assert state.escalation.reason_code is ReasonCode.LOW_CONFIDENCE
    assert state.escalation.triggered_by is TriggeredBy.MODEL
    assert any("below threshold" in line for line in state.trace)


def test_an_intent_on_a_state_that_carries_none_is_dropped():
    classification, _, trace = classify(
        request("thanks, all sorted"),
        FakeLLM(proposal(conversation_state="acknowledgement_closing", intent="hardware_devices")))
    assert classification.intent is None
    assert any("dropped intent" in line for line in trace)


def test_a_missing_intent_becomes_needs_more_context():
    classification, _, trace = classify(request("help"), FakeLLM(proposal(intent="")))
    assert classification.intent is Intent.NEEDS_MORE_CONTEXT
    assert any("needs_more_context" in line for line in trace)


def test_union_cues_add_what_the_model_missed():
    text = "I already tried that and it still doesn't work"
    _, model_only, _ = classify(request(text), FakeLLM(proposal()))
    _, merged, trace = classify_with_fallback_cues(request(text), FakeLLM(proposal()))
    assert not model_only.steps_failed and merged.steps_failed
    assert any("extractor added cues" in line for line in trace)


def test_union_never_removes_a_cue_the_model_reported():
    _, merged, _ = classify_with_fallback_cues(request("hello"), FakeLLM(proposal(strong_anger=True)))
    assert merged.strong_anger


def test_route_produces_a_finalizable_state():
    state = route(request(context=(Turn(role="brand", text="Did you power cycle?"),)),
                  FakeLLM(proposal(conversation_state="issue_followup")))
    output = finalize(state, system="agent", model_versions={"agent": "fake/model"})
    assert output.request_id == "G001" and output.conversation_state is ConversationState.ISSUE_FOLLOWUP
    assert output.reason_code in set(ReasonCode)
    assert state.latency_ms >= 0


@pytest.mark.parametrize("intent", [i.value for i in Intent])
def test_every_intent_round_trips_through_the_policy(intent):
    state = route(request(), FakeLLM(proposal(intent=intent)))
    assert state.escalation.reason_code in set(ReasonCode)
