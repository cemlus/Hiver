"""Checks a drafted reply before it may be sent.

Grounding rule (set by the project owner): a substantive claim is grounded when it is supported by
the customer conversation/context **and/or** the retrieved evidence. Paraphrase and synthesis across
several retrieved examples are fine, and a claim does NOT have to appear verbatim in any one
retrieved reply. What is rejected is the genuinely unsupported: invented links, a redaction placeholder copied out of the evidence, money amounts
nobody mentioned, troubleshooting offered with no evidence behind it, a canned DM deflection, and
steps the customer has already reported trying.

Every check is deterministic and returns a plain reason string, so a failure can be explained to the
customer-facing operator and replayed in a test without an LLM.
"""
from __future__ import annotations

import re

from src.contracts import RetrievedExample, SupportRequest

PLACEHOLDER_RE = re.compile(r"<\s*url\s*>", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"')]+|\b(?:www\.)[^\s<>\"')]+", re.I)
MONEY_RE = re.compile(r"(?:[$£€]\s?\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\s?(?:usd|gbp|eur|dollars|pounds)\b)", re.I)
DM_RE = re.compile(r"\b(?:dm|direct message|private message|message us|pm us)\b", re.I)
GUIDANCE_RE = re.compile(
    r"\b(?:try|restart|reboot|reinstall|re-?install|unplug|power\s?cycle|hard\s?reset|factory\s?reset|"
    r"update|check|clear|delete|remove|sign\s?(?:in|out)|log\s?(?:in|out)|settings|press|hold|"
    r"disconnect|reconnect|reset)\b", re.I)
TRIED_RE = re.compile(
    r"\b(?:tried|already\s+(?:tried|did|done)|i(?:'ve|\s+have)\s+(?:tried|done)|didn'?t\s+work|"
    r"doesn'?t\s+work|no\s+luck|still\s+(?:not|doesn'?t|won'?t))\b", re.I)
STEP_WORDS = ("restart", "reboot", "reinstall", "re-install", "unplug", "power cycle", "powercycle",
              "hard reset", "factory reset", "update", "sign out", "sign in", "log out", "log in",
              "clear cache", "reset")


def _evidence(request: SupportRequest, retrieved: tuple[RetrievedExample, ...]) -> str:
    """Everything the draft is allowed to rest on: the conversation plus the retrieved examples."""
    parts = [request.customer_text, *(turn.text for turn in request.context)]
    for example in retrieved:
        parts += [example.customer_text, example.brand_reply]
    return "\n".join(parts).lower()


def _normalise(url: str) -> str:
    return url.rstrip(".,);:!?").lower().removeprefix("https://").removeprefix("http://").removeprefix("www.")


def tried_steps(request: SupportRequest) -> set[str]:
    """Steps the customer says they already attempted, so the reply does not repeat them."""
    said = " ".join([request.customer_text, *(t.text for t in request.context
                                              if t.role == "customer")]).lower()
    if not TRIED_RE.search(said):
        return set()
    return {word for word in STEP_WORDS if word in said}


def validate(draft: str, request: SupportRequest, retrieved: tuple[RetrievedExample, ...] = (), *,
             max_chars: int = 280) -> tuple[str, ...]:
    """Returns one string per failed check; an empty tuple means the draft may be sent."""
    errors: list[str] = []
    text = (draft or "").strip()
    if not text:
        return ("the draft is empty",)
    if len(text) > max_chars:
        errors.append(f"the reply is {len(text)} characters, over the {max_chars}-character limit")

    evidence = _evidence(request, retrieved)

    known = {_normalise(u) for u in URL_RE.findall(evidence)}
    for url in URL_RE.findall(text):
        if _normalise(url) not in known:
            errors.append(f"unsupported link: {url} appears in neither the conversation nor the "
                          "retrieved evidence")

    if PLACEHOLDER_RE.search(text):
        errors.append("broken link: the draft contains the literal <URL> placeholder, which is the "
                      "corpus's redaction token, not an address a customer can open")

    for amount in MONEY_RE.findall(text):
        if amount.lower().replace(" ", "") not in evidence.replace(" ", ""):
            errors.append(f"unsupported amount: {amount} is not in the conversation or the evidence")

    # A DM ask is legitimate alongside real help; a bare deflection is the canned template the
    # held-out data is full of, and it never counts as a grounded answer ([P2]).
    if DM_RE.search(text) and not GUIDANCE_RE.search(text):
        errors.append("DM deflection: the reply asks the customer to get in touch without offering "
                      "any guidance")

    repeated = sorted(step for step in tried_steps(request) if step in text.lower())
    if repeated:
        errors.append("repeats steps the customer already reported trying: " + ", ".join(repeated))

    if not retrieved and GUIDANCE_RE.search(text):
        errors.append("unsupported troubleshooting: the reply gives steps but no evidence was "
                      "retrieved to support them")

    return tuple(errors)


__all__ = ["validate", "tried_steps"]
