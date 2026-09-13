"""Record the adjudication of every human-vs-Gemma disagreement on the golden set (label layer 3).

Run from the repo root:
    uv run python scripts/adjudicate_golden.py            # fill data/golden/golden_adjudication.csv
    uv run python scripts/compare_golden_labels.py --finalize   # then generate golden_final.csv

Each decision below was made by reading the customer message and its context against the frozen
codebook (`data/codebook.md`), not by preferring either labeller. Neither original label is
changed: the human and Gemma values stay in the log beside the final one.

G064, G079 and G179 are the project owner's recorded human-vs-policy divergences on refund how-tos.
They keep the human label deliberately: the point is to measure the policy's over-escalation, so
"correcting" them to match the policy would erase the finding.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ADJUDICATION = ROOT / "data" / "golden" / "golden_adjudication.csv"
CODEBOOK = "assistant (codebook v1)"
OWNER = "project owner (recorded policy divergence)"

# (golden_id, field) -> (final label, decided_by, rationale)
DECISIONS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("G004", "intent"): ("account_access_profile", CODEBOOK, "support_process_complaint excludes complaints that name a concrete issue; the hacked account is the issue and the missed callbacks are a repeat-contact cue"),
    ("G009", "escalate"): ("no", CODEBOOK, "enforcement is auto with the policy template; no safety or legal cue, and Gemma's own reason cites GENERAL_INFO, an auto code"),
    ("G017", "intent"): ("hardware_devices", CODEBOOK, "names a concrete headset/controller fault; the jab at responsiveness is not a complaint about a prior contact"),
    ("G017", "escalate"): ("no", CODEBOOK, "hardware auto: no repair request and no failed steps"),
    ("G018", "intent"): ("connectivity_xbox_live", CODEBOOK, "the concrete issue is a connection error code; the support complaint is a risk cue, not the intent"),
    ("G018", "escalate"): ("no", CODEBOOK, "repeat contact alone does not escalate, and strong_anger fires only on medium/high-risk intents while connectivity is low"),
    ("G021", "intent"): ("entitlements_subscriptions_codes", CODEBOOK, "the console cannot confirm ownership of the title, which is a licence check rather than an app bug (close call)"),
    ("G021", "escalate"): ("no", CODEBOOK, "no specific lookup requested and no failed steps; first-line entitlement steps still apply"),
    ("G023", "conversation_state"): ("social_offtopic", CODEBOOK, "Portuguese banter aimed at another customer; no support request of their own"),
    ("G023", "intent"): ("", CODEBOOK, "states without an intent leave it blank"),
    ("G023", "escalate"): ("no", CODEBOOK, "no support request and no risk cue"),
    ("G025", "escalate"): ("no", CODEBOOK, "adds a symptom mid-troubleshooting; no repair request and no stated failure"),
    ("G026", "intent"): ("product_info_feedback", CODEBOOK, "the request is an information question about an update; the support jab does not make it a process complaint"),
    ("G026", "escalate"): ("no", CODEBOOK, "product_info is auto (GENERAL_INFO)"),
    ("G028", "conversation_state"): ("issue_followup", CODEBOOK, "continues the mic case already raised in this thread"),
    ("G029", "intent"): ("product_info_feedback", CODEBOOK, "a negative opinion on the product with no help requested (S2)"),
    ("G029", "escalate"): ("no", CODEBOOK, "profanity and a competitor threat fire strong_anger, but product_info is low risk so the rule does not escalate"),
    ("G030", "intent"): ("account_access_profile", CODEBOOK, "voice/text privacy settings are profile data (T7)"),
    ("G030", "escalate"): ("no", CODEBOOK, "answerable as a how-to with the settings guide; no account-specific action requested"),
    ("G031", "intent"): ("purchases_billing_orders", CODEBOOK, "the refund transaction itself is the problem, which T5 assigns to purchases"),
    ("G033", "intent"): ("install_download_update", CODEBOOK, "slow downloads belong to install_download_update; connectivity covers reaching Live"),
    ("G037", "conversation_state"): ("new_issue", CODEBOOK, "console freezing was not raised earlier in this thread"),
    ("G037", "escalate"): ("no", CODEBOOK, "hardware auto: no repair request and no stated failure"),
    ("G045", "conversation_state"): ("issue_followup", CODEBOOK, "continues the Gold issue this customer raised earlier in the thread"),
    ("G045", "escalate"): ("yes", CODEBOOK, "Gold removed from their own account needs an account-specific lookup"),
    ("G052", "intent"): ("product_info_feedback", CODEBOOK, "a pricing question with no failed transaction, which the purchases exclude sends to product_info"),
    ("G052", "escalate"): ("no", CODEBOOK, "product_info is auto"),
    ("G064", "escalate"): ("no", OWNER, "human-vs-policy divergence kept: a refund how-to is answerable, with escalation if it repeats or becomes a dispute"),
    ("G065", "intent"): ("entitlements_subscriptions_codes", CODEBOOK, "owned 360 titles will not download, which is a licence/entitlement problem (close call with install)"),
    ("G065", "escalate"): ("yes", CODEBOOK, "the customer states their own attempts failed, so steps_failed fires"),
    ("G066", "escalate"): ("no", CODEBOOK, "a regional availability question; product_info is auto"),
    ("G067", "conversation_state"): ("social_offtopic", CODEBOOK, "advice to another customer, with no support request and no issue of their own to close"),
    ("G075", "escalate"): ("no", CODEBOOK, "first-line entitlement steps have not been tried; hand off only if the reward is still missing"),
    ("G079", "escalate"): ("no", OWNER, "human-vs-policy divergence kept: explain the refund rules first"),
    ("G082", "escalate"): ("no", CODEBOOK, "the redemption guide is the first-line step and no lookup has been requested yet"),
    ("G084", "intent"): ("enforcement_safety", CODEBOOK, "the thread's issue is players cheating on leaderboards, which enforcement_safety covers"),
    ("G087", "escalate"): ("yes", CODEBOOK, "changing their own account's adult status needs account-specific action"),
    ("G090", "escalate"): ("no", CODEBOOK, "answers the brand's clarifying questions; no failed steps stated"),
    ("G095", "conversation_state"): ("issue_followup", CODEBOOK, "the issue is only partly fixed and details are still being supplied, so S1 does not allow closing"),
    ("G095", "intent"): ("software_game_app", CODEBOOK, "the thread's issue is the gamertag search feature"),
    ("G105", "intent"): ("account_access_profile", CODEBOOK, "repeated sign-outs from their own account; no entitlement is missing"),
    ("G106", "intent"): ("account_access_profile", CODEBOOK, "the hacked account is the concrete issue and the daily contacts are a repeat-contact cue"),
    ("G110", "intent"): ("account_access_profile", CODEBOOK, "a gamerpic is profile data (T7), not an app bug"),
    ("G110", "escalate"): ("no", CODEBOOK, "answerable with the custom-gamerpic requirements; no account action requested"),
    ("G113", "intent"): ("entitlements_subscriptions_codes", CODEBOOK, "prepaid balance not recognised is an entitlement problem; 'no one can help' is a cue, not the intent"),
    ("G116", "intent"): ("software_game_app", CODEBOOK, "the Guide not showing the playing track is a dashboard/app problem"),
    ("G117", "conversation_state"): ("issue_followup", CODEBOOK, "continues the menu problem this customer raised earlier in the thread"),
    ("G117", "escalate"): ("yes", CODEBOOK, "'is it fixable?' asks about repair, which escalates hardware"),
    ("G119", "intent"): ("purchases_billing_orders", CODEBOOK, "a snapped game disc with a rebuy dispute is purchases (T11), not a faulty device"),
    ("G121", "escalate"): ("yes", CODEBOOK, "the customer states the standard troubleshooting already failed: steps_failed"),
    ("G122", "escalate"): ("yes", CODEBOOK, "game sharing across their accounts needs a licence/home-Xbox lookup"),
    ("G125", "conversation_state"): ("issue_followup", CODEBOOK, "continues the ban question this customer raised earlier in the thread"),
    ("G127", "escalate"): ("yes", CODEBOOK, "a hate-speech report plus the threat to take it further triggers SAFETY_LEGAL"),
    ("G130", "intent"): ("software_game_app", CODEBOOK, "reports a green screen failure, so T10 sends it to the issue intent rather than the roadmap question"),
    ("G131", "intent"): ("product_info_feedback", CODEBOOK, "the message is a negative opinion on the dashboard UI, not the earlier code problem"),
    ("G131", "escalate"): ("no", CODEBOOK, "product_info is auto and no risk cue fires"),
    ("G132", "conversation_state"): ("issue_followup", CODEBOOK, "continues the ban this customer described earlier in the thread"),
    ("G134", "intent"): ("hardware_devices", CODEBOOK, "an audible controller is a device symptom, not a product-information question"),
    ("G137", "intent"): ("software_game_app", CODEBOOK, "games fail to launch while the console is otherwise online (T3)"),
    ("G140", "escalate"): ("no", CODEBOOK, "enforcement is auto with the policy template; support cannot act on enforcement"),
    ("G143", "escalate"): ("no", CODEBOOK, "enforcement stays auto by policy even when an account check is requested"),
    ("G145", "intent"): ("purchases_billing_orders", CODEBOOK, "the refund demand is the concrete issue; the phone-support complaint is a cue"),
    ("G146", "intent"): ("connectivity_xbox_live", CODEBOOK, "the server outage is the concrete issue named"),
    ("G146", "escalate"): ("no", CODEBOOK, "connectivity auto; no failed steps stated"),
    ("G147", "conversation_state"): ("issue_followup", CODEBOOK, "continues the mic setup this customer was working through in the thread"),
    ("G147", "intent"): ("software_game_app", CODEBOOK, "the thread states the issue, so T12 forbids needs_more_context"),
    ("G147", "escalate"): ("yes", CODEBOOK, "'i've done that' states the advised steps failed"),
    ("G151", "conversation_state"): ("issue_followup", CODEBOOK, "same thread and same code; the customer is still waiting on the earlier item"),
    ("G151", "intent"): ("product_info_feedback", CODEBOOK, "asks whether a code is transferable, which is a policy question"),
    ("G151", "escalate"): ("no", CODEBOOK, "a policy answer with no lookup required"),
    ("G152", "conversation_state"): ("acknowledgement_closing", CODEBOOK, "the customer reports the bug resolved itself after clearing the cache and nothing is pending"),
    ("G152", "intent"): ("", CODEBOOK, "closing states carry no intent"),
    ("G161", "intent"): ("software_game_app", CODEBOOK, "OneGuide cannot find a TV provider while the console is online, so it is an app problem"),
    ("G161", "escalate"): ("yes", CODEBOOK, "'i've reset everything' states the steps already failed"),
    ("G162", "escalate"): ("no", CODEBOOK, "support cannot reassign another person's gamertag; this is a policy answer"),
    ("G167", "intent"): ("account_access_profile", CODEBOOK, "child-account and family settings are account_access_profile"),
    ("G169", "conversation_state"): ("new_issue", CODEBOOK, "a reply to a brand announcement is a new contact"),
    ("G169", "intent"): ("needs_more_context", CODEBOOK, "'if my Xbox worked' gives no symptom to act on, so one clarifying question is due"),
    ("G179", "escalate"): ("no", OWNER, "human-vs-policy divergence kept: first-line purchase help before handing off"),
    ("G180", "escalate"): ("no", CODEBOOK, "answers the brand's question about the power setup; no failed step stated"),
    ("G181", "conversation_state"): ("issue_followup", CODEBOOK, "responds to the brand about the same Kinect feature"),
    ("G185", "conversation_state"): ("issue_followup", CODEBOOK, "engages with the diagnosis of the console fault raised earlier in the thread"),
    ("G185", "intent"): ("hardware_devices", CODEBOOK, "the thread's issue is the failing console"),
    ("G192", "conversation_state"): ("issue_followup", CODEBOOK, "reports back on the suggestion inside their own thread"),
    ("G197", "conversation_state"): ("issue_followup", CODEBOOK, "a further error code for the console fault raised earlier in the thread"),
    ("G198", "conversation_state"): ("issue_followup", CODEBOOK, "adds detail to the overheating issue raised earlier in the thread"),
}


def main() -> None:
    adj = pd.read_csv(ADJUDICATION, dtype=str, keep_default_na=False)
    rows = {(r["golden_id"], r["field"]) for r in adj.to_dict("records")}
    missing = rows - set(DECISIONS)
    extra = set(DECISIONS) - rows
    if missing or extra:
        sys.exit(f"decisions do not match the log: {len(missing)} undecided {sorted(missing)[:5]}, "
                 f"{len(extra)} stale {sorted(extra)[:5]}")

    outcomes = {"human": 0, "llm": 0, "new": 0}
    for i, r in adj.iterrows():
        final, by, why = DECISIONS[(r["golden_id"], r["field"])]
        adj.at[i, "final"] = final
        adj.at[i, "decided_by"] = by
        adj.at[i, "rationale"] = why
        if final == r["human"].strip():
            outcomes["human"] += 1
        elif final == r["llm"].strip():
            outcomes["llm"] += 1
        else:
            outcomes["new"] += 1
    adj.to_csv(ADJUDICATION, index=False)
    print(f"resolved {len(adj)} disagreements over {adj.golden_id.nunique()} items")
    print(f"  in favour of the human label: {outcomes['human']}")
    print(f"  in favour of Gemma:           {outcomes['llm']}")
    print(f"  a third, new label:           {outcomes['new']}")
    print(adj.groupby("field").apply(
        lambda g: pd.Series({"human": int((g.final == g.human.str.strip()).sum()),
                             "llm": int((g.final == g.llm.str.strip()).sum())}),
        include_groups=False).to_string())


if __name__ == "__main__":
    main()
