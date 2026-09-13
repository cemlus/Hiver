"""The frozen escalation policy (codebook v1, escalation frozen 2026-09-11). Framework-free.

Ported from the `decide()` used to calibrate and freeze the policy in
`scripts/calibrate_escalation.py`; `tests/test_escalate.py` replays the 40 labelled dev items
through this module and requires the same decisions, so the port cannot drift from what was frozen.

The design rule is **"the LLM proposes; the system decides"**: a model may propose the intent and
the cues, but `escalate` and `reason_code` are computed here, deterministically. Rules (a)-(i) below
are the codebook's `escalation_combination` block verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

import yaml

from src.config import resolve
from src.contracts import (REASON_PRIORITY, EscalationDecision, Intent, ReasonCode, RiskLevel,
                           TriggeredBy)

#: Intents whose auto reply is troubleshooting rather than an answer (for the auto reason code).
FIX_INTENTS = frozenset({Intent.CONNECTIVITY_XBOX_LIVE, Intent.INSTALL_DOWNLOAD_UPDATE,
                         Intent.HARDWARE_DEVICES, Intent.SOFTWARE_GAME_APP,
                         Intent.ACCOUNT_ACCESS_PROFILE, Intent.ENTITLEMENTS_SUBSCRIPTIONS_CODES})
#: Intents that always escalate (rule b).
ALWAYS_ESCALATE = frozenset({Intent.PURCHASES_BILLING_ORDERS, Intent.SUPPORT_PROCESS_COMPLAINT})
_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


@dataclass(frozen=True)
class Cues:
    """The nine policy cues. A cue-blind caller (a baseline, or gold data without cue columns)
    leaves them all false, which still lets the intent-level rules fire."""
    strong_anger: bool = False
    repeat_contact: bool = False
    steps_failed: bool = False
    account_specific_action: bool = False
    prior_clarification: bool = False
    repair_or_replacement: bool = False
    account_compromised: bool = False
    harm_or_legal: bool = False
    money_dispute: bool = False

    @classmethod
    def from_mapping(cls, values: dict[str, object], prefix: str = "") -> "Cues":
        """Build from a row of yes/no strings or booleans, e.g. the dev sheet's `cue_*` columns."""
        def flag(name: str) -> bool:
            raw = values.get(f"{prefix}{name}")
            if isinstance(raw, str):
                return raw.strip().lower() == "yes"
            return bool(raw)
        return cls(**{f.name: flag(f.name) for f in cls.__dataclass_fields__.values()})  # type: ignore[attr-defined]


@lru_cache(maxsize=1)
def default_risks() -> dict[Intent, RiskLevel]:
    """Each intent's default risk, read from the frozen spec so the two cannot disagree."""
    spec = yaml.safe_load(resolve("data/taxonomy/taxonomy_v1.yaml").read_text(encoding="utf-8"))
    return {Intent(it["name"]): RiskLevel(it["default_risk"]) for it in spec["intents"]}


def risk_level(intent: Intent | None, cues: Cues) -> RiskLevel:
    """risk = the highest of the intent's default risk and every rule that fires."""
    risk = default_risks().get(intent, RiskLevel.LOW) if intent else RiskLevel.LOW
    if cues.account_compromised or cues.harm_or_legal or cues.money_dispute:
        return RiskLevel.HIGH
    if _RISK_ORDER[risk] < _RISK_ORDER[RiskLevel.MEDIUM] and (
            cues.repeat_contact or cues.steps_failed or cues.strong_anger):
        return RiskLevel.MEDIUM
    return risk


