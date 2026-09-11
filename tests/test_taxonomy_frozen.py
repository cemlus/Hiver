"""Taxonomy v1 and its escalation policy are frozen: renaming, adding or removing an intent, state
or risk rule has to be a deliberate, versioned change (new codebook version, relabelling). The
escalation policy was calibrated on the dev set before freezing."""
import yaml

from src.config import resolve

FROZEN_INTENTS = [
    "connectivity_xbox_live", "install_download_update", "hardware_devices", "software_game_app",
    "account_access_profile", "purchases_billing_orders", "entitlements_subscriptions_codes",
    "enforcement_safety", "product_info_feedback", "support_process_complaint", "needs_more_context",
]
FROZEN_STATES = ["new_issue", "issue_followup", "acknowledgement_closing", "social_offtopic"]


def spec():
    return yaml.safe_load(resolve("data/taxonomy/taxonomy_v1.yaml").read_text(encoding="utf-8"))


def test_intents_are_frozen():
    assert [it["name"] for it in spec()["intents"]] == FROZEN_INTENTS


def test_states_are_frozen():
    s = spec()
    assert [st["name"] for st in s["conversation_states"]] == FROZEN_STATES
    assert s["states_without_intent"] == ["acknowledgement_closing", "social_offtopic"]


def test_taxonomy_and_escalation_are_frozen():
    s = spec()
    assert s["taxonomy_status"] == "frozen"
    assert s["escalation_status"] == "frozen"


def test_escalation_rules_match_the_approved_policy():
    s = spec()
    assert [r[0] for r in s["risk_rules"]] == [
        "account_compromised", "harm_or_legal", "money_dispute", "repeat_contact", "steps_failed", "strong_anger"]
    codes = next(values for field, _, values in s["label_fields"] if field == "reason_code")
    assert "STEPS_FAILED" in codes and "REPLY_FAILED_CHECKS" in codes


def test_s1_open_issues_are_followups():
    rows = {msg: state for msg, state, _ in spec()["s1_examples"]}
    assert rows["Will try tonight"] == "issue_followup"
    assert rows["I'll get back to you"] == "issue_followup"
    assert rows["Thanks, it works now"] == "acknowledgement_closing"


def test_rendered_codebook_matches_the_spec():
    text = resolve("data/codebook.md").read_text(encoding="utf-8")
    assert "Taxonomy FROZEN" in text
    for name in FROZEN_INTENTS + FROZEN_STATES:
        assert f"### `{name}`" in text or f"| `{name}` |" in text, name
