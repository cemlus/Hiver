"""Non-LLM routing baselines: the floor the agent has to beat. No API calls, no quota.

Every baseline returns `list[AgentOutput]`, so the metrics treat them exactly like the agent.
Escalation always goes through the frozen policy in `src/core/escalate.py` rather than being
invented per baseline — except for `always_escalate` / `never_escalate`, whose whole purpose is to
pin the extremes of the precision/recall trade-off.

`tfidf_lr` is **weakly supervised**: its labels come from `src/eval/training_labels.py`, which is
assistant-coded and LLM-drafted data, never independent human annotation.
"""
from __future__ import annotations

import re
from collections import Counter

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from src.config import load_config
from src.contracts import (AgentOutput, ConversationState, EscalationDecision, GoldenExample,
                           Intent, ReasonCode, TriggeredBy)
from src.core.cues import cues_for
from src.core.escalate import Cues, decide
from src.eval.training_labels import intent_training_set, state_training_set, training_corpus

# --- deterministic cue extraction (input-side only; used by the keyword baseline) ---------------
CUE_PATTERNS = {
    "strong_anger": r"\b(?:fuck\w*|shit|bullshit|crap|useless|pathetic|joke|garbage|ridiculous)\b|"
                    r"\b(?:switch(?:ing)? to|buy(?:ing)? a) (?:ps\d|playstation)\b",
    "repeat_contact": r"\b(?:already (?:contacted|called|chatted|emailed|spoke)|still waiting|"
                      r"third time|again and again|no(?:-| )?one (?:has )?(?:replied|responded|helped)|"
                      r"chat(?:ted)? (?:with )?support|phone team|customer service)\b",
    "steps_failed": r"\b(?:(?:i(?:'ve| have)? )?(?:tried|did) (?:that|this|everything|all)|didn'?t work|"
                    r"does(?:n'?t| not) work|still (?:not working|doesn'?t|won'?t|happening|same)|"
                    r"nothing (?:works|helped|suggested)|no luck|to no avail)\b",
    "account_specific_action": r"\b(?:my (?:account|gamertag|profile|order|subscription)|gamertag is|"
                               r"my gt\b|change my|on my account)\b",
    "repair_or_replacement": r"\b(?:repair\w*|replace\w*|warranty|servic(?:e|ing)|rma|fixable|"
                             r"send it (?:in|back))\b",
    "account_compromised": r"\b(?:hack\w*|compromis\w*|unauthori[sz]ed|someone (?:else )?(?:has|is using|"
                           r"logged|changed)|stolen)\b",
    "harm_or_legal": r"\b(?:lawyer|solicitor|legal action|sue|police|trading standards|ombudsman|"
                     r"kill myself|threat(?:en)?(?:ed|ing)? (?:me|to))\b",
    "money_dispute": r"\b(?:charged (?:twice|again|without)|double charged|took my money|refund (?:refused|"
                     r"denied)|stole my money|unauthori[sz]ed charge|my money back)\b",
}
_CUE_RE = {name: re.compile(pattern, re.I) for name, pattern in CUE_PATTERNS.items()}
_CLOSING_RE = re.compile(r"\b(?:thanks|thank you|cheers|ta\b|appreciate it|it works|working now|"
                         r"fixed|sorted|all good|resolved)\b", re.I)
