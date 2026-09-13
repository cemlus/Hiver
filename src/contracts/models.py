"""Typed contracts every module shares (pydantic v2).

The agent's input is a `SupportRequest`; its output is an `AgentOutput`. Everything between is
`AgentState`, which LangGraph carries from node to node. `finalize()` is a pure function turning a
finished state into the output, so the orchestration layer adds no logic of its own.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.contracts.enums import (AUTO_CODES, ESCALATION_CODES, STATES_WITHOUT_INTENT,
                                 ConversationState, Intent, ReasonCode, RiskLevel, TriggeredBy,
                                 WeakLabelSource)


class Turn(BaseModel):
    """One earlier turn of the conversation, oldest first in `SupportRequest.context`."""
    model_config = ConfigDict(frozen=True)
    role: str                      # customer | brand | other_customer
    text: str
    created_at: datetime | None = None


class SupportRequest(BaseModel):
    """What the agent is asked to handle. Frozen: nothing downstream may edit the request."""
    model_config = ConfigDict(frozen=True)
    request_id: str
    brand: str
    customer_text: str
    context: tuple[Turn, ...] = ()
    created_at: datetime | None = None
    is_followup: bool = False


class Classification(BaseModel):
    """The classifier's view: state, and an intent unless the state carries none."""
    conversation_state: ConversationState
    intent: Intent | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""

    @model_validator(mode="after")
    def _intent_matches_state(self) -> "Classification":
        needs_intent = self.conversation_state not in STATES_WITHOUT_INTENT
        if needs_intent and self.intent is None:
            raise ValueError(f"{self.conversation_state} requires an intent")
        if not needs_intent and self.intent is not None:
            raise ValueError(f"{self.conversation_state} must not carry an intent")
        return self


class RetrievedExample(BaseModel):
    model_config = ConfigDict(frozen=True)
    record_id: str
    customer_text: str
    brand_reply: str
    similarity: float
    weak_outcome: str | None = None
    weak_outcome_source: WeakLabelSource | None = None


class EscalationDecision(BaseModel):
    escalate: bool
    reason_code: ReasonCode
    reason_text: str = ""
    risk_level: RiskLevel = RiskLevel.LOW
    triggered_by: TriggeredBy = TriggeredBy.POLICY

    @model_validator(mode="after")
    def _code_matches_decision(self) -> "EscalationDecision":
        allowed = ESCALATION_CODES if self.escalate else AUTO_CODES
        if self.reason_code not in allowed:
            raise ValueError(f"reason_code {self.reason_code} is not valid when escalate={self.escalate}")
        if self.reason_code is ReasonCode.REPLY_FAILED_CHECKS and self.triggered_by is not TriggeredBy.VALIDATION:
            raise ValueError("REPLY_FAILED_CHECKS is only set by the reply validator")
        return self


class AgentState(BaseModel):
    """The LangGraph state. Nodes fill it in; nothing is required until `finalize`."""
    request: SupportRequest
    classification: Classification | None = None
    retrieved: tuple[RetrievedExample, ...] = ()
    draft: str = ""
    validation_errors: tuple[str, ...] = ()
    draft_attempts: int = 0
    escalation: EscalationDecision | None = None
    trace: tuple[str, ...] = ()
    latency_ms: float = 0.0


class AgentOutput(BaseModel):
    """What the evaluation scores. One row per request."""
    model_config = ConfigDict(frozen=True)
    request_id: str
    system: str                                   # which system produced it: agent, baseline name, ...
    conversation_state: ConversationState
    intent: Intent | None = None
    intent_confidence: float = Field(ge=0.0, le=1.0)
    reply: str = ""
    escalate: bool = False
    reason_code: ReasonCode = ReasonCode.GENERAL_INFO
    reason_text: str = ""
    retrieved_ids: tuple[str, ...] = ()
    codebook_version: str = "v1"
    model_versions: dict[str, str] = Field(default_factory=dict)
    latency_ms: float = 0.0

    @model_validator(mode="after")
    def _consistent(self) -> "AgentOutput":
        needs_intent = self.conversation_state not in STATES_WITHOUT_INTENT
        if needs_intent != (self.intent is not None):
            raise ValueError(f"{self.conversation_state} and intent={self.intent} disagree")
        allowed = ESCALATION_CODES if self.escalate else AUTO_CODES
        if self.reason_code not in allowed:
            raise ValueError(f"reason_code {self.reason_code} is not valid when escalate={self.escalate}")
        return self


class GoldenExample(BaseModel):
    """One labelled evaluation item. `label_*` come from the gold layer being scored against."""
    model_config = ConfigDict(frozen=True)
    request: SupportRequest
    label_conversation_state: ConversationState
    label_intent: Intent | None = None
    label_escalate: bool = False
    label_confidence: str = ""
    slice: str = "random"
    notes: str = ""
    labeler: str = ""

    @model_validator(mode="after")
    def _intent_matches_state(self) -> "GoldenExample":
        needs_intent = self.label_conversation_state not in STATES_WITHOUT_INTENT
        if needs_intent != (self.label_intent is not None):
            raise ValueError(f"{self.label_conversation_state} and intent={self.label_intent} disagree")
        return self


def finalize(state: AgentState, system: str, model_versions: dict[str, str] | None = None) -> AgentOutput:
    """Turn a finished state into the scored output. Pure: no I/O, no model calls."""
    if state.classification is None or state.escalation is None:
        raise ValueError("cannot finalize a state without a classification and an escalation decision")
    return AgentOutput(
        request_id=state.request.request_id,
        system=system,
        conversation_state=state.classification.conversation_state,
        intent=state.classification.intent,
        intent_confidence=state.classification.confidence,
        reply=state.draft,
        escalate=state.escalation.escalate,
        reason_code=state.escalation.reason_code,
        reason_text=state.escalation.reason_text,
        retrieved_ids=tuple(e.record_id for e in state.retrieved),
        model_versions=model_versions or {},
        latency_ms=state.latency_ms,
    )
