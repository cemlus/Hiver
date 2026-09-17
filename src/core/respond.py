"""The response half of the agent: retrieve, draft, validate, revise once, else escalate.

This module CONSUMES the `AgentState` that `src/core/route.py` already produced. It never
re-classifies, never re-extracts cues, and never re-runs the escalation policy, so Phase 9's routing
results cannot move. The single exception is deliberate and defined by the codebook: when a drafted
reply fails validation after its one revise, the case is escalated with `REPLY_FAILED_CHECKS`.

That is codebook rule (i), and `src/core/escalate.py` deliberately never emits the code — the
contract requires it to be paired with `triggered_by=validation`, which only this module sets.
"""
from __future__ import annotations

from typing import Callable

from src.contracts import (AgentState, EscalationDecision, ReasonCode, RetrievedExample,
                           TriggeredBy)
from src.core.draft import draft as draft_reply
from src.core.validate import validate
from src.ports.protocols import LLMClient

Retriever = Callable[[str], tuple[RetrievedExample, ...]]


def failed_validation(state: AgentState, errors: tuple[str, ...]) -> EscalationDecision:
    """Codebook rule (i). The routed risk level is carried over, never recomputed."""
    return EscalationDecision(
        escalate=True,
        reason_code=ReasonCode.REPLY_FAILED_CHECKS,
        reason_text="the drafted reply failed validation: " + "; ".join(errors),
        risk_level=state.escalation.risk_level,
        triggered_by=TriggeredBy.VALIDATION)


def respond(state: AgentState, llm: LLMClient, *, retriever: Retriever, max_attempts: int = 2,
            max_chars: int = 280) -> AgentState:
    """Draft a reply for an auto-handled case. Escalated cases are returned untouched.

    `max_attempts=2` is one draft plus one revise. Exhausting it escalates rather than sending a
    reply that failed its checks.
    """
    if state.escalation is None:
        raise ValueError("respond() needs a routed state: escalation is None")
    if state.escalation.escalate:
        # Already going to a human. No retrieval, no generation, no customer-facing reply.
        return state.model_copy(update={"trace": state.trace + ("escalated: no reply drafted",)})

    retrieved = retriever(state.request.customer_text)
    trace = state.trace + (f"retrieved {len(retrieved)} grounding example(s)",)
    errors: tuple[str, ...] = ()
    text = ""

    for attempt in range(1, max_attempts + 1):
        text, supported = draft_reply(state.request, retrieved, llm, errors=errors)
        errors = validate(text, state.request, retrieved, max_chars=max_chars)
        trace = trace + (f"draft attempt {attempt}: "
                         + ("passed validation" if not errors
                            else f"rejected ({'; '.join(errors)})")
                         + (f"; cited {', '.join(supported)}" if supported else ""),)
        if not errors:
            return state.model_copy(update={"retrieved": retrieved, "draft": text,
                                            "validation_errors": (), "draft_attempts": attempt,
                                            "trace": trace})

    # Out of attempts: hand to a human rather than send a reply that failed its checks.
    trace = trace + (f"policy rule (i): {ReasonCode.REPLY_FAILED_CHECKS.value} after "
                     f"{max_attempts} attempt(s)",)
    return state.model_copy(update={"retrieved": retrieved, "draft": "", "validation_errors": errors,
                                    "draft_attempts": max_attempts,
                                    "escalation": failed_validation(state, errors), "trace": trace})


__all__ = ["respond", "failed_validation", "Retriever"]