def decide(intent: Intent | None, cues: Cues | None = None, *, low_confidence: bool = False
           ) -> EscalationDecision:
    """The frozen policy. Returns the escalate flag, the reason code and why it fired."""
    cues = cues or Cues()
    default = default_risks().get(intent, RiskLevel.LOW) if intent else RiskLevel.LOW
    risk = risk_level(intent, cues)
    reasons: list[tuple[ReasonCode, str, TriggeredBy]] = []

    if cues.account_compromised:                                            # (a) via a high-risk rule
        reasons.append((ReasonCode.SECURITY, "account compromised", TriggeredBy.RULE))
    if cues.harm_or_legal:
        reasons.append((ReasonCode.SAFETY_LEGAL, "harm or legal threat", TriggeredBy.RULE))
    if cues.money_dispute:
        reasons.append((ReasonCode.BILLING_DISPUTE, "money dispute", TriggeredBy.RULE))
    if intent in ALWAYS_ESCALATE:                                           # (b)
        if intent is Intent.PURCHASES_BILLING_ORDERS:
            code = ReasonCode.BILLING_DISPUTE if cues.money_dispute else ReasonCode.ACCOUNT_SPECIFIC
        else:
            code = ReasonCode.REPEAT_CONTACT if cues.repeat_contact else ReasonCode.HIGH_ANGER
        reasons.append((code, f"{intent.value} always escalates", TriggeredBy.POLICY))
    if intent is Intent.ACCOUNT_ACCESS_PROFILE and cues.account_specific_action:   # (c)
        reasons.append((ReasonCode.ACCOUNT_SPECIFIC, "needs the customer's own account", TriggeredBy.POLICY))
    if intent is Intent.ENTITLEMENTS_SUBSCRIPTIONS_CODES and cues.account_specific_action:
        reasons.append((ReasonCode.ACCOUNT_SPECIFIC, "a specific order, code or licence must be looked up",
                        TriggeredBy.POLICY))
    if intent is Intent.HARDWARE_DEVICES and cues.repair_or_replacement:    # (d)
        reasons.append((ReasonCode.ACCOUNT_SPECIFIC, "repair or replacement requested", TriggeredBy.POLICY))
    if cues.steps_failed:                                                   # (e)
        if cues.repeat_contact:
            reasons.append((ReasonCode.REPEAT_CONTACT, "repeat contact and the steps already failed",
                            TriggeredBy.RULE))
        else:
            reasons.append((ReasonCode.STEPS_FAILED, "the steps already failed", TriggeredBy.RULE))
    if cues.strong_anger and _RISK_ORDER[default] >= _RISK_ORDER[RiskLevel.MEDIUM]:   # (f)
        reasons.append((ReasonCode.HIGH_ANGER, "strong anger", TriggeredBy.RULE))
    if intent is Intent.NEEDS_MORE_CONTEXT and cues.prior_clarification:    # (g)
        reasons.append((ReasonCode.LOW_CONFIDENCE, "still vague after a clarification", TriggeredBy.POLICY))
    if low_confidence:                                                      # (h)
        reasons.append((ReasonCode.LOW_CONFIDENCE, "classifier confidence below the dev threshold",
                        TriggeredBy.MODEL))
    # (i) REPLY_FAILED_CHECKS is set by the reply validator, never here.

    if reasons:
        code = min((c for c, _, _ in reasons), key=REASON_PRIORITY.index)
        triggered = next(t for c, _, t in reasons if c is code)
        why = "; ".join(dict.fromkeys(text for _, text, _ in reasons))
        return EscalationDecision(escalate=True, reason_code=code, reason_text=why,
                                  risk_level=risk, triggered_by=triggered)
    auto = ReasonCode.ROUTINE_TROUBLESHOOTING if intent in FIX_INTENTS else ReasonCode.GENERAL_INFO
    return EscalationDecision(escalate=False, reason_code=auto, reason_text="", risk_level=risk,
                              triggered_by=TriggeredBy.POLICY)


def cue_blind_risk(intent: Intent | None) -> RiskLevel:
    """Risk with no cue information: exactly the intent's default risk. Used by the golden
    must-escalate proxy, because the locked sheet carries no cue, risk or reason columns."""
    return risk_level(intent, Cues())


__all__ = ["Cues", "decide", "risk_level", "cue_blind_risk", "default_risks", "FIX_INTENTS",
           "ALWAYS_ESCALATE", "replace"]
