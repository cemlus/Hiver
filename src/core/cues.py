"""Deterministic extraction of the frozen policy's risk cues from raw conversation text.

Each pattern below implements one cue **as the frozen codebook defines it** (the `risk_rules` block
of `data/taxonomy/taxonomy_v1.yaml`), not as whatever would score well. The extractor runs at
evaluation time on the raw message and its context: no cue labels are ever added to an evaluation
set, and the golden CSVs are never touched.

Scope of the scan, which matters because cues are statements *the customer* makes:
  - the message being routed, plus the customer's own earlier turns in the thread
  - brand turns are read only to detect `prior_clarification` (did the brand ask this customer for
    missing details?)

Calibration policy: the patterns are written from the codebook definitions and validated against the
**dev** set's labelled cue columns (`scripts/validate_cue_extractor.py`). They are never tuned
against golden results. Known, deliberate misses are listed in `results/eval/cue_extractor_dev.md`:
where a dev cue label goes beyond the codebook definition, the definition wins.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.contracts import SupportRequest
from src.core.escalate import Cues

# Codebook: "Says the standard first-line fix for this issue was already tried (by themselves or as
# advised) and the problem persists."
STEPS_FAILED = r"""
    \b(?:i\s*(?:'ve|\s+have)?\s*)?(?:already\s+)?(?:tried|did|done|followed|attempted)\b
        (?![^.!?]{0,40}\bnot\b)                       # "tried" but not "haven't tried"
  | \bdidn'?t\s+(?:work|help|fix|do\s+anything)\b
  | \bdoes(?:n'?t|\s+not)\s+(?:work|help|fix)\b
  | \bstill\s+(?:not\s+working|doesn'?t|does\s+not|won'?t|wont|no\b|the\s+same|happening|same\s+(?:thing|issue|error|problem)|nothing)
  | \bstill\s+(?:it\s+)?(?:would|would'?nt|wouldn'?t|didn'?t)\b
  | \bnothing\s+(?:works|worked|helped|helps|has\s+helped|suggested)\b
  | \b(?:no\s+luck|to\s+no\s+avail|without\s+success|same\s+(?:issue|problem|error)\s+again)\b
  | \beven\s+after\s+(?:a\s+)?(?:reset|restart|reinstall|factory)
  | \bafter\s+(?:a\s+)?(?:reset|factory\s+reset|reinstall|re-?download)\b
  | \bre-?(?:downloaded|installed|set)\b[^.!?]{0,40}\b(?:still|persists?|again)\b
"""
# Codebook: "Says they already contacted support about this issue (DM, chat, phone, an earlier
# unanswered tweet) or have waited days."
REPEAT_CONTACT = r"""
    \b(?:already\s+)?(?:contacted|called|phoned|emailed|e-?mailed|messaged|chatted|spoke|spoken|
        talked|reached\s+out)\b[^.!?]{0,40}\b(?:support|team|agent|you|xbox|microsoft|chat|phone)\b
  | \b(?:sent|send|dm'?d|dmed)\s+(?:you\s+)?(?:a\s+|an\s+)?(?:dm|direct\s+message|email|message)\b
  | \b(?:chat|phone|support)\s+(?:team|agent|session|support)\b
  | \b(?:tried|trying)\s+to\s+(?:chat|call|contact|reach)\b
  | \b(?:still\s+waiting|no\s+(?:response|reply|answer)|never\s+(?:replied|responded|got\s+back)|
        haven'?t\s+heard\s+back|chased)\b
  | \b(?:in\s+case\s+you\s+(?:didn'?t|did\s+not)\s+see|second\s+time|third\s+time|again\s+and\s+again|
        for\s+(?:the\s+)?(?:second|third|fourth)\s+time)\b
  | \b(?:for|over|past)\s+\d+\s+(?:days?|weeks?|months?)\b
  | \b(?:every\s+day|days?\s+now|weeks?\s+now)\b
"""
# Codebook: "Profanity, insults or abuse aimed at Xbox or support, or a threat to leave."
STRONG_ANGER = r"""
    \b(?:fuck\w*|shit\w*|bullshit|bloody|crap\w*|damn|arse|ass\b)\b
  | \b(?:pathetic|useless|garbage|rubbish|disgrace\w*|appalling|atrocious|incompetent|
        (?:a\s+)?(?:complete|absolute|total)\s+joke|joke\b|clowns?\b|scam\w*)\b
  | \b(?:switch(?:ing)?|mov(?:e|ing)|go(?:ing)?|buy(?:ing)?)\s+(?:back\s+)?to\s+(?:a\s+)?(?:ps\s?\d|playstation|sony|nintendo)\b
  | \b(?:never\s+buying|done\s+with\s+xbox|cancel(?:ling|ing)?\s+my\s+(?:gold|game\s?pass|subscription))\b
"""
# Codebook: "Charged twice or without consent, refund refused, money taken." A plain refund how-to
# is NOT a money dispute (that is purchases_billing_orders, which escalates on its own rule).
MONEY_DISPUTE = r"""
    \b(?:charged|billed)\s+(?:me\s+)?(?:twice|again|multiple|two\s+times|without)\b
  | \bdouble[-\s]?charg\w*\b
  | \b(?:took|taken|stole|stolen)\s+my\s+money\b
  | \brefund\s+(?:was\s+)?(?:refused|denied|declined|rejected)\b
  | \b(?:denied|refused)\s+(?:me\s+)?(?:the\s+|a\s+|my\s+)?refund\b
  | \b(?:unauthori[sz]ed|unknown|unexpected)\s+(?:charge|payment|transaction)\b
  | \b(?:my\s+money\s+back|hold\s+on\s+my\s+(?:cc|card|credit))\b
"""
# Codebook: "Someone else is using or has taken the account; hacked; unauthorised sign-ins."
ACCOUNT_COMPROMISED = r"""
    \b(?:hack\w*|compromis\w*|stolen\s+(?:account|gamertag)|breach\w*)\b
  | \b(?:someone|somebody)\s+(?:else\s+)?(?:has|is|got|took|logged|signed|accessed|changed|using)\b
  | \b(?:unauthori[sz]ed|unknown)\s+(?:access|sign[-\s]?ins?|logins?|ip)\b
  | \b(?:other\s+)?ip'?s?\s+(?:accessing|logging|on)\b
  | \baccessing\s+my\s+(?:account|stuff|profile)\b
"""
# Codebook: "Threats of violence or self-harm, minors at risk, doxxing; lawsuits, police, lawyers."
HARM_OR_LEGAL = r"""
    \b(?:lawyer|solicitor|attorney|legal\s+action|sue\b|suing|court|police|trading\s+standards|
        ombudsman|regulator|small\s+claims)\b
  | \b(?:kill|hurt|harm)\s+(?:myself|himself|herself|themselves)\b
  | \b(?:doxx?\w*|address\s+posted|threaten\w*\s+(?:me|my\s+family))\b
  | \b(?:my\s+)?(?:son|daughter|child|kid)\b[^.!?]{0,40}\b(?:groom\w*|predator|unsafe|inappropriate)\b
"""
# Codebook (hardware rule d): repair, replacement, warranty or servicing.
REPAIR_OR_REPLACEMENT = r"""
    \b(?:repair\w*|replac\w*|warrant\w*|servic(?:e|ed|ing)|rma\b)\b
  | \b(?:fixable|get\s+it\s+fixed|send\s+it\s+(?:in|back)|new\s+(?:console|controller|cable|unit))\b
  | \b(?:needs?\s+(?:servicing|repairing|replacing)|broken\s+beyond)\b
"""
# Policy rules (c)/(d): the fix needs someone to see or change THIS customer's account, order,
# code or licence.
ACCOUNT_SPECIFIC = r"""
    \bmy\s+(?:account|gamertag|profile|order|pre-?order|subscription|membership|licen[cs]e|
        code|purchase|billing|card|cc\b)\b
  | \b(?:gamertag|gt)\s*(?:is|:)\s*\S+
  | \b(?:check|look\s+(?:in)?to|investigate|verify|reset|restore|refund|cancel|change)\s+
        (?:my|the)\s+(?:account|order|gamertag|subscription|purchase|code)\b
  | \b(?:request|need|want)\s+(?:a\s+)?(?:new|replacement)\s+(?:cable|controller|console|code)\b
  | \bhow\s+do\s+(?:i|you)\s+refund\b
  | \b(?:havent|haven'?t|still\s+not)\s+(?:got|received)\s+my\b
"""
_FLAGS = re.VERBOSE | re.IGNORECASE
CUSTOMER_PATTERNS = {
    "steps_failed": re.compile(STEPS_FAILED, _FLAGS),
    "repeat_contact": re.compile(REPEAT_CONTACT, _FLAGS),
    "strong_anger": re.compile(STRONG_ANGER, _FLAGS),
    "money_dispute": re.compile(MONEY_DISPUTE, _FLAGS),
    "account_compromised": re.compile(ACCOUNT_COMPROMISED, _FLAGS),
    "harm_or_legal": re.compile(HARM_OR_LEGAL, _FLAGS),
    "repair_or_replacement": re.compile(REPAIR_OR_REPLACEMENT, _FLAGS),
    "account_specific_action": re.compile(ACCOUNT_SPECIFIC, _FLAGS),
}
# C6: the brand asked THIS customer for missing details. Announcements, answers and troubleshooting
# steps do not count.
BRAND_ASKS = re.compile(
    r"(?:\?)|\b(?:can|could|would)\s+you\s+(?:dm|send|share|tell|let\s+us\s+know|provide)\b"
    r"|\b(?:please\s+)?(?:dm|send)\s+us\b|\bwhat\s+(?:is|are|error)\b", _FLAGS)


@dataclass(frozen=True)
class CueEvidence:
    """Which text matched, so a cue decision can be audited rather than trusted."""
    cue: str
    matched: str
    source: str          # "message" | "customer_context" | "brand_context"


def extract(request: SupportRequest) -> tuple[Cues, tuple[CueEvidence, ...]]:
    """Return the policy cues for a request, with the evidence that produced each one."""
    customer_texts = [("message", request.customer_text)]
    customer_texts += [("customer_context", t.text) for t in request.context
                       if t.role.startswith("customer")]
    flags: dict[str, bool] = {}
    evidence: list[CueEvidence] = []
    for cue, pattern in CUSTOMER_PATTERNS.items():
        flags[cue] = False
        for source, text in customer_texts:
            found = pattern.search(text or "")
            if found:
                flags[cue] = True
                evidence.append(CueEvidence(cue, found.group(0).strip()[:60], source))
                break

    prior = False
    for turn in request.context:
        if turn.role == "brand" and BRAND_ASKS.search(turn.text or ""):
            prior = True
            evidence.append(CueEvidence("prior_clarification", turn.text.strip()[:60], "brand_context"))
            break
    flags["prior_clarification"] = prior
    return Cues(**flags), tuple(evidence)


def cues_for(request: SupportRequest) -> Cues:
    return extract(request)[0]
