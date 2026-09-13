"""Routing metrics with bootstrap confidence intervals. Framework-free, no I/O.

Every metric is computed from per-item arrays, so the bootstrap simply resamples item indices and
recomputes. Metric definitions follow the frozen codebook's `scoring` block, with one documented
deviation: see `MUST_ESCALATE_LIMITATION`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from src.contracts import AgentOutput, ConversationState, GoldenExample, Intent, RiskLevel
from src.core.escalate import cue_blind_risk

INTENT_BEARING = (ConversationState.NEW_ISSUE, ConversationState.ISSUE_FOLLOWUP)
MUST_ESCALATE_LIMITATION = (
    "must_escalate_recall_cue_blind is a PROXY, not the metric originally specified. The locked "
    "golden sheet carries no cue, risk or reason columns, so risk is derived by running the frozen "
    "policy cue-blind over the gold intent, which yields the intent's default risk. Items that "
    "would reach high risk only through the SECURITY / SAFETY_LEGAL / BILLING_DISPUTE cue rules "
    "cannot be identified, so this proxy under-counts the true must-escalate set."
)


@dataclass
class Metric:
    """A metric with its bootstrap interval and the number of items it was computed over."""
    value: float
    lo: float = float("nan")
    hi: float = float("nan")
    support: int = 0
    note: str = ""

    def __str__(self) -> str:
        if np.isnan(self.lo):
            return f"{self.value:.3f} (n={self.support})"
        return f"{self.value:.3f} [{self.lo:.3f}–{self.hi:.3f}] (n={self.support})"


@dataclass
class RoutingResult:
    system: str
    metrics: dict[str, Metric]
    per_intent: dict[str, dict[str, float]] = field(default_factory=dict)
    confusion_state: dict[str, dict[str, int]] = field(default_factory=dict)
    confusion_intent: dict[str, dict[str, int]] = field(default_factory=dict)


def _macro_f1(truth: np.ndarray, pred: np.ndarray, labels: tuple[str, ...]) -> float:
    scores = []
    for label in labels:
        tp = int(np.sum((truth == label) & (pred == label)))
        fp = int(np.sum((truth != label) & (pred == label)))
        fn = int(np.sum((truth == label) & (pred != label)))
        if tp + fn == 0 and tp + fp == 0:
            continue                      # class absent from both: it would only dilute the mean
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return float(np.mean(scores)) if scores else float("nan")


def _prf(truth: np.ndarray, pred: np.ndarray, label: str) -> tuple[float, float, float, int]:
    tp = int(np.sum((truth == label) & (pred == label)))
    fp = int(np.sum((truth != label) & (pred == label)))
    fn = int(np.sum((truth == label) & (pred != label)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1, tp + fn


class _Arrays:
    """Per-item arrays; every metric is a function of an index selection into these."""

    def __init__(self, gold: list[GoldenExample], pred: list[AgentOutput]):
        by_id = {p.request_id: p for p in pred}
        missing = [g.request.request_id for g in gold if g.request.request_id not in by_id]
        if missing:
            raise ValueError(f"no prediction for {len(missing)} item(s), e.g. {missing[:3]}")
        ordered = [by_id[g.request.request_id] for g in gold]
        self.gold_state = np.array([g.label_conversation_state.value for g in gold])
        self.pred_state = np.array([p.conversation_state.value for p in ordered])
        self.gold_intent = np.array([g.label_intent.value if g.label_intent else "" for g in gold])
        self.pred_intent = np.array([p.intent.value if p.intent else "" for p in ordered])
        self.gold_esc = np.array([g.label_escalate for g in gold])
        self.pred_esc = np.array([p.escalate for p in ordered])
        self.intent_bearing = np.isin(self.gold_state, [s.value for s in INTENT_BEARING])
        must = np.array([cue_blind_risk(g.label_intent) is RiskLevel.HIGH for g in gold])
        self.must_escalate = must & self.gold_esc

    def compute(self, idx: np.ndarray) -> dict[str, float]:
        gs, ps = self.gold_state[idx], self.pred_state[idx]
        gi, pi = self.gold_intent[idx], self.pred_intent[idx]
        ge, pe = self.gold_esc[idx], self.pred_esc[idx]
        bearing, must = self.intent_bearing[idx], self.must_escalate[idx]
        states = tuple(s.value for s in ConversationState)
        intents = tuple(i.value for i in Intent)

        out = {"state_accuracy": float(np.mean(gs == ps)) if len(idx) else float("nan"),
               "state_macro_f1": _macro_f1(gs, ps, states)}
        # Intent is scored only where the gold state carries one; a missing prediction is an error.
        out["intent_macro_f1"] = (_macro_f1(gi[bearing], pi[bearing], intents) if bearing.any()
                                  else float("nan"))
        out["intent_accuracy"] = (float(np.mean(gi[bearing] == pi[bearing])) if bearing.any()
                                  else float("nan"))
        tp = int(np.sum(ge & pe))
        out["escalation_precision"] = tp / int(np.sum(pe)) if np.sum(pe) else float("nan")
        out["escalation_recall"] = tp / int(np.sum(ge)) if np.sum(ge) else float("nan")
        out["must_escalate_recall_cue_blind"] = (int(np.sum(must & pe)) / int(np.sum(must))
                                                 if np.sum(must) else float("nan"))
        joint = (gs == ps) & (ge == pe) & ((gi == pi) | ~bearing)
        out["joint_routing_correctness"] = float(np.mean(joint)) if len(idx) else float("nan")
        return out


def evaluate(gold: list[GoldenExample], pred: list[AgentOutput], system: str = "system",
             n_boot: int = 10_000, seed: int = 42) -> RoutingResult:
    """All routing metrics with percentile bootstrap 95% CIs over items."""
    arrays = _Arrays(gold, pred)
    n = len(gold)
    point = arrays.compute(np.arange(n))

    rng = np.random.default_rng(seed)
    samples: dict[str, list[float]] = {k: [] for k in point}
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        for key, value in arrays.compute(idx).items():
            samples[key].append(value)

    supports = {"state_accuracy": n, "state_macro_f1": n, "joint_routing_correctness": n,
                "intent_macro_f1": int(arrays.intent_bearing.sum()),
                "intent_accuracy": int(arrays.intent_bearing.sum()),
                "escalation_precision": int(arrays.pred_esc.sum()),
                "escalation_recall": int(arrays.gold_esc.sum()),
                "must_escalate_recall_cue_blind": int(arrays.must_escalate.sum())}
    metrics = {}
    for key, value in point.items():
        draws = np.array(samples[key], dtype=float)
        draws = draws[~np.isnan(draws)]
        lo, hi = (np.percentile(draws, [2.5, 97.5]) if len(draws) else (float("nan"),) * 2)
        metrics[key] = Metric(value=value, lo=float(lo), hi=float(hi), support=supports.get(key, n),
                              note=MUST_ESCALATE_LIMITATION if key.startswith("must_escalate") else "")

    per_intent = {}
    bearing = arrays.intent_bearing
    for intent in Intent:
        precision, recall, f1, support = _prf(arrays.gold_intent[bearing], arrays.pred_intent[bearing],
                                              intent.value)
        if support or np.sum(arrays.pred_intent[bearing] == intent.value):
            per_intent[intent.value] = {"precision": precision, "recall": recall, "f1": f1,
                                        "support": support}

    def table(truth: np.ndarray, pred_values: np.ndarray) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for t in sorted(set(truth)):
            out[t or "(none)"] = {}
            for p in sorted(set(pred_values)):
                out[t or "(none)"][p or "(none)"] = int(np.sum((truth == t) & (pred_values == p)))
        return out

    return RoutingResult(system=system, metrics=metrics, per_intent=per_intent,
                         confusion_state=table(arrays.gold_state, arrays.pred_state),
                         confusion_intent=table(arrays.gold_intent[bearing], arrays.pred_intent[bearing]))
