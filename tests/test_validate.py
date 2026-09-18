"""The reply validator rejects the genuinely unsupported, not the merely paraphrased.

Grounding rule: a claim is supported by the conversation and/or the retrieved evidence. Synthesis
across examples is allowed; verbatim reuse is never required.
"""
from __future__ import annotations

from src.contracts import RetrievedExample, SupportRequest, Turn
from src.core.validate import steps_mentioned, tried_steps, validate


def request(text: str, context: tuple[Turn, ...] = ()) -> SupportRequest:
    return SupportRequest(request_id="R1", brand="XboxSupport", customer_text=text, context=context)


def example(customer: str = "my console won't connect", reply: str = "Try a power cycle: hold the "
            "power button for 10 seconds, then plug it back in.") -> RetrievedExample:
    return RetrievedExample(record_id="T1", customer_text=customer, brand_reply=reply,
                            similarity=0.8)


def test_a_paraphrased_answer_is_grounded():
    """Synthesis is allowed: nothing here appears verbatim in the retrieved reply."""
    errors = validate("Hold the power button down for ten seconds and then reconnect the power.",
                      request("console won't connect"), (example(),))
    assert errors == ()


def test_empty_draft_is_rejected():
    assert validate("", request("help")) == ("the draft is empty",)


def test_over_length_is_rejected():
    errors = validate("x" * 281, request("help"), (example(),), max_chars=280)
    assert any("281 characters" in e for e in errors)


def test_invented_link_is_rejected():
    errors = validate("See https://xbox.example/fix-it for the steps.", request("help"), (example(),))
    assert any("unsupported link" in e for e in errors)


def test_a_link_present_in_the_evidence_is_allowed():
    evidence = example(reply="Full steps are at https://support.xbox.com/help")
    errors = validate("The steps are at https://support.xbox.com/help", request("help"), (evidence,))
    assert errors == ()


def test_the_url_placeholder_is_rejected():
    """Regression: the corpus redacts links to a literal <URL>, and drafts copied it through.

    The placeholder is in the retrieved evidence too, so a support check calls it grounded. It
    reaches the customer as a broken link, so it is rejected flatly.
    """
    errors = validate("Try these steps: <URL>. That usually clears it.",
                      request("console keeps shutting down"), (example(),))
    assert any("broken link" in e for e in errors)


def test_the_url_placeholder_is_rejected_whatever_its_casing():
    for text in ("see <url> for help", "see < URL > for help"):
        errors = validate(text, request("help"), (example(),))
        assert any("broken link" in e for e in errors), text


def test_the_placeholder_in_the_evidence_alone_is_fine():
    """Only the draft is customer-facing; evidence may carry the placeholder.

    The evidence must actually support the drafted step, or M4's support check fires for an
    unrelated reason and this test stops testing the placeholder rule at all. It passed before M4
    only because the old rule merely asked whether retrieval had returned anything.
    """
    evidence = example(reply="Recalibrate it in Settings. Full guide here: <URL>")
    errors = validate("Recalibrate the controller in Settings.", request("stick drift"), (evidence,))
    assert not any("broken link" in e for e in errors), "a placeholder in the evidence is not a defect"
    assert errors == ()


def test_invented_refund_amount_is_rejected():
    errors = validate("We can refund you $49.99 for that order.", request("I want my money back"),
                      (example(),))
    assert any("unsupported amount" in e for e in errors)


def test_bare_dm_deflection_is_rejected():
    errors = validate("Sorry about that! Please DM us so we can help.", request("it won't turn on"),
                      (example(),))
    assert any("DM deflection" in e for e in errors)


def test_a_dm_ask_with_real_guidance_is_allowed():
    errors = validate("Try holding the power button for 10 seconds. If it still fails, DM us.",
                      request("it won't turn on"), (example(),))
    assert errors == ()


def test_repeating_a_step_the_customer_tried_is_rejected():
    errors = validate("Please restart your console and see if that helps.",
                      request("I already tried a restart and it didn't work"), (example(),))
    assert any("already reported trying" in e for e in errors)


def test_troubleshooting_with_no_evidence_is_rejected():
    errors = validate("Try a factory reset.", request("it won't turn on"), ())
    assert any("unsupported troubleshooting" in e for e in errors)


def test_tried_steps_needs_an_explicit_statement():
    assert tried_steps(request("my console needs a restart")) == set()
    assert "restart" in tried_steps(request("I tried a restart already"))


# --- M4: support is tested against the evidence, not against "did retrieval return anything" ---

def test_troubleshooting_unsupported_by_the_evidence_is_rejected():
    """Retrieval returning something is not the same as that something supporting the steps."""
    evidence = example(customer="billing question", reply="Check your order history online.")
    errors = validate("Try a factory reset of your console.", request("it keeps crashing"),
                      (evidence,))
    assert any("unsupported troubleshooting" in e for e in errors)
    assert any("factory reset" in e for e in errors)


def test_troubleshooting_supported_by_the_evidence_passes():
    errors = validate("A power cycle usually clears that.", request("it keeps crashing"),
                      (example(reply="Try a power cycle: hold the power button for 10 seconds."),))
    assert errors == ()


def test_troubleshooting_supported_by_the_conversation_alone_passes():
    """The grounding rule allows conversation OR evidence."""
    errors = validate("Reinstalling usually fixes that one.",
                      request("do I need reinstalling it again?"),
                      (example(reply="Have a look at the guide."),))
    assert errors == ()


def test_partial_support_is_tolerated_because_synthesis_is_allowed():
    """One supported step is enough; drafts may combine evidence rather than copy one reply."""
    errors = validate("Power cycle the console, then reconnect it.", request("it keeps crashing"),
                      (example(reply="Try a power cycle: hold the power button for 10 seconds."),))
    assert errors == ()


# --- M5: a DM ask cannot be excused by the word "check" ---

def test_dm_ask_with_only_check_your_messages_is_still_a_deflection():
    """The old rule accepted this because its guidance regex matched "check"."""
    errors = validate("Please DM us and check your messages.", request("it won't turn on"),
                      (example(),))
    assert any("DM deflection" in e for e in errors)


def test_dm_ask_with_a_real_step_outside_the_dm_clause_is_allowed():
    errors = validate("Try a power cycle first. If it still fails, DM us your gamertag.",
                      request("it won't turn on"), (example(),))
    assert errors == ()


def test_a_step_named_only_inside_the_dm_clause_does_not_rescue_it():
    errors = validate("DM us so we can restart the process for you.", request("it won't turn on"),
                      (example(),))
    assert any("DM deflection" in e for e in errors)


def test_steps_mentioned_finds_canonical_actions_only():
    assert steps_mentioned("try a power cycle and then sign in") == {"power cycle", "sign in"}
    assert steps_mentioned("please check your messages") == set()