_QUESTION_RE = re.compile(r"\?|\b(?:how|what|when|why|where|can i|do i|is there|will there)\b", re.I)
# Ordered: the first pattern that matches wins, most specific first.
INTENT_PATTERNS: list[tuple[Intent, str]] = [
    (Intent.ENFORCEMENT_SAFETY, r"\b(?:bann?(?:ed|ing)?|suspen\w*|enforcement|code of conduct|"
                                r"reported (?:me|a|him|her|them)|gamerpic|harass\w*|cheat\w*)\b"),
    (Intent.PURCHASES_BILLING_ORDERS, r"\b(?:refund\w*|charg(?:e|ed|ing)|payment|billing|invoice|"
                                      r"credit card|paypal|pre-?order\w*|delivery|shipped|price|money)\b"),
    (Intent.ENTITLEMENTS_SUBSCRIPTIONS_CODES, r"\b(?:codes?|redeem\w*|gift ?card|game ?pass|gold|"
                                              r"subscription|season pass|dlc|licen[cs]e|trial|"
                                              r"game sharing|home xbox)\b"),
    (Intent.ACCOUNT_ACCESS_PROFILE, r"\b(?:account|sign(?:ed|ing)? ?in|log ?in|password|e-?mail|"
                                    r"gamertag|profile|child account|family settings)\b"),
    (Intent.CONNECTIVITY_XBOX_LIVE, r"\b(?:connect\w*|disconnect\w*|online|servers?|nat\b|lag\w*|"
                                    r"party chat|matchmaking|xbox live (?:down|status)|network)\b"),
    (Intent.INSTALL_DOWNLOAD_UPDATE, r"\b(?:download\w*|install\w*|updat\w*|patch|storage|queue|"
                                     r"re-?download)\b"),
    (Intent.HARDWARE_DEVICES, r"\b(?:controller|console|disc drive|disc|hdmi|headset|kinect|power|"
                              r"overheat\w*|fan|hard ?drive|screen|turn on|won'?t start)\b"),
    (Intent.SOFTWARE_GAME_APP, r"\b(?:crash\w*|freez\w*|bug|glitch|error code|launch|achievement|"
                               r"app\b|dashboard|game won'?t)\b"),
    (Intent.SUPPORT_PROCESS_COMPLAINT, r"\b(?:no(?:-| )?one helps|still waiting|ignor\w*|"
                                       r"support team|useless support)\b"),
    (Intent.PRODUCT_INFO_FEEDBACK, r"\b(?:how do i|can i|is there|does it|will it|when will|"
                                   r"backwards? compat\w*|suggest\w*|feedback)\b"),
]
_INTENT_RE = [(intent, re.compile(pattern, re.I)) for intent, pattern in INTENT_PATTERNS]


def keyword_cues(example: GoldenExample) -> Cues:
    """The ORIGINAL, weaker cue reading kept so `keyword_rule` stays frozen for comparison.
    `src/core/cues.py` holds the codebook-derived extractor used by the cue-enhanced baselines."""
    text = example.request.customer_text
    flags = {name: bool(rx.search(text)) for name, rx in _CUE_RE.items()}
    turns = example.request.context
    flags["prior_clarification"] = bool(turns) and turns[-1].role == "brand" and "?" in turns[-1].text
    return Cues(**flags)


def _output(example: GoldenExample, state: ConversationState, intent: Intent | None,
            decision: EscalationDecision, system: str, confidence: float = 0.0) -> AgentOutput:
    if state in {ConversationState.ACKNOWLEDGEMENT_CLOSING, ConversationState.SOCIAL_OFFTOPIC}:
        intent = None
    return AgentOutput(request_id=example.request.request_id, system=system, conversation_state=state,
                       intent=intent, intent_confidence=confidence, escalate=decision.escalate,
                       reason_code=decision.reason_code, reason_text=decision.reason_text,
                       codebook_version=load_config()["codebook_version"])


# --- trivial baselines --------------------------------------------------------------------------
def _majority_labels() -> tuple[ConversationState, Intent]:
    corpus = training_corpus()
    state = Counter(corpus.loc[corpus["conversation_state"] != "", "conversation_state"]).most_common(1)[0][0]
    intent = Counter(corpus.loc[corpus["intent"] != "", "intent"]).most_common(1)[0][0]
    return ConversationState(state), Intent(intent)


def majority(examples: list[GoldenExample]) -> list[AgentOutput]:
    """Always predicts the most frequent labelled state and intent; escalation from the policy."""
    state, intent = _majority_labels()
    return [_output(e, state, intent, decide(intent), "majority") for e in examples]


def always_escalate(examples: list[GoldenExample]) -> list[AgentOutput]:
    """Escalation recall ceiling. Routing fields come from the majority baseline."""
    state, intent = _majority_labels()
    forced = EscalationDecision(escalate=True, reason_code=ReasonCode.LOW_CONFIDENCE,
                                reason_text="baseline escalates every item",
                                triggered_by=TriggeredBy.MODEL)
    return [_output(e, state, intent, forced, "always_escalate") for e in examples]


def never_escalate(examples: list[GoldenExample]) -> list[AgentOutput]:
    """The "do nothing" floor: every item auto-handled."""
    state, intent = _majority_labels()
    auto = EscalationDecision(escalate=False, reason_code=ReasonCode.GENERAL_INFO,
                              reason_text="baseline never escalates", triggered_by=TriggeredBy.POLICY)
    return [_output(e, state, intent, auto, "never_escalate") for e in examples]


# --- deterministic keyword / rule baseline -------------------------------------------------------
def _keyword_state(example: GoldenExample) -> ConversationState:
    text = example.request.customer_text
    closing = bool(_CLOSING_RE.search(text)) and not _QUESTION_RE.search(text)
    if closing:
        return ConversationState.ACKNOWLEDGEMENT_CLOSING
    if len(text.split()) <= 4 and not _QUESTION_RE.search(text):
        return ConversationState.SOCIAL_OFFTOPIC
    return ConversationState.ISSUE_FOLLOWUP if example.request.is_followup else ConversationState.NEW_ISSUE


