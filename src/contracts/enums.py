"""Enumerations shared by every module. They mirror the frozen codebook v1, and
`tests/test_contracts.py` fails if they drift from `data/taxonomy/taxonomy_v1.yaml`.
"""
from __future__ import annotations

from enum import StrEnum


class ConversationState(StrEnum):
    NEW_ISSUE = "new_issue"
    ISSUE_FOLLOWUP = "issue_followup"
    ACKNOWLEDGEMENT_CLOSING = "acknowledgement_closing"
    SOCIAL_OFFTOPIC = "social_offtopic"


class Intent(StrEnum):
    CONNECTIVITY_XBOX_LIVE = "connectivity_xbox_live"
    INSTALL_DOWNLOAD_UPDATE = "install_download_update"
    HARDWARE_DEVICES = "hardware_devices"
    SOFTWARE_GAME_APP = "software_game_app"
    ACCOUNT_ACCESS_PROFILE = "account_access_profile"
    PURCHASES_BILLING_ORDERS = "purchases_billing_orders"
    ENTITLEMENTS_SUBSCRIPTIONS_CODES = "entitlements_subscriptions_codes"
    ENFORCEMENT_SAFETY = "enforcement_safety"
    PRODUCT_INFO_FEEDBACK = "product_info_feedback"
    SUPPORT_PROCESS_COMPLAINT = "support_process_complaint"
    NEEDS_MORE_CONTEXT = "needs_more_context"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReasonCode(StrEnum):
    # Escalation reasons, in the codebook's priority order.
    SECURITY = "SECURITY"
    SAFETY_LEGAL = "SAFETY_LEGAL"
    BILLING_DISPUTE = "BILLING_DISPUTE"
    ACCOUNT_SPECIFIC = "ACCOUNT_SPECIFIC"
    REPEAT_CONTACT = "REPEAT_CONTACT"
    STEPS_FAILED = "STEPS_FAILED"
    HIGH_ANGER = "HIGH_ANGER"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    REPLY_FAILED_CHECKS = "REPLY_FAILED_CHECKS"   # system only: the drafted reply failed validation
    # Auto-handled reasons.
    ROUTINE_TROUBLESHOOTING = "ROUTINE_TROUBLESHOOTING"
    GENERAL_INFO = "GENERAL_INFO"


class TriggeredBy(StrEnum):
    RULE = "rule"            # a risk rule fired on a labelled cue
    POLICY = "policy"        # the intent's own escalation policy
    SIGNAL = "signal"        # a weak keyword signal
    VALIDATION = "validation"  # the drafted reply failed its checks
    MODEL = "model"          # low classifier confidence


class Split(StrEnum):
    TRAIN = "train"
    HOLDOUT = "holdout"
    EXCLUDED = "excluded"


class WeakLabelSource(StrEnum):
    HEURISTIC_V1 = "heuristic_v1"
    LLM = "llm"


#: States that carry no intent (codebook `states_without_intent`).
STATES_WITHOUT_INTENT = frozenset({ConversationState.ACKNOWLEDGEMENT_CLOSING,
                                   ConversationState.SOCIAL_OFFTOPIC})
#: Reason codes that may only appear when escalate is true.
ESCALATION_CODES = frozenset({ReasonCode.SECURITY, ReasonCode.SAFETY_LEGAL, ReasonCode.BILLING_DISPUTE,
                              ReasonCode.ACCOUNT_SPECIFIC, ReasonCode.REPEAT_CONTACT, ReasonCode.STEPS_FAILED,
                              ReasonCode.HIGH_ANGER, ReasonCode.OUT_OF_SCOPE, ReasonCode.LOW_CONFIDENCE,
                              ReasonCode.REPLY_FAILED_CHECKS})
#: Reason codes that may only appear when escalate is false.
AUTO_CODES = frozenset({ReasonCode.ROUTINE_TROUBLESHOOTING, ReasonCode.GENERAL_INFO})
#: The codebook's priority order for choosing among several escalation reasons.
REASON_PRIORITY = (ReasonCode.SECURITY, ReasonCode.SAFETY_LEGAL, ReasonCode.BILLING_DISPUTE,
                   ReasonCode.ACCOUNT_SPECIFIC, ReasonCode.REPEAT_CONTACT, ReasonCode.STEPS_FAILED,
                   ReasonCode.HIGH_ANGER, ReasonCode.OUT_OF_SCOPE, ReasonCode.LOW_CONFIDENCE,
                   ReasonCode.REPLY_FAILED_CHECKS)
