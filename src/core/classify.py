"""The classification step: one structured LLM call proposing state, intent and policy cues.

"The LLM proposes; the system decides." This module never returns an escalation decision, and the
schema it asks for has no field for one. Malformed proposals are repaired deterministically (an
intent on a state that carries none is dropped, and vice versa) and the repair is recorded in the
trace rather than hidden.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.contracts import Classification, ConversationState, Intent, STATES_WITHOUT_INTENT
from src.core.cues import cues_for
from src.core.escalate import Cues
from src.core.prompts import system_prompt, user_prompt
from src.ports.protocols import LLMClient


class RoutingProposal(BaseModel):
    """What the model is asked for. Note the absence of any escalate field."""
    conversation_state: Literal["new_issue", "issue_followup", "acknowledgement_closing",
                                "social_offtopic"]
    intent: Literal[
        "connectivity_xbox_live", "install_download_update", "hardware_devices", "software_game_app",
        "account_access_profile", "purchases_billing_orders", "entitlements_subscriptions_codes",
        "enforcement_safety", "product_info_feedback", "support_process_complaint",
        "needs_more_context", ""] = Field(description="empty for states that carry no intent")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(description="one sentence, at most 200 characters")
    strong_anger: bool = False
    repeat_contact: bool = False
    steps_failed: bool = False
    account_specific_action: bool = False
    prior_clarification: bool = False
    repair_or_replacement: bool = False
    account_compromised: bool = False
    harm_or_legal: bool = False
    money_dispute: bool = False

    def cues(self) -> Cues:
        return Cues(**{f: getattr(self, f) for f in Cues().__dataclass_fields__})


def classify(request, llm: LLMClient) -> tuple[Classification, Cues, tuple[str, ...]]:
    """Returns the classification, the proposed cues, and a trace of any deterministic repair."""
    proposal: RoutingProposal = llm.complete(user_prompt(request), system=system_prompt(),
                                             schema=RoutingProposal)
    state = ConversationState(proposal.conversation_state)
    intent = Intent(proposal.intent) if proposal.intent else None
    trace: list[str] = [f"model proposed {state.value}/{intent.value if intent else '-'} "
                        f"at confidence {proposal.confidence:.2f}"]

    if state in STATES_WITHOUT_INTENT and intent is not None:
        trace.append(f"dropped intent {intent.value}: {state.value} carries none")
        intent = None
    elif state not in STATES_WITHOUT_INTENT and intent is None:
        # The codebook's T12: when no intent can be determined, the answer is needs_more_context.
        trace.append(f"{state.value} requires an intent; the model gave none, using needs_more_context")
        intent = Intent.NEEDS_MORE_CONTEXT

    classification = Classification(conversation_state=state, intent=intent,
                                    confidence=proposal.confidence, rationale=proposal.rationale)
    return classification, proposal.cues(), tuple(trace)


def classify_with_fallback_cues(request, llm: LLMClient) -> tuple[Classification, Cues, tuple[str, ...]]:
    """Model cues OR-ed with the deterministic extractor: a cue either side spots is reported.

    The policy is conservative by design (cues only ever raise risk), so union is the safe
    combination: it cannot silently drop a signal the regexes already catch.
    """
    classification, model_cues, trace = classify(request, llm)
    rule_cues = cues_for(request)
    merged = Cues(**{f: getattr(model_cues, f) or getattr(rule_cues, f)
                     for f in Cues().__dataclass_fields__})
    added = [f for f in Cues().__dataclass_fields__
             if getattr(rule_cues, f) and not getattr(model_cues, f)]
    if added:
        trace = trace + (f"extractor added cues the model missed: {', '.join(added)}",)
    return classification, merged, trace
