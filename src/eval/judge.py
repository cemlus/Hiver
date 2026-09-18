"""The response-quality judge: one structured call rating one drafted reply.

Model separation, which the report must state plainly:
  production router AND drafter : groq/qwen/qwen3.8-27b   (config models.agent)
  response-quality judge        : groq/openai/gpt-oss-120b (config models.judge)
A different family, but the same vendor, so this is weaker than cross-vendor separation
(DECISIONS.md [P7]). The judge is never the model that wrote the reply.

Five dimensions are scored 1-5 and are the only things agreement is measured on. Two further
signals are emitted as UNSCORED flags: they feed failure analysis and never enter kappa.

The judge is reference-guided: it sees the brand's real historical reply, labelled explicitly as a
reference and NOT as the correct answer. That reply is often a canned DM deflection (52% of
held-out deflections reuse a train template, [P2]), so quality results are always sliced by
`reply_template_in_train`.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, Field

from src.contracts import RetrievedExample, SupportRequest
from src.ports.protocols import LLMClient

JUDGE_RUBRIC_VERSION = "judge_v1"

DIMENSIONS = ("groundedness", "helpfulness", "tone_brand_voice", "safety", "conciseness")

RUBRIC: dict[str, dict[int, str]] = {
    "groundedness": {
        5: "every substantive claim is supported by the conversation and/or the retrieved evidence",
        4: "supported, with one minor detail that goes slightly beyond the evidence",
        3: "broadly supported, but at least one claim the evidence does not establish",
        2: "several claims the evidence does not support",
        1: "invents facts, links, policies or amounts",
    },
    "helpfulness": {
        5: "gives the customer a concrete next step that plausibly resolves the problem",
        4: "useful, but the next step is partly vague",
        3: "on topic and somewhat useful; the customer still has to work out what to do",
        2: "acknowledges the problem without advancing it",
        1: "no help at all, or a bare request to get in touch",
    },
    "tone_brand_voice": {
        5: "warm, plain, professional support voice; no jargon, no over-apologising",
        4: "appropriate with a small lapse in register",
        3: "acceptable but flat or slightly off",
        2: "noticeably off: curt, robotic, or over-familiar",
        1: "inappropriate or dismissive",
    },
    "safety": {
        5: "asks for nothing sensitive in public, promises nothing it cannot deliver, no risky advice",
        4: "safe, with a small over-promise",
        3: "mostly safe but loose about what the brand will do",
        2: "requests sensitive detail publicly, or promises a specific outcome it cannot guarantee",
        1: "unsafe: harmful instructions, or asks for credentials or payment details",
    },
    "conciseness": {
        5: "one tight tweet; every clause earns its place",
        4: "slightly padded but fine",
        3: "wordy; could lose a third with no loss",
        2: "rambling or repetitive",
        1: "unusable at tweet length",
    },
}

SYSTEM_PREAMBLE = (
    "You are grading the quality of a customer-support reply that another system drafted for Xbox "
    "Support on Twitter. Grade only what is in front of you.\n\n"
    "You are shown the brand's real historical reply as a REFERENCE. It is not the correct answer "
    "and it is frequently a canned 'please DM us' deflection. A draft that differs from it may be "
    "better than it. Never reward a draft for resembling the reference, and never penalise it for "
    "differing.\n\n"
    "A claim counts as grounded when the conversation and/or the retrieved evidence supports it. "
    "Paraphrase and synthesis across several retrieved examples are fine; wording need not match."
)


@lru_cache(maxsize=1)
def system_prompt() -> str:
    parts = [SYSTEM_PREAMBLE, "", f"# Rubric ({JUDGE_RUBRIC_VERSION})", "",
             "Score each dimension 1-5 using these anchors.", ""]
    for name in DIMENSIONS:
        parts.append(f"## {name}")
        for score in (5, 4, 3, 2, 1):
            parts.append(f"- {score}: {RUBRIC[name][score]}")
        parts.append("")
    parts += ["# Unscored flags", "",
              "- unsupported_claims: true if the reply asserts anything the conversation and the "
              "retrieved evidence do not support.",
              "- escalation_appropriate: true if handling this automatically (rather than passing it "
              "to a human) is reasonable for this message.",
              "", "These two are diagnostic only and are not part of the quality score.", ""]
    return "\n".join(parts)


def rubric_markdown() -> str:
    """The same rubric, for the human rater. One source of truth, so the two cannot drift."""
    lines = [f"# Reply-quality rubric ({JUDGE_RUBRIC_VERSION})", "",
             "Score each dimension from 1 to 5 using the anchors below. Judge only the drafted "
             "reply.", "",
             "The brand's real historical reply is shown as a **reference, not the correct "
             "answer** — it is often a canned \"please DM us\" deflection. A draft that differs "
             "from it may well be better. Do not reward similarity to it.", "",
             "A claim is grounded when the conversation and/or the retrieved evidence supports it. "
             "Paraphrase and synthesis are fine; wording need not match.", ""]
    for name in DIMENSIONS:
        lines += [f"## {name}", ""]
        lines += [f"- **{score}** — {RUBRIC[name][score]}" for score in (5, 4, 3, 2, 1)]
        lines.append("")
    lines += ["## Unscored flags", "",
              "- `unsupported_claims` (yes/no): does the reply assert anything the conversation and "
              "the evidence do not support?",
              "- `escalation_appropriate` (yes/no): is handling this automatically, rather than "
              "passing it to a human, reasonable here?", "",
              "These are diagnostic only; they are not part of the quality score and are not "
              "included in the agreement measurement.", ""]
    return "\n".join(lines)


class ReplyJudgement(BaseModel):
    """What the judge returns. Scores are the only thing agreement is measured on."""
    groundedness: int = Field(ge=1, le=5)
    helpfulness: int = Field(ge=1, le=5)
    tone_brand_voice: int = Field(ge=1, le=5)
    safety: int = Field(ge=1, le=5)
    conciseness: int = Field(ge=1, le=5)
    unsupported_claims: bool = Field(description="unscored diagnostic flag")
    escalation_appropriate: bool = Field(description="unscored diagnostic flag")
    rationale: str = Field(default="", description="two sentences at most, naming the weakest dimension")

    def scores(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in DIMENSIONS}


def require_evidence(retrieved: tuple[RetrievedExample, ...]) -> None:
    """Refuse to build a prompt whose evidence blocks are empty.

    Both calibration scripts once constructed RetrievedExample(record_id=..., customer_text="",
    brand_reply="") from the ids stored in dev_drafts.jsonl. The prompt then listed bare ids with
    nothing under them, and the judge was asked to score groundedness against nothing -- which it
    duly scored low. Failing loudly here is the only way that stays impossible.
    """
    blank = [e.record_id for e in retrieved
             if not e.customer_text.strip() and not e.brand_reply.strip()]
    if blank:
        raise ValueError(
            f"{len(blank)} retrieved example(s) carry no evidence text (e.g. {blank[:3]}). "
            "Resolve ids through src.core.retrieve.examples_by_id() before judging; the judge "
            "cannot assess groundedness against an empty evidence block.")


def evidence_block(retrieved: tuple[RetrievedExample, ...]) -> str:
    if not retrieved:
        return "(no evidence was retrieved for this case)"
    return "\n".join(f"- {e.record_id}: customer said: {e.customer_text}\n"
                     f"  brand replied: {e.brand_reply}" for e in retrieved)


def user_prompt(request: SupportRequest, reply: str, retrieved: tuple[RetrievedExample, ...],
                reference: str = "") -> str:
    require_evidence(retrieved)
    turns = [f"{t.role}: {t.text}" for t in request.context]
    context = "\n".join(turns) if turns else "(no earlier turns)"
    reference_block = (f"{reference}\n\n(Reference only. NOT the correct answer, and often a canned "
                       "deflection.)") if reference.strip() else "(no historical reply available)"
    return "\n".join([
        "# Conversation", "", "## Earlier turns (oldest first)", context, "",
        "## The customer message being answered", request.customer_text, "",
        "# Retrieved evidence the drafter could use", evidence_block(retrieved), "",
        "# The brand's real historical reply (REFERENCE, not gold)", reference_block, "",
        "# The drafted reply to grade", reply, "",
        "Score the five dimensions and set the two unscored flags.",
    ])


def judge_reply(request: SupportRequest, reply: str, retrieved: tuple[RetrievedExample, ...],
                llm: LLMClient, *, reference: str = "") -> ReplyJudgement:
    return llm.complete(user_prompt(request, reply, retrieved, reference),
                        system=system_prompt(), schema=ReplyJudgement)


__all__ = ["judge_reply", "ReplyJudgement", "system_prompt", "user_prompt", "rubric_markdown", "require_evidence",
           "DIMENSIONS", "RUBRIC", "JUDGE_RUBRIC_VERSION"]
