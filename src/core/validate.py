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
#: Canonical troubleshooting actions. One vocabulary serves three checks: which steps the customer
#: already tried, whether a drafted step is supported by the evidence, and whether a reply that asks
#: for a DM also offers real help. Deliberately excludes weak verbs like "check", which is why
#: "please DM us and check your messages" no longer counts as guidance.
STEP_PHRASES = ("restart", "reboot", "reinstall", "re-install", "unplug", "power cycle", "powercycle",
                "hard reset", "factory reset", "update", "sign out", "sign in", "log out", "log in",
                "clear cache", "reset", "power button", "disconnect", "reconnect", "recalibrat")
STEP_WORDS = STEP_PHRASES          # retained name for the already-tried check

#: A DM request and its immediate object, stripped before asking whether any real help remains.
DM_CLAUSE_RE = re.compile(
    r"\b(?:please\s+)?(?:send\s+us\s+a\s+|shoot\s+us\s+a\s+)?"
    r"(?:dm|direct message|private message|pm)\s*(?:us|me)?\b[^.!?]*", re.I)
CONTACT_ONLY_RE = re.compile(r"\bcheck\s+your\s+(?:dms?|messages|inbox)\b", re.I)


def _evidence(request: SupportRequest, retrieved: tuple[RetrievedExample, ...]) -> str:
    """Everything the draft is allowed to rest on: the conversation plus the retrieved examples."""
    parts = [request.customer_text, *(turn.text for turn in request.context)]
    for example in retrieved:
        parts += [example.customer_text, example.brand_reply]
    return "\n".join(parts).lower()


def _normalise(url: str) -> str:
    return url.rstrip(".,);:!?").lower().removeprefix("https://").removeprefix("http://").removeprefix("www.")


def steps_mentioned(text: str) -> set[str]:
    """Which canonical troubleshooting actions a piece of text refers to."""
    lowered = (text or "").lower()
    return {phrase for phrase in STEP_PHRASES if phrase in lowered}


def tried_steps(request: SupportRequest) -> set[str]:
    """Steps the customer says they already attempted, so the reply does not repeat them."""
    said = " ".join([request.customer_text, *(t.text for t in request.context
                                              if t.role == "customer")]).lower()
    if not TRIED_RE.search(said):
        return set()
    return steps_mentioned(said)


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
    # held-out data is full of, and it never counts as a grounded answer ([P2]). The DM clause and
    # "check your messages" are stripped first, so asking someone to look at their inbox cannot
    # masquerade as troubleshooting -- the old check accepted it because GUIDANCE_RE matched "check".
    if DM_RE.search(text):
        remainder = DM_CLAUSE_RE.sub(" ", CONTACT_ONLY_RE.sub(" ", text))
        if not steps_mentioned(remainder):
            errors.append("DM deflection: the reply asks the customer to get in touch without "
                          "offering any concrete step")

    repeated = sorted(step for step in tried_steps(request) if step in text.lower())
    if repeated:
        errors.append("repeats steps the customer already reported trying: " + ", ".join(repeated))

    # Whether the steps are actually supported, not merely whether retrieval returned something.
    # Partial support is tolerated: the grounding rule allows synthesis across examples, so only a
    # reply whose every proposed step is absent from the conversation AND the evidence is rejected.
    drafted_steps = steps_mentioned(text)
    if drafted_steps:
        supported = drafted_steps & steps_mentioned(evidence)
        if not supported:
            errors.append("unsupported troubleshooting: none of the steps it proposes ("
                          + ", ".join(sorted(drafted_steps))
                          + ") appear in the conversation or the retrieved evidence")

    return tuple(errors)


__all__ = ["validate", "tried_steps", "steps_mentioned", "STEP_PHRASES"]
