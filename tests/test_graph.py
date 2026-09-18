"""The graph orchestrates and nothing more: same result as calling core functions in sequence.

No network: the LLM is a stub that dispatches on the requested schema, and the retriever is a
closure over fixed examples.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.contracts import (AgentState, Classification, ConversationState, Intent, ReasonCode,
                           RetrievedExample, SupportRequest, TriggeredBy, finalize)
from src.core.draft import ReplyDraft
from src.core.classify import RoutingProposal
from src.core.respond import respond
from src.core.route import route
from src.orchestration.graph import build_graph, run

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "orchestration" / "graph.py").read_text(encoding="utf-8")


class FakeLLM:
    """Returns a routing proposal or a reply draft depending on the schema asked for."""

    def __init__(self, intent: str, *replies: str) -> None:
        self.intent = intent
        self.replies = list(replies)
        self.model = "fake/model"
        self.calls: list[str] = []

    def complete(self, prompt, *, system=None, schema=None):
        self.calls.append(schema.__name__ if schema else "text")
        if schema is RoutingProposal:
            return RoutingProposal(conversation_state="new_issue", intent=self.intent,
                                   confidence=0.95, rationale="test")
        return ReplyDraft(reply=self.replies.pop(0), supported_by=["T7"])


def example() -> RetrievedExample:
    return RetrievedExample(record_id="T7", customer_text="stick drift",
                            brand_reply="Recalibrate it in Settings.", similarity=0.9)


def retriever(text: str) -> tuple[RetrievedExample, ...]:
    return (example(),)


def request(text: str = "my controller keeps drifting") -> SupportRequest:
    return SupportRequest(request_id="R1", brand="XboxSupport", customer_text=text)


def direct(req, llm, **kwargs):
    """The same flow, composed by hand: this is what the graph must reproduce."""
    state = route(req, llm, confidence_threshold=0.0, union_cues=True)
    state = respond(state, llm, retriever=retriever, max_attempts=2, max_chars=280)
    return finalize(state, system="agent")


def comparable(output):
    """Everything except wall-clock latency, which differs between two invocations."""
    return output.model_dump(exclude={"latency_ms"})


@pytest.mark.parametrize("intent,reply", [
    ("hardware_devices", "Recalibrating in Settings usually clears that up."),
    ("connectivity_xbox_live", "Recalibrating in Settings usually clears that up."),
])
def test_graph_matches_direct_composition_on_an_auto_handled_case(intent, reply):
    graph_out = run(request(), FakeLLM(intent, reply), retriever=retriever)
    direct_out = direct(request(), FakeLLM(intent, reply))
    assert comparable(graph_out) == comparable(direct_out)
    assert graph_out.reply == reply


def test_graph_matches_direct_composition_on_the_handoff_path():
    """Rule (b): purchases always escalates, so no drafting happens on either path."""
    graph_out = run(request("I want a refund"), FakeLLM("purchases_billing_orders"),
                    retriever=retriever)
    direct_out = direct(request("I want a refund"), FakeLLM("purchases_billing_orders"))
    assert comparable(graph_out) == comparable(direct_out)
    assert graph_out.escalate and graph_out.reply == ""


def test_graph_matches_direct_composition_when_validation_forces_a_handoff():
    """Two rejected drafts escalate with REPLY_FAILED_CHECKS, by the same path either way."""
    bad = ("Check https://invented.example now.", "Or try https://also-invented.example.")
    graph_out = run(request(), FakeLLM("hardware_devices", *bad), retriever=retriever)
    direct_out = direct(request(), FakeLLM("hardware_devices", *bad))
    assert comparable(graph_out) == comparable(direct_out)
    assert graph_out.reason_code is ReasonCode.REPLY_FAILED_CHECKS


def test_an_escalated_case_never_calls_the_drafter_through_the_graph():
    llm = FakeLLM("purchases_billing_orders")
    run(request("I want a refund"), llm, retriever=retriever)
    assert llm.calls == ["RoutingProposal"], "the graph drafted for an escalated case"


def test_the_graph_holds_no_policy_logic():
    """It may orchestrate route/respond/finalize; it must not reach into the policy itself."""
    for forbidden in ("from src.core.escalate", "from src.core.classify", "from src.core.cues",
                      "from src.core.draft", "from src.core.validate", "from src.core.retrieve"):
        assert forbidden not in SOURCE, f"graph.py imports business logic: {forbidden}"
    for banned in ("if state.escalation", "ReasonCode.", "RiskLevel.", "add_conditional_edges"):
        assert banned not in SOURCE, f"graph.py contains a decision: {banned}"


def test_the_graph_is_a_straight_line():
    compiled = build_graph(FakeLLM("hardware_devices", "ok"), retriever=retriever)
    nodes = set(compiled.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"route", "respond", "finalize"}
