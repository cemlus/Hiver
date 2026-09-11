"""Compare the DRAFT escalation policy with the labelled 40-item dev set and test proposed changes.

Run from the repo root:   uv run python scripts/calibrate_escalation.py

Reads data/golden/dev_labeling_sheet.csv (labels), data/golden/dev_sample_key.csv (slices),
data/taxonomy/taxonomy_v1.yaml (default risks) and the eval pool (message text, plus the real
XboxSupport reply as a weak cross-check). Writes results/escalation/dev_calibration.md.

Each policy is applied to the *labelled* state, intent and cues, so a disagreement is about the
policy, not about classification. Dev is for tuning only; this report is never a headline result.
The policies are analysis code here; the frozen policy moves into src/core in Phase 7.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.dataprep.loaders import eval_pool  # noqa: E402

GOLDEN = ROOT / "data" / "golden"
OUT = ROOT / "results" / "escalation" / "dev_calibration.md"
SPEC = yaml.safe_load((ROOT / "data" / "taxonomy" / "taxonomy_v1.yaml").read_text(encoding="utf-8"))
DEFAULT_RISK = {it["name"]: it["default_risk"] for it in SPEC["intents"]}

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
PRIORITY = ["SECURITY", "SAFETY_LEGAL", "BILLING_DISPUTE", "ACCOUNT_SPECIFIC", "REPEAT_CONTACT",
            "STEPS_FAILED", "HIGH_ANGER", "OUT_OF_SCOPE", "LOW_CONFIDENCE", "REPLY_FAILED_CHECKS"]
AUTO_CODES = ["ROUTINE_TROUBLESHOOTING", "GENERAL_INFO"]
MUST_ESCALATE_CODES = {"SECURITY", "SAFETY_LEGAL", "BILLING_DISPUTE"}
FIX_INTENTS = {"connectivity_xbox_live", "install_download_update", "hardware_devices",
               "software_game_app", "account_access_profile", "entitlements_subscriptions_codes"}
STEPS_INTENTS = {"hardware_devices", "entitlements_subscriptions_codes"}  # draft: own policy escalates on failed steps
HIGH_RULES = [("account_compromised", "SECURITY"), ("harm_or_legal", "SAFETY_LEGAL"),
              ("money_dispute", "BILLING_DISPUTE")]
CUE_NAMES = ["strong_anger", "repeat_contact", "steps_already_failed", "account_specific_action",
             "prior_clarification", "repair_or_replacement", "account_compromised", "harm_or_legal",
             "money_dispute"]
CUE_SHORT = dict(zip(CUE_NAMES, ["anger", "repeat", "steps_failed", "acct_specific", "prior_clar",
                                 "repair", "compromised", "harm_legal", "money"]))
HANDOFF = re.compile(r"\b(?:DM|direct message|chat|phone|contact)\b", re.I)


@dataclass(frozen=True)
class Policy:
    """One reading of the escalation rules. The fields are the behaviours the codebook asks to
    calibrate."""
    name: str
    steps_failed_alone: bool = False        # failed steps escalate any intent, repeat contact or not
    steps_failed_code: str = "ACCOUNT_SPECIFIC"
    repeat_contact_alone: bool = False      # a stated repeat contact escalates on its own
    anger_min_risk: str = "medium"          # lowest intent default risk on which anger escalates
    repair_on_request: bool = True          # a repair/replacement request escalates hardware at once
    account_always: bool = False            # every account_access_profile request escalates
    clarify_twice_escalates: bool = True    # needs_more_context after a brand clarification escalates


DRAFT = Policy("draft (literal reading)")
PROPOSED = replace(DRAFT, name="proposed", steps_failed_alone=True, steps_failed_code="STEPS_FAILED")
# Reading the draft's repeat_contact definition ("already did the steps") as enough on its own gives
# the same decisions as PROPOSED, without a reason code of its own.
DRAFT_BROAD = replace(DRAFT, name="draft (broad reading)", steps_failed_alone=True,
                      steps_failed_code="REPEAT_CONTACT")

ALTERNATIVES = [
    ("`strong_anger`", "Anger escalates every intent, low-risk ones too",
     replace(PROPOSED, anger_min_risk="low")),
    ("`repeat_contact`", "Any stated repeat contact escalates", replace(PROPOSED, repeat_contact_alone=True)),
    ("failed steps", "Failed steps escalate only with a stated repeat contact (the literal draft)", DRAFT),
    ("account-specific", "Every `account_access_profile` request escalates",
     replace(PROPOSED, account_always=True)),
    ("`needs_more_context` after a clarification", "Ask a second clarifying question instead of escalating",
     replace(PROPOSED, clarify_twice_escalates=False)),
    ("repair / replacement", "Hardware escalates only after failed steps, not on a repair request",
     replace(PROPOSED, repair_on_request=False)),
]


@dataclass
class Decision:
    escalate: bool
    reason: str
    risk: str
    why: str


def decide(intent: str | None, cue: dict, p: Policy) -> Decision:
    on = lambda name: bool(cue.get(name))  # noqa: E731  (a blank cue counts as no)
    default = DEFAULT_RISK.get(intent, "low")
    risk = default
    why: list[tuple[str, str]] = []
    for name, code in HIGH_RULES:
        if on(name):
            risk = "high"
            why.append((code, name.replace("_", " ")))
    if risk == "low" and any(on(n) for n in ("repeat_contact", "steps_already_failed", "strong_anger")):
        risk = "medium"
    if intent == "purchases_billing_orders":
        why.append(("BILLING_DISPUTE" if on("money_dispute") else "ACCOUNT_SPECIFIC", "purchases always escalate"))
    if intent == "support_process_complaint":
        why.append(("REPEAT_CONTACT" if on("repeat_contact") else "HIGH_ANGER", "support complaints always escalate"))
    if intent == "account_access_profile" and (on("account_specific_action") or p.account_always):
        why.append(("ACCOUNT_SPECIFIC", "needs the customer's own account"))
    if intent == "entitlements_subscriptions_codes" and on("account_specific_action"):
        why.append(("ACCOUNT_SPECIFIC", "a specific order, code or licence must be looked up"))
    if intent == "hardware_devices" and on("repair_or_replacement") and p.repair_on_request:
        why.append(("ACCOUNT_SPECIFIC", "repair or replacement requested"))
    if on("steps_already_failed"):
        if on("repeat_contact"):
            why.append(("REPEAT_CONTACT", "repeat contact and the steps already failed"))
        elif p.steps_failed_alone:
            why.append((p.steps_failed_code, "the steps already failed"))
        elif intent in STEPS_INTENTS:
            why.append(("ACCOUNT_SPECIFIC", "the steps already failed (intent policy)"))
    if on("repeat_contact") and p.repeat_contact_alone:
        why.append(("REPEAT_CONTACT", "repeat contact"))
    if on("strong_anger") and RISK_ORDER[default] >= RISK_ORDER[p.anger_min_risk]:
        why.append(("HIGH_ANGER", "strong anger"))
    if intent == "needs_more_context" and on("prior_clarification") and p.clarify_twice_escalates:
        why.append(("LOW_CONFIDENCE", "still vague after a clarification"))
    assert risk != "high" or why
    if why:
        code = min((c for c, _ in why), key=PRIORITY.index)
    else:
        code = "ROUTINE_TROUBLESHOOTING" if intent in FIX_INTENTS else "GENERAL_INFO"
    return Decision(bool(why), code, risk, "; ".join(dict.fromkeys(w for _, w in why)))


# --- hand-written notes (the assistant's reading; not labels) --------------------------------------
FIX_NOTE = re.compile(r"\[review fix [^\]]*\]")   # fixes made after review are appended to `notes`
NOTES = {
    "D30": "Supplies the network stats the brand asked for, as an image. An automated reply can't read it; "
           "the real brand moved to DM. One item: no rule proposed; watch on golden.",
    "D01": "Already DM'd the details (repeat contact, no failed steps). Auto first-line matches the real reply.",
    "D33": "Can't set a custom gamerpic although the account is verified adult: T7 points to "
           "`account_access_profile` (age/profile) rather than moderation. Escalation is the same either way.",
}

CHANGES = [
    ("C1. Split failed steps out of `repeat_contact` (the one change in behaviour).", [
        "Draft: `repeat_contact` covered both 'already contacted support' and 'already did the steps', "
        "and escalated when it fired *and* the steps had failed. With the two cues labelled separately "
        "this reads two ways. Read literally, failed steps alone are auto-handled except on hardware and "
        "entitlements, whose own policies escalate on failed steps.",
        "Proposed: two rules. `repeat_contact`: the customer says they already contacted support about "
        "this issue (DM, chat, phone, an earlier unanswered tweet) or have waited days. It raises risk "
        "to medium and does not escalate on its own. `steps_failed`: the customer says the standard "
        "first-line fix was already tried (by themselves or as advised) and the problem persists. It "
        "raises risk to medium and escalates on every intent.",
        "Evidence: D26, D31 and D35 (failed steps, no repeat contact) are labelled escalate, but the literal "
        "draft auto-handles them. D01 (repeat contact, no failed steps) is labelled auto. The codebook "
        "already forbids repeating steps the customer has tried, and that is most of what an automated "
        "reply could offer.",
        "Cost: it is the main driver of escalation volume outside the always-escalate intents. Watch "
        "escalation precision for `steps_failed` on golden.",
    ]),
    ("C2. New reason code `STEPS_FAILED`; `REPLY_FAILED_CHECKS` is system-only.", [
        "Escalations from C1 get `STEPS_FAILED`, or `REPEAT_CONTACT` when a repeat contact is also stated. "
        "Priority: … ACCOUNT_SPECIFIC > REPEAT_CONTACT > STEPS_FAILED > HIGH_ANGER …",
        "`REPLY_FAILED_CHECKS` is set only by the agent when its own drafted reply fails validation "
        "after retries (PLAN Phase 4, `triggered_by = validation`). Labellers never use it. The submitted "
        "labels used it on 5 items (D02, D15, D17, D26, D35) to mean 'the customer's steps failed'; they are "
        "re-coded (§7). "
        "Reason codes are informational, so no scored label changes.",
    ]),
    ("C3. `strong_anger` definition tightened; the threshold is unchanged.", [
        "It fires on profanity, insults or abuse aimed at Xbox or support, or a threat to leave. Frustration, "
        "sarcasm, an angry emoji or disputing a ban decision alone do not count. It still escalates only "
        "on intents with a medium or high default risk.",
        "Evidence: D08, D29 and D33 fit. D32 is the borderline case: no profanity or abuse, but the reviewer "
        "judged its hostility as strong anger, and that label stands. No "
        "dev item has anger on a low-risk intent, so dev gives no reason to lower the threshold.",
    ]),
    ("C4. The hardware repair trigger is explicit.", [
        "Escalate (ACCOUNT_SPECIFIC) when the customer asks for a repair, replacement, warranty or servicing, "
        "or says a repaired or replaced device still fails. Also escalate when first-line steps failed "
        "(C1). A bare 'it broke' with no request gets auto first-line steps and a question about the symptom.",
        "Evidence: D14, D18 and D40 are escalated. All three also have failed steps, so dev can't tell "
        "'on request' from 'after failed steps'. D34 ('my xone broke', no request) is labelled auto.",
    ]),
    ("C5. Account-specific handling is explicit.", [
        "`account_access_profile` and `entitlements_subscriptions_codes` escalate (ACCOUNT_SPECIFIC) when "
        "the fix needs someone to see or change this customer's own account, order, code or licence: "
        "sign-in failures on their account, linked accounts, a specific pre-order or code. General how-to "
        "or policy answers stay auto (GENERAL_INFO), and so does first-line entitlement troubleshooting.",
        "Evidence: D10, D37 and D39 (own account) and D05 (a specific pre-order) are escalated. D01, D13 and "
        "D36 are auto. No dev item is an account how-to question, so the auto side is untested.",
    ]),
    ("C6. The `prior_clarification` cue is defined.", [
        "It means the brand asked this customer for missing details earlier in the thread. Brand announcements, "
        "answers and troubleshooting steps don't count. It matters only for `needs_more_context`, and no "
        "decision changes on dev.",
    ]),
]
UNCHANGED = [
    "**`needs_more_context` after a clarification** still escalates (LOW_CONFIDENCE). No dev item was "
    "vague after a brand clarification: the 4 `after_clarification` picks all carried a clear issue in "
    "context. This rule is **untested**.",
    "**Low-confidence escalation** is a threshold on classifier confidence. It is set on dev in Phase 7, "
    "once the classifier exists.",
    "**OUT_OF_SCOPE** (third-party answers such as patch timelines) has no cue on the sheet and is untested.",
]
FINAL_POLICY = [
    "1. `risk_level` = the highest of the primary intent's default risk (`low` for states without an "
    "intent) and every risk rule that fires.",
    "2. Risk rules:",
    "   - `account_compromised` → high, SECURITY.",
    "   - `harm_or_legal` → high, SAFETY_LEGAL.",
    "   - `money_dispute` (charged twice or without consent, refund refused, money taken) → high, BILLING_DISPUTE.",
    "   - `repeat_contact` (already contacted support about this issue, or waited days) → medium. It does not escalate on its own.",
    "   - `steps_failed` (the standard first-line fix was already tried and the problem persists) → medium.",
    "   - `strong_anger` (profanity, insults or abuse aimed at Xbox or support, or a threat to leave) → medium.",
    "3. `escalate = yes` if any of these hold:",
    "   - a. `risk_level` is high;",
    "   - b. the intent is `purchases_billing_orders` or `support_process_complaint` (always);",
    "   - c. account or entitlements, and the fix needs this customer's own account, order, code or licence (ACCOUNT_SPECIFIC);",
    "   - d. hardware, and a repair, replacement, warranty or servicing is requested, or a repaired or replaced device still fails (ACCOUNT_SPECIFIC);",
    "   - e. `steps_failed` fires, on any intent (REPEAT_CONTACT if `repeat_contact` also fires, else STEPS_FAILED);",
    "   - f. `strong_anger` fires on an intent whose default risk is medium or high (HIGH_ANGER);",
    "   - g. `needs_more_context`, and the brand already asked this customer for clarification in the thread (LOW_CONFIDENCE; untested on dev);",
    "   - h. Phase 7: classifier confidence falls below a threshold set on dev (LOW_CONFIDENCE);",
    "   - i. system only: the drafted reply fails validation after its retries (REPLY_FAILED_CHECKS).",
    "4. `reason_code` when escalating is the first match in this order: SECURITY > SAFETY_LEGAL > "
    "BILLING_DISPUTE > ACCOUNT_SPECIFIC > REPEAT_CONTACT > STEPS_FAILED > HIGH_ANGER > OUT_OF_SCOPE > "
    "LOW_CONFIDENCE > REPLY_FAILED_CHECKS. When auto: ROUTINE_TROUBLESHOOTING for fix intents, GENERAL_INFO otherwise.",
]
BEFORE_AFTER = ["D26", "D35", "D02", "D01", "D14", "D34", "D10"]


# --- data -------------------------------------------------------------------------------------
def load_dev() -> pd.DataFrame:
    labels = pd.read_csv(GOLDEN / "dev_labeling_sheet.csv", dtype=str, keep_default_na=False)
    labels = labels.apply(lambda s: s.str.strip())
    key = pd.read_csv(GOLDEN / "dev_sample_key.csv", dtype=str)[["dev_id", "slice"]]
    pool = eval_pool()
    pool = pool.assign(record_id=pool["record_id"].astype(str))[
        ["record_id", "customer_text_clean", "reply_type", "brand_reply_clean", "customer_escalation_signals"]]
    dev = labels.merge(key, on="dev_id").merge(pool, on="record_id", how="left")
    assert len(dev) == 40 and dev["customer_text_clean"].notna().all()
    dev["cues"] = [{n: {"yes": True, "no": False}.get(r[f"cue_{n}"].lower()) for n in CUE_NAMES}
                   for r in dev.to_dict("records")]
    dev["label_esc"] = dev["escalate"] == "yes"
    dev["handoff"] = (dev["reply_type"] == "dm_deflection") | dev["brand_reply_clean"].str.contains(HANDOFF)
    dev["must"] = (dev["risk_level"] == "high") | dev["reason_code"].isin(MUST_ESCALATE_CODES)
    return dev


def apply(dev: pd.DataFrame, p: Policy) -> list[Decision]:
    return [decide(r["intent"] or None, r["cues"], p) for r in dev.to_dict("records")]


def label_issues(dev: pd.DataFrame) -> list[tuple[str, str]]:
    states = {s["name"] for s in SPEC["conversation_states"]}
    no_intent = set(SPEC["states_without_intent"])
    issues = []
    for r in dev.to_dict("records"):
        d, intent, code = r["dev_id"], r["intent"], r["reason_code"]
        if r["conversation_state"] not in states:
            issues.append((d, f"unknown state `{r['conversation_state']}`"))
        if (intent == "") != (r["conversation_state"] in no_intent):
            issues.append((d, "intent must be blank exactly for closing/social states"))
        if intent and intent not in DEFAULT_RISK:
            issues.append((d, f"unknown intent `{intent}`"))
        if code not in PRIORITY + AUTO_CODES:
            issues.append((d, f"unknown reason code `{code}`"))
        elif r["escalate"] not in ("yes", "no"):
            issues.append((d, f"escalate is `{r['escalate']}`"))
        elif r["label_esc"] != (code not in AUTO_CODES):
            kind = "an auto" if code in AUTO_CODES else "an escalation"
            issues.append((d, f"escalate = {r['escalate']}, but `{code}` is {kind} code"))
        if code == "REPLY_FAILED_CHECKS":
            issues.append((d, "`REPLY_FAILED_CHECKS` is system-only (the agent's own reply failed "
                              "validation); here it means the customer's steps failed → C1/C2"))
        blank = [f"cue_{n}" for n, v in r["cues"].items() if v is None]
        if blank:
            issues.append((d, f"blank cue: {', '.join(blank)} (read as no)"))
        for sec in [s.strip() for s in r["secondary_intents"].split(";") if s.strip()]:
            if sec not in DEFAULT_RISK:
                issues.append((d, f"unknown secondary intent `{sec}`"))
            elif sec == "support_process_complaint":
                issues.append((d, "secondary `support_process_complaint`: its exclude rule folds a complaint "
                                  "about a named issue into that issue (REPEAT_CONTACT / HIGH_ANGER rules), so "
                                  "it shouldn't be listed (unscored; no scored change)"))
            elif intent and RISK_ORDER[DEFAULT_RISK[sec]] > RISK_ORDER[DEFAULT_RISK[intent]]:
                issues.append((d, f"T0: secondary `{sec}` ({DEFAULT_RISK[sec]}) outranks primary `{intent}` "
                                  f"({DEFAULT_RISK[intent]}); swap them or drop the secondary"))
        expected = decide(intent or None, r["cues"], PROPOSED).risk
        if expected != r["risk_level"]:
            issues.append((d, f"risk `{r['risk_level']}`, but the intent and cues give `{expected}`"))
    return issues


# --- rendering -------------------------------------------------------------------------------
def short(text: str, limit: int = 120) -> str:
    text = " ".join(str(text).split()).replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def cues_str(cue: dict) -> str:
    fired = [CUE_SHORT[n] for n, v in cue.items() if v]
    return ", ".join(fired) or "–"


def fmt(d: Decision) -> str:
    head = f"**ESCALATE** `{d.reason}`" if d.escalate else f"auto `{d.reason}`"
    return head + (f" ({d.why})" if d.why else "")


def label_str(r: dict) -> str:
    return f"**{'ESCALATE' if r['label_esc'] else 'auto'}** `{r['reason_code']}`"


def pct(k: int, n: int) -> str:
    return f"{k}/{n} ({k / n:.0%})" if n else "–"


def scores(dev: pd.DataFrame, pred: list[bool]) -> list[str]:
    y, p = dev["label_esc"].to_numpy(), pd.Series(pred).to_numpy()
    must = dev["must"].to_numpy()
    tp = int((y & p).sum())
    return [pct(int((y == p).sum()), len(y)), pct(tp, int(p.sum())), pct(tp, int(y.sum())),
            pct(int((p & must).sum()), int(must.sum())), pct(int(p.sum()), len(p))]


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return out + ["| " + " | ".join(str(c) for c in row) + " |" for row in rows] + [""]


def render(dev: pd.DataFrame) -> str:
    draft, broad, prop = apply(dev, DRAFT), apply(dev, DRAFT_BROAD), apply(dev, PROPOSED)
    dev = dev.assign(draft=draft, prop=prop)
    recs = dev.to_dict("records")
    by_id = {r["dev_id"]: r for r in recs}
    L = ["# Escalation calibration on the dev set (40 items)", "",
         "_Generated by `uv run python scripts/calibrate_escalation.py`. Each policy is applied to the "
         "**labelled** state, intent and cues, so disagreements are about the policy, not about "
         "classification. Dev is for tuning only and is never reported as a result. The policy in §8 was "
         "approved and frozen on 2026-09-11._", ""]

    labelers = dev["labeler"].value_counts().to_dict() if "labeler" in dev else {}
    field = ", ".join(f"`{k}` × {v}" for k, v in labelers.items()) or "not in the sheet"
    L += [f"**Labeller field:** {field}.", "",
          "> **Provenance.** The dev labels are ChatGPT drafts (made with the codebook and the project context) "
          "that the project owner reviewed and approved item by item. They are not blind human labels. That is "
          "acceptable for dev, which only tunes the policy, but agreement with the draft is partly circular: the "
          "drafts applied the draft rules. §7 lists the fixes made after review. The golden set, which carries "
          "the headline numbers, should get a blind human first pass.", ""]

    # 1. overall agreement
    L += ["## 1. Overall agreement", "",
          f"The labels escalate {int(dev['label_esc'].sum())}/40 items. {int(dev['must'].sum())} are "
          "must-escalate (risk high, or reason SECURITY / SAFETY_LEGAL / BILLING_DISPUTE).", ""]
    L += table(["policy", "agreement", "escalate precision", "escalate recall", "must-escalate recall",
                "escalates"],
               [[DRAFT.name] + scores(dev, [d.escalate for d in draft]),
                [DRAFT_BROAD.name] + scores(dev, [d.escalate for d in broad]),
                ["**proposed**"] + scores(dev, [d.escalate for d in prop])])
    slice_rows = []
    for name, part in dev.groupby(dev["slice"].str.startswith("targeted").map({True: "targeted (24)", False: "random (16)"})):
        slice_rows.append([name] + [pct(int((part["label_esc"] == part[col].map(lambda d: d.escalate)).sum()), len(part))
                                    for col in ("draft", "prop")])
    L += table(["slice", "draft (literal) agreement", "proposed agreement"], slice_rows)
    reason_agree = sum(r["reason_code"] == r["prop"].reason for r in recs)
    L += [f"Reason codes (informational only): the proposed policy's code matches the label on "
          f"{pct(reason_agree, 40)} items.", "",
          "**How to read this.** 24 of the 40 items were targeted at hard cases, so these are not estimates of "
          "production rates. Dev is too small for CIs to separate the policies; what matters is *which* "
          "items disagree and why. The broad reading of the draft gives the proposed decisions, which is what "
          "C1 writes down.", ""]

    # 2/3. disagreements
    def disagreement(rows: list[dict]) -> list[str]:
        if not rows:
            return ["None.", ""]
        return table(["item", "slice", "message", "labelled state / intent", "cues", "draft", "label"],
                     [[r["dev_id"], r["slice"], short(r["customer_text_clean"]),
                       f"{r['conversation_state']} / `{r['intent'] or '–'}`", cues_str(r["cues"]),
                       fmt(r["draft"]), label_str(r) + f": {short(r['notes'], 90)}"] for r in rows])
    L += ["## 2. Draft AUTO vs labelled ESCALATE", ""]
    L += disagreement([r for r in recs if r["label_esc"] and not r["draft"].escalate])
    L += ["## 3. Draft ESCALATE vs labelled AUTO", ""]
    L += disagreement([r for r in recs if not r["label_esc"] and r["draft"].escalate])

    # 4. false-auto candidates
    L += ["## 4. False-auto candidates", "",
          "Items the **proposed** policy auto-handles that carry a warning sign: a label fixed after review, "
          "medium label confidence, a real brand reply that moved the case to DM, chat or phone, or a Phase 2 "
          "keyword signal. The real reply is a weak cross-check, not a target. XboxSupport asks for a DM to "
          "collect a gamertag even on routine issues.", ""]
    cand = []
    for r in recs:
        if r["prop"].escalate:
            continue
        flags = []
        if FIX_NOTE.search(r["notes"]):
            flags.append("label fixed after review")
        if r["label_confidence"] != "high":
            flags.append(f"label confidence {r['label_confidence']}")
        if r["handoff"]:
            flags.append("real reply hands off")
        if len(r["customer_escalation_signals"]):
            flags.append("signals: " + ", ".join(r["customer_escalation_signals"]))
        if flags:
            cand.append((r["dev_id"] not in NOTES, -len(flags), r, flags, NOTES.get(r["dev_id"], "")))
    L += table(["item", "message", "proposed", "warning signs", "note"],
               [[r["dev_id"], short(r["customer_text_clean"]), fmt(r["prop"]), "; ".join(f), n]
                for *_, r, f, n in sorted(cand, key=lambda c: c[:2])])
    both = pd.crosstab(pd.Series([d.escalate for d in prop], name="proposed escalates"),
                       dev["handoff"].rename("real reply hands off"))
    L += ["Weak cross-check, proposed decision vs whether the historical reply moved the case to DM, chat or phone:", ""]
    L += table(["", "real reply public", "real reply hands off"],
               [[f"proposed {'ESCALATE' if k else 'auto'}", int(both.loc[k].get(False, 0)), int(both.loc[k].get(True, 0))]
                for k in both.index])
    L += ["Real XboxSupport answered the angry enforcement messages (D08, D29, D32) with the public policy "
          "template, and asked for DMs on routine install and software issues (D20, D21). The historical agent "
          "is not a gold standard for escalation.", ""]

    # 5. proposed changes + evidence per behaviour
    L += ["## 5. Proposed policy changes", "",
          "The rule is to change the policy only where dev evidence disagrees. Only C1 changes a decision on dev. "
          "C2–C6 make the wording deterministic, so that labellers and the classifier can't read it two ways.", ""]
    for title, paras in CHANGES:
        L += [f"**{title}**", ""] + [f"- {p}" for p in paras] + [""]
    L += ["**Unchanged, and why:**", ""] + [f"- {u}" for u in UNCHANGED] + [""]
    L += ["**Evidence per calibration behaviour.** Each alternative is applied instead of the proposed rule, and "
          "the items whose decision would change are listed with their label.", ""]
    rows = []
    for behaviour, alt_text, alt in ALTERNATIVES:
        dec = apply(dev, alt)
        flips = [(r, d) for r, d in zip(recs, dec) if d.escalate != r["prop"].escalate]
        prop_right = sum(r["prop"].escalate == r["label_esc"] for r, _ in flips)
        items = ", ".join(f"{r['dev_id']} (label {'esc' if r['label_esc'] else 'auto'})" for r, _ in flips) or "none"
        verdict = ("no dev evidence either way" if not flips else
                   f"labels side with proposed on {prop_right}/{len(flips)}")
        rows.append([behaviour, alt_text, items, verdict])
    conf = dev["label_confidence"].value_counts().to_dict()
    rows.append(["low confidence", "Threshold on classifier confidence (Phase 7)",
                 f"label confidence: {', '.join(f'{k} {v}' for k, v in conf.items())}", "set in Phase 7"])
    L += table(["behaviour", "alternative tested", "items that would change", "verdict"], rows)

    # 6. before / after
    L += ["## 6. Before / after examples", ""]
    L += table(["item", "message", "cues", "draft (before)", "proposed (after)", "label"],
               [[d, short(by_id[d]["customer_text_clean"], 110), cues_str(by_id[d]["cues"]), fmt(by_id[d]["draft"]),
                 fmt(by_id[d]["prop"]), label_str(by_id[d])] for d in BEFORE_AFTER])
    L += ["D26 and D35 flip (C1). D02 keeps its decision and gets a clearer reason (C1/C2). D01 shows a repeat "
          "contact alone staying auto. D14 and D34 show the hardware trigger (C4), and D10 the account trigger "
          "(C5).", ""]

    # 7. label issues
    L += ["## 7. Label checks and fixes", "", "**Mechanical checks** against the codebook rules:", ""]
    L += [f"- **{d}**: {text}" for d, text in label_issues(dev)] or ["- None remain."]
    L += ["", "**Fixes applied after review** (2026-09-11; each is recorded in the item's `notes`). D27 and D31 "
          "are the assistant's reading, delegated by the reviewer. The rest make the labels consistent with the "
          "reviewer's own judgment and the frozen rules.", ""]
    for r in recs:
        L += [f"- **{r['dev_id']}**: {m.group(0)[1:-1].removeprefix('review fix 2026-09-11: ')}"
              for m in FIX_NOTE.finditer(r["notes"])]
    L += ["", f"- **D33** (assistant reading, not changed): {NOTES['D33']}", ""]

    # 8. final policy
    L += ["## 8. Final escalation policy (approved and frozen 2026-09-11)", ""] + FINAL_POLICY + [
          "", "It is written into `data/taxonomy/taxonomy_v1.yaml` (`escalation_status: frozen`) and the "
          "codebook, and `DECISIONS.md` records C1–C6. The 200-item golden set is sampled next, excluding the "
          "40 dev threads.", ""]

    # appendix
    L += ["## Appendix: every item", ""]
    L += table(["item", "slice", "state / intent", "cues", "label", "draft", "proposed", "real reply"],
               [[r["dev_id"], r["slice"].replace("targeted:", "t:"), f"{r['conversation_state']} / `{r['intent'] or '–'}`",
                 cues_str(r["cues"]), label_str(r), fmt(r["draft"]), fmt(r["prop"]),
                 f"{r['reply_type']}{' (hands off)' if r['handoff'] else ''}"] for r in recs])
    return "\n".join(L)


def main() -> None:
    dev = load_dev()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(dev), encoding="utf-8")
    draft, prop = apply(dev, DRAFT), apply(dev, PROPOSED)
    print(f"wrote {OUT.relative_to(ROOT)}: draft agrees on {sum(d.escalate == y for d, y in zip(draft, dev['label_esc']))}/40, "
          f"proposed on {sum(d.escalate == y for d, y in zip(prop, dev['label_esc']))}/40")


if __name__ == "__main__":
    main()
