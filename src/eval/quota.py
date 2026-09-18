"""Reading Groq's rate-limit errors, in one place.

`scripts/warm_agent_cache.py` and `scripts/draft_dev_replies.py` each grew their own copy of this
logic. Rather than write a third, new callers use this module.

The distinction that matters: the **daily** token budget and the **per-minute** one fail the same
way but need different waits, and the per-minute headers report capacity as available even while
the daily budget is exhausted (DECISIONS.md [P7]) -- so a tiny probe succeeding proves nothing
about a real call. Always read the full error body; a truncated one hides the TPD message.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

WAIT_RE = re.compile(r"try again in ([0-9hms.]+)")
TPD_RE = re.compile(r"tokens per day \(TPD\): Limit (\d+), Used (\d+), Requested (\d+)")

DAILY = "tokens_per_day"
PER_MINUTE = "tokens_per_minute"


def parse_wait(message: str) -> float | None:
    """Seconds from a "try again in 11m17.376s" message, or None if it names no wait."""
    found = WAIT_RE.search(message)
    if not found:
        return None
    # The character class is greedy and swallows the sentence's full stop: "try again in 11m17.376s."
    # captures a trailing "." that float() will not take.
    total, number = 0.0, ""
    for char in found.group(1).rstrip("."):
        if char.isdigit() or char == ".":
            number += char
        elif char == "h":
            total, number = total + float(number or 0) * 3600, ""
        elif char == "m":
            total, number = total + float(number or 0) * 60, ""
        elif char == "s":
            total, number = total + float(number or 0), ""
    try:
        return total + float(number or 0)
    except ValueError:                      # a stray separator left in the tail
        return total or None


@dataclass(frozen=True)
class Limit:
    """A rate limit the API reported: which budget, how long to wait, and its own numbers."""
    kind: str
    wait_seconds: float
    used: int | None = None
    cap: int | None = None


def classify(message: str, *, max_wait: float = 1800.0) -> Limit | None:
    """Read an exception message. Returns None when it is not a rate limit at all."""
    tpd = TPD_RE.search(message)
    named = parse_wait(message)
    if tpd:
        return Limit(DAILY, min(named or 900.0, max_wait) + 20,
                     used=int(tpd.group(2)), cap=int(tpd.group(1)))
    if "tokens per day" in message.lower():
        return Limit(DAILY, min(named or 900.0, max_wait) + 20)
    if named is not None or "rate limit" in message.lower():
        return Limit(PER_MINUTE, min(named or 70.0, 300.0) + 5)
    return None


__all__ = ["classify", "parse_wait", "Limit", "DAILY", "PER_MINUTE", "TPD_RE", "WAIT_RE"]
