"""The drafting step: one structured LLM call producing a reply grounded in retrieved evidence.

Versioned like the routing prompt: `DRAFT_PROMPT_VERSION` goes into the run manifest so a reply can
always be tied to the prompt that produced it. The model is told what it may rest a claim on — the
conversation and the retrieved examples — and is asked to name the records that support it.

Drafting runs only for cases the frozen policy decided to auto-handle. Escalated cases hand off
with a reason code and no customer-facing reply.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, Field

from src.contracts import RetrievedExample, SupportRequest
from src.ports.protocols import LLMClient

DRAFT_PROMPT_VERSION = "draft_v1"

SYSTEM_PREAMBLE = (
    "You write short public replies for Xbox Support on Twitter. You are shown how the brand has "
    "answered similar messages before; use that as evidence, not as text to copy.\n\n"
    "You do NOT decide whether a case goes to a human. That decision is already made before you are "
    "called, and you are only asked to draft when the case is being handled automatically."
)

RULES = [
    "Ground every substantive claim in the conversation and/or the retrieved examples. You may "
    "paraphrase and combine several examples; you do not have to reuse anyone's wording.",
    "Never invent a link, a price, a refund amount, a date or a policy. If the evidence does not "
    "support a detail, leave it out.",
    "Do not repeat a troubleshooting step the customer has already said they tried.",
    "Do not simply ask the customer to DM you. If a DM is genuinely needed, still give them "
    "something useful first.",
    "Keep it to one tweet: at most 280 characters, plain text, no hashtags.",
    "Name the record_id of every retrieved example you actually relied on.",
]


@lru_cache(maxsize=1)
def system_prompt() -> str:
    parts = [SYSTEM_PREAMBLE, "", "# Rules", ""]
    parts += [f"{i}. {rule}" for i, rule in enumerate(RULES, start=1)]
    return "\n".join(parts)


def evidence_block(retrieved: tuple[RetrievedExample, ...]) -> str:
    if not retrieved:
        return "(no similar past exchanges were found)"
    blocks = []
    for example in retrieved:
        blocks.append(f"- record_id: {example.record_id} (similarity {example.similarity:.2f})\n"
                      f"  customer asked: {example.customer_text}\n"
                      f"  the brand replied: {example.brand_reply}")
    return "\n".join(blocks)


def user_prompt(request: SupportRequest, retrieved: tuple[RetrievedExample, ...],
                errors: tuple[str, ...] = ()) -> str:
    turns = [f"{t.role}: {t.text}" for t in request.context]
    context = "\n".join(turns) if turns else "(no earlier turns)"
    parts = [f"# Conversation\n\n## Earlier turns (oldest first)\n{context}\n\n"
             f"## The customer message to answer\n{request.customer_text}", "",
             f"# Retrieved past exchanges (evidence)\n{evidence_block(retrieved)}", ""]
    if errors:
        # The revise pass: name what failed so the model fixes that rather than rewriting blindly.
        parts += ["# Your previous draft was rejected", "",
                  *(f"- {error}" for error in errors), "",
                  "Write a corrected reply that fixes every point above.", ""]
    parts.append("Draft the reply.")
    return "\n".join(parts)


class ReplyDraft(BaseModel):
    """What the model is asked for. It proposes a reply; the validator decides if it may be sent."""
    reply: str = Field(description="the public reply, at most 280 characters")
    supported_by: list[str] = Field(default_factory=list,
                                    description="record_id of each retrieved example actually used")
    rationale: str = Field(default="", description="one sentence on how the evidence supports it")


def draft(request: SupportRequest, retrieved: tuple[RetrievedExample, ...], llm: LLMClient, *,
          errors: tuple[str, ...] = ()) -> tuple[str, tuple[str, ...]]:
    """Returns the drafted reply and the record_ids the model says it relied on."""
    proposal: ReplyDraft = llm.complete(user_prompt(request, retrieved, errors),
                                        system=system_prompt(), schema=ReplyDraft)
    return proposal.reply.strip(), tuple(proposal.supported_by)


__all__ = ["draft", "system_prompt", "user_prompt", "ReplyDraft", "DRAFT_PROMPT_VERSION"]
