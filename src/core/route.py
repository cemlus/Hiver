"""The routing pipeline: conversation → state → intent → cues → deterministic policy → decision.

No LangGraph here (Phase 8 wraps this); no business logic anywhere else. The escalation decision is
always `src/core/escalate.py`'s, never the model's.
"""
from __future__ import annotations

import time

from src.contracts import AgentState, SupportRequest
from src.core.classify import classify, classify_with_fallback_cues
from src.core.escalate import decide
from src.ports.protocols import LLMClient


def route(request: SupportRequest, llm: LLMClient, *, confidence_threshold: float = 0.0,
          union_cues: bool = False) -> AgentState:
    """Classify, then let the frozen policy decide. `confidence_threshold` fires policy rule (h)."""
    started = time.time()
    classifier = classify_with_fallback_cues if union_cues else classify
    classification, cues, trace = classifier(request, llm)
    low_confidence = classification.confidence < confidence_threshold
    if low_confidence:
        trace = trace + (f"confidence {classification.confidence:.2f} below threshold "
                         f"{confidence_threshold:.2f}: policy rule (h) applies",)
    decision = decide(classification.intent, cues, low_confidence=low_confidence)
    trace = trace + (f"policy: {'ESCALATE' if decision.escalate else 'auto'} "
                     f"({decision.reason_code.value})",)
    return AgentState(request=request, classification=classification, escalation=decision,
                      trace=trace, latency_ms=(time.time() - started) * 1000)
