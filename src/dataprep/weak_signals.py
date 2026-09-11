"""Weak signals from keyword heuristics. Weak supervision only, never ground truth.

- weak_outcome + outcome_confidence: how the customer reacted to the brand's reply. Derived from
  the customer's *next* tweet, i.e. from the future, so it is kept on the train split only.
- customer_escalation_signals: cues in the customer's own message (anger, security, ...). They
  come from the model's input, so they are kept on every split.
- brand_escalation_evidence: what the historical reply did (asked for a DM, handed off, cited
  policy). It describes the reference answer, i.e. a weak label, so it is kept on train only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.dataprep.text import (
    ANGER, BILLING_DISPUTE, DM_REDIRECT, FIX_CONFIRMED, FIX_NEGATED, HANDOFF, LEGAL, NEGATIVE,
    POLICY, POSITIVE, REPEAT_CONTACT, SECURITY,
)

WEAK_OUTCOME_SOURCE = "heuristic_v1"

# (weak_outcome, condition, outcome_confidence, basis). The confidence comes from the Phase 1
# hand checks (results/brand_validation.md, section 3).
OUTCOME_RULES = [
    ("resolved", "customer confirms a fix after a substantive reply", "medium",
     "fixes are real, but only ~half credit the brand's reply"),
    ("resolved", "customer confirms a fix after any other reply", "low",
     "mostly fixed elsewhere (chat, phone, by themselves)"),
    ("unresolved", "still / not working / negated fix (\"none of these worked\")", "medium",
     "~2/3 of sampled cues were genuine"),
    ("acknowledged", "thanks without a fix cue", "low", "~2/12 samples mentioned a fix"),
    ("deflected", "no cue in the answer (or no answer) and the reply was a pure DM request", "high",
     "the deflection itself is observed; DM detection was right in every sample"),
    ("unknown", "no answer or an answer with no cue", "none", "nothing to go on"),
]


def weak_outcome(next_text: pd.Series, reply_type: pd.Series) -> pd.DataFrame:
    nxt = next_text.fillna("").str.lower()
    negated = nxt.str.contains(NEGATIVE, regex=True) | nxt.str.contains(FIX_NEGATED, regex=True)
    fixed = nxt.str.contains(FIX_CONFIRMED, regex=True) & ~negated
    thanks = nxt.str.contains(POSITIVE, regex=True) & ~negated & ~fixed
    deflected = reply_type == "dm_deflection"
    outcome = np.select([fixed, negated, thanks, deflected],
                        ["resolved", "unresolved", "acknowledged", "deflected"], default="unknown")
    confidence = np.select(
        [fixed & (reply_type == "substantive"), fixed, negated, thanks, deflected],
        ["medium", "low", "medium", "low", "high"], default="none")
    return pd.DataFrame({"weak_outcome": outcome, "outcome_confidence": confidence}, index=next_text.index)


def customer_escalation_signals(customer_text: pd.Series, prior_threads: pd.Series) -> pd.Series:
    lower = customer_text.str.lower()
    return _codes({
        "anger": lower.str.contains(ANGER, regex=True),
        "legal_threat": lower.str.contains(LEGAL, regex=True),
        "security": lower.str.contains(SECURITY, regex=True),
        "billing_dispute": lower.str.contains(BILLING_DISPUTE, regex=True),
        "repeat_contact_cue": lower.str.contains(REPEAT_CONTACT, regex=True),
        "prior_contact": prior_threads >= 1,
    })


def brand_escalation_evidence(brand_reply: pd.Series) -> pd.Series:
    lower = brand_reply.str.lower()
    return _codes({
        "dm_request": lower.str.contains(DM_REDIRECT, regex=True),
        "handoff_other_channel": lower.str.contains(HANDOFF, regex=True),
        "policy_enforcement": lower.str.contains(POLICY, regex=True),
    })


def _codes(masks: dict[str, pd.Series]) -> pd.Series:
    """Boolean columns -> one list of the names that are True, per row."""
    names = list(masks)
    index = next(iter(masks.values())).index
    values = np.column_stack([np.asarray(m, dtype=bool) for m in masks.values()])
    return pd.Series([[n for n, v in zip(names, row) if v] for row in values], index=index)