def _keyword_intent(example: GoldenExample) -> Intent:
    text = example.request.customer_text
    for intent, rx in _INTENT_RE:
        if rx.search(text):
            return intent
    return Intent.NEEDS_MORE_CONTEXT


def keyword_rule(examples: list[GoldenExample]) -> list[AgentOutput]:
    """Regex intent + policy escalation driven by regex cues. Fully deterministic, no training."""
    outputs = []
    for example in examples:
        state = _keyword_state(example)
        intent = None if state in {ConversationState.ACKNOWLEDGEMENT_CLOSING,
                                   ConversationState.SOCIAL_OFFTOPIC} else _keyword_intent(example)
        outputs.append(_output(example, state, intent, decide(intent, keyword_cues(example)),
                               "keyword_rule"))
    return outputs


# --- classical ML baseline (weakly supervised) ---------------------------------------------------
def _vectorizer() -> FeatureUnion:
    return FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True, lowercase=True)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True)),
    ])


def _fit(texts: pd.Series, labels: pd.Series, seed: int) -> Pipeline:
    model = Pipeline([("features", _vectorizer()),
                      ("clf", LogisticRegression(max_iter=2000, class_weight="balanced",
                                                 random_state=seed))])
    return model.fit(texts, labels)


def tfidf_lr(examples: list[GoldenExample]) -> list[AgentOutput]:
    """TF-IDF (word + char) → logistic regression for state and intent, trained on the weakly
    supervised non-golden corpus. Escalation comes from the policy, cue-blind."""
    seed = load_config()["seed"]
    states, intents = state_training_set(), intent_training_set()
    state_model = _fit(states["text"], states["conversation_state"], seed)
    intent_model = _fit(intents["text"], intents["intent"], seed)

    texts = pd.Series([e.request.customer_text for e in examples])
    predicted_states = state_model.predict(texts)
    predicted_intents = intent_model.predict(texts)
    confidences = intent_model.predict_proba(texts).max(axis=1)

    outputs = []
    for example, state, intent, confidence in zip(examples, predicted_states, predicted_intents,
                                                  confidences):
        state = ConversationState(state)
        intent_value = None if state in {ConversationState.ACKNOWLEDGEMENT_CLOSING,
                                         ConversationState.SOCIAL_OFFTOPIC} else Intent(intent)
        outputs.append(_output(example, state, intent_value, decide(intent_value), "tfidf_lr",
                               float(confidence)))
    return outputs


# --- cue-enhanced deterministic baselines --------------------------------------------------------
# These isolate the contribution of explicit policy-cue extraction. The cues come from
# src/core/cues.py, derived from the frozen codebook and validated on dev
# (results/eval/cue_extractor_dev.md), never tuned against golden results. No cue labels are added
# to any evaluation file: cues are computed at evaluation time from the raw message and context.
def cue_rule(examples: list[GoldenExample]) -> list[AgentOutput]:
    """Regex intent + the codebook-derived cue extractor. Same routing as `keyword_rule`, so the
    difference between the two is purely the quality of the cue extraction."""
    outputs = []
    for example in examples:
        state = _keyword_state(example)
        intent = None if state in {ConversationState.ACKNOWLEDGEMENT_CLOSING,
                                   ConversationState.SOCIAL_OFFTOPIC} else _keyword_intent(example)
        decision = decide(intent, cues_for(example.request))
        outputs.append(_output(example, state, intent, decision, "cue_rule"))
    return outputs


def tfidf_lr_cues(examples: list[GoldenExample]) -> list[AgentOutput]:
    """Learned intent + the codebook-derived cue extractor: the difference from `tfidf_lr` is
    exactly what explicit policy-cue handling adds to a cue-blind statistical classifier."""
    base = {o.request_id: o for o in tfidf_lr(examples)}
    outputs = []
    for example in examples:
        predicted = base[example.request.request_id]
        decision = decide(predicted.intent, cues_for(example.request))
        outputs.append(_output(example, predicted.conversation_state, predicted.intent, decision,
                               "tfidf_lr_cues", predicted.intent_confidence))
    return outputs


BASELINES = {
    "majority": majority,
    "always_escalate": always_escalate,
    "never_escalate": never_escalate,
    "keyword_rule": keyword_rule,
    "tfidf_lr": tfidf_lr,
    "cue_rule": cue_rule,
    "tfidf_lr_cues": tfidf_lr_cues,
}
