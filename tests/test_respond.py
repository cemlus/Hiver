"""End-to-end response behaviour: pass, revise-then-pass, and revise-then-escalate.

Phase 9's routing must be untouchable here: respond() consumes the routed AgentState and may only
change the outcome through the validation-failure path (codebook rule (i)).
"""
from __future__ import annotations

import pytest

from src.contracts import (AgentState, Classification, ConversationState, Intent, ReasonCode,
                           RetrievedExample, SupportRequest, TriggeredBy, finalize)
from src.core.draft import ReplyDraft
from src.core.escalate import Cues, decide
from src.core.respond import respond


class FakeLLM:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.model = "fake/model"
        self.calls: list[dict] = []

    def complete(self, prompt, *, system=None, schema=None):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema})
        return ReplyDraft(reply=self.replies.pop(0), supported_by=["T7"])


def example() -> RetrievedExample:
    return RetrievedExample(record_id="T7", customer_text="stick drift",
                            brand_reply="Recalibrate in Settings.", similarity=0.9)


def retriever(*found: RetrievedExample):
    return lambda text: tuple(found)


def routed(text: str = "my controller keeps drifting", intent: Intent = Intent.HARDWARE_DEVICES,
           cues: Cues | None = None) -> AgentState:
    """A state exactly as route() would leave it."""
    request = SupportRequest(request_id="R1", brand="XboxSupport", customer_text=text)
    classification = Classification(conversation_state=ConversationState.NEW_ISSUE, intent=intent,
                                    confidence=0.95, rationale="test")
    return AgentState(request=request, classification=classification,
                      escalation=decide(intent, cues or Cues()), trace=("routed",))


def test_a_clean_draft_is_kept():
    state = respond(routed(), FakeLLM("Recalibrating in Settings usually clears that up."),
                    retriever=retriever(example()))
    assert state.draft == "Recalibrating in Settings usually clears that up."
    assert state.draft_attempts == 1
    assert state.validation_errors == ()
    assert not state.escalation.escalate


def test_a_rejected_draft_is_revised_once_and_then_accepted():
    llm = FakeLLM("Check https://invented.example for help.",
                  "Recalibrating in Settings usually clears that up.")
    state = respond(routed(), llm, retriever=retriever(example()))
    assert state.draft_attempts == 2
    assert state.validation_errors == ()
    assert not state.escalation.escalate
    assert "previous draft was rejected" in llm.calls[1]["prompt"]


def test_two_failures_escalate_with_reply_failed_checks():
    llm = FakeLLM("Check https://invented.example now.", "Or try https://also-invented.example.")
    state = respond(routed(), llm, retriever=retriever(example()))
    assert state.escalation.escalate
    assert state.escalation.reason_code is ReasonCode.REPLY_FAILED_CHECKS
    assert state.escalation.triggered_by is TriggeredBy.VALIDATION
    assert state.draft == ""
    assert state.validation_errors


def test_an_escalated_case_is_never_drafted_for():
    """Rule (b): purchases always escalates, so no retrieval and no generation happen."""
    llm = FakeLLM()
    calls: list[str] = []
    state = respond(routed(intent=Intent.PURCHASES_BILLING_ORDERS), llm,
                    retriever=lambda text: calls.append(text) or ())
    assert state.draft == ""
    assert state.retrieved == ()
    assert llm.calls == [] and calls == []


def test_routing_is_never_recomputed():
    """The classification and the policy decision survive the response step byte for byte."""
    before = routed()
    after = respond(before, FakeLLM("Recalibrating in Settings clears that up."),
                    retriever=retriever(example()))
    assert after.classification == before.classification
    assert after.escalation == before.escalation


def test_the_risk_level_is_carried_over_not_recomputed():
    before = routed()
    after = respond(before, FakeLLM("https://a.example", "https://b.example"),
                    retriever=retriever(example()))
    assert after.escalation.risk_level == before.escalation.risk_level


def test_a_drafted_reply_reaches_the_agent_output():
    state = respond(routed(), FakeLLM("Recalibrating in Settings clears that up."),
                    retriever=retriever(example()))
    output = finalize(state, system="agent")
    assert output.reply == "Recalibrating in Settings clears that up."
    assert output.retrieved_ids == ("T7",)


def test_an_unrouted_state_is_an_error():
    request = SupportRequest(request_id="R1", brand="XboxSupport", customer_text="hi")
    with pytest.raises(ValueError, match="routed state"):
        respond(AgentState(request=request), FakeLLM(), retriever=retriever())
