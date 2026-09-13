"""Prompts for the routing agent, rendered from the frozen codebook.

Versioned: `CLASSIFIER_PROMPT_VERSION` goes into every run manifest, so a result can always be tied
to the prompt that produced it. The prompt deliberately never asks the model whether to escalate —
it proposes the state, the intent and the policy cues, and `src/core/escalate.py` decides.
"""
from __future__ import annotations

from functools import lru_cache

import yaml

from src.config import resolve
from src.contracts import SupportRequest

CLASSIFIER_PROMPT_VERSION = "routing_v1"

SYSTEM_PREAMBLE = (
    "You are routing customer support tweets for Xbox Support, following a fixed codebook. Apply the "
    "codebook exactly as written, even where you would decide differently.\n\n"
    "You do NOT decide whether a case is escalated to a human. You report what the conversation "
    "contains: its state, its primary intent, and which policy cues are present. A separate "
    "deterministic policy uses your report to make the escalation decision, so cue accuracy matters "
    "as much as the intent."
)


@lru_cache(maxsize=1)
def spec() -> dict:
    return yaml.safe_load(resolve("data/taxonomy/taxonomy_v1.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def system_prompt() -> str:
    s = spec()
    parts = [SYSTEM_PREAMBLE, "", "# Codebook (frozen v1)", "",
             "## Conversation states — choose exactly one", ""]
    parts += [f"- {st['name']}: {st['definition']}" for st in s["conversation_states"]]
    parts += ["", f"Leave the intent empty for: {', '.join(s['states_without_intent'])}.", "",
              "## Intents — choose exactly one when the state carries an intent", ""]
    for it in s["intents"]:
        parts += [f"- {it['name']}: {it['definition']}",
                  f"    include: {'; '.join(it['include'])}",
                  f"    exclude: {'; '.join(it['exclude'])}"]
    parts += ["", "## Deterministic tie-breaks — apply in this order", ""]
    parts += [f"- {tb['id']}: {tb['rule']}" for tb in s["tie_breaks"]]
    parts += ["", "## Policy cues — report each as true or false", "",
              "These feed the escalation policy. Report what the customer states in this message or "
              "earlier in the thread; do not infer beyond the text.", ""]
    cue_names = {"strong_anger": "strong_anger", "repeat_contact": "repeat_contact",
                 "steps_failed": "steps_failed", "account_compromised": "account_compromised",
                 "harm_or_legal": "harm_or_legal", "money_dispute": "money_dispute"}
    for rule in s["risk_rules"]:
        if rule[0] in cue_names:
            parts.append(f"- {rule[0]}: {rule[1]}")
    parts += [
        "- account_specific_action: the fix needs someone to see or change THIS customer's own "
        "account, order, code or licence (a sign-in failure on their account, a specific pre-order, "
        "a named code). A general how-to or policy answer is not account-specific.",
        "- repair_or_replacement: the customer asks for a repair, replacement, warranty or "
        "servicing, or says a repaired or replaced device still fails.",
        "- prior_clarification: earlier in this thread the brand asked THIS customer for missing "
        "details. Brand announcements, answers and troubleshooting steps do not count.",
        "", "## confidence", "",
        "0.0-1.0: how sure you are of the state and intent together. Be honest; a low value is used "
        "by the system, not held against you.",
    ]
    return "\n".join(parts)


def user_prompt(request: SupportRequest) -> str:
    turns = [f"{t.role}: {t.text}" for t in request.context]
    context = "\n".join(turns) if turns else "(no earlier turns)"
    return (f"# Conversation to route\n\n## Earlier turns (oldest first)\n{context}\n\n"
            f"## The customer message to route\n{request.customer_text}\n\n"
            "Report the conversation state, the primary intent (empty for states that carry none), "
            "every policy cue, and your confidence. The brand's actual reply is not shown and must "
            "not be guessed at.")
