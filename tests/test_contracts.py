"""The contracts must mirror the frozen codebook and reject inconsistent outputs.

If someone edits taxonomy_v1.yaml without updating the enums (or the reverse), these fail.
"""
import pytest
import yaml
from pydantic import ValidationError

from src.config import resolve
from src.contracts import (AUTO_CODES, ESCALATION_CODES, AgentOutput, AgentState, Classification,
                           ConversationState, EscalationDecision, GoldenExample, Intent, ReasonCode,
                           RetrievedExample, RiskLevel, SupportRequest, TriggeredBy, Turn, finalize)


def spec():
    return yaml.safe_load(resolve("data/taxonomy/taxonomy_v1.yaml").read_text(encoding="utf-8"))


def request(**kwargs):
    return SupportRequest(request_id="G001", brand="XboxSupport", customer_text="my console won't start",
                          **kwargs)


# --- the enums mirror the frozen codebook ------------------------------------------------------
def test_intents_match_the_codebook():
    assert [i.value for i in Intent] == [it["name"] for it in spec()["intents"]]


def test_states_match_the_codebook():
    s = spec()
    assert [c.value for c in ConversationState] == [st["name"] for st in s["conversation_states"]]
    assert {c.value for c in ESCALATION_CODES | AUTO_CODES}  # non-empty


def test_reason_codes_match_the_codebook():
    codes = next(values for field, _, values in spec()["label_fields"] if field == "reason_code")
    for code in ReasonCode:
        assert code.value in codes, code


def test_states_without_intent_match_the_codebook():
    from src.contracts import STATES_WITHOUT_INTENT
    assert {s.value for s in STATES_WITHOUT_INTENT} == set(spec()["states_without_intent"])


# --- validators --------------------------------------------------------------------------------
def test_closing_state_must_not_carry_an_intent():
    Classification(conversation_state=ConversationState.ACKNOWLEDGEMENT_CLOSING, confidence=0.9)
    with pytest.raises(ValidationError):
        Classification(conversation_state=ConversationState.ACKNOWLEDGEMENT_CLOSING,
                       intent=Intent.HARDWARE_DEVICES, confidence=0.9)


def test_issue_state_requires_an_intent():
    with pytest.raises(ValidationError):
        Classification(conversation_state=ConversationState.NEW_ISSUE, confidence=0.5)


def test_escalation_code_must_match_the_decision():
    EscalationDecision(escalate=True, reason_code=ReasonCode.STEPS_FAILED)
    EscalationDecision(escalate=False, reason_code=ReasonCode.GENERAL_INFO)
    with pytest.raises(ValidationError):     # auto code while escalating
        EscalationDecision(escalate=True, reason_code=ReasonCode.GENERAL_INFO)
    with pytest.raises(ValidationError):     # escalation code while auto-handling
        EscalationDecision(escalate=False, reason_code=ReasonCode.SECURITY)


def test_reply_failed_checks_is_system_only():
    EscalationDecision(escalate=True, reason_code=ReasonCode.REPLY_FAILED_CHECKS,
                       triggered_by=TriggeredBy.VALIDATION)
    with pytest.raises(ValidationError):
        EscalationDecision(escalate=True, reason_code=ReasonCode.REPLY_FAILED_CHECKS,
                           triggered_by=TriggeredBy.RULE)


def test_agent_output_rejects_state_intent_mismatch():
    with pytest.raises(ValidationError):
        AgentOutput(request_id="G001", system="agent", intent_confidence=0.5,
                    conversation_state=ConversationState.SOCIAL_OFFTOPIC, intent=Intent.HARDWARE_DEVICES)


def test_golden_example_rejects_state_intent_mismatch():
    GoldenExample(request=request(), label_conversation_state=ConversationState.NEW_ISSUE,
                  label_intent=Intent.HARDWARE_DEVICES)
    with pytest.raises(ValidationError):
        GoldenExample(request=request(), label_conversation_state=ConversationState.NEW_ISSUE)


def test_requests_are_frozen():
    with pytest.raises(ValidationError):
        request().customer_text = "changed"


# --- round trip and finalize -------------------------------------------------------------------
def test_json_round_trip():
    out = AgentOutput(request_id="G001", system="agent", conversation_state=ConversationState.NEW_ISSUE,
                      intent=Intent.HARDWARE_DEVICES, intent_confidence=0.8, reply="Let's try...",
                      escalate=True, reason_code=ReasonCode.ACCOUNT_SPECIFIC, retrieved_ids=("1", "2"))
    assert AgentOutput.model_validate_json(out.model_dump_json()) == out


def test_finalize_builds_a_valid_output():
    state = AgentState(
        request=request(context=(Turn(role="brand", text="Have you power cycled?"),), is_followup=True),
        classification=Classification(conversation_state=ConversationState.ISSUE_FOLLOWUP,
                                      intent=Intent.HARDWARE_DEVICES, confidence=0.7),
        retrieved=(RetrievedExample(record_id="42", customer_text="same", brand_reply="try this",
                                    similarity=0.8),),
        draft="Sorry about that, let's get it sorted.",
        escalation=EscalationDecision(escalate=True, reason_code=ReasonCode.STEPS_FAILED,
                                      risk_level=RiskLevel.MEDIUM, triggered_by=TriggeredBy.RULE),
        latency_ms=1234.5)
    out = finalize(state, system="agent", model_versions={"agent": "gemini/gemini-2.5-flash"})
    assert out.request_id == "G001" and out.escalate and out.retrieved_ids == ("42",)
    assert out.intent is Intent.HARDWARE_DEVICES and out.latency_ms == 1234.5


def test_finalize_refuses_an_unfinished_state():
    with pytest.raises(ValueError):
        finalize(AgentState(request=request()), system="agent")
