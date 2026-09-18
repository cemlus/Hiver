"""The reply validator rejects the genuinely unsupported, not the merely paraphrased.

Grounding rule: a claim is supported by the conversation and/or the retrieved evidence. Synthesis
across examples is allowed; verbatim reuse is never required.
"""
from __future__ import annotations

from src.contracts import RetrievedExample, SupportRequest, Turn
from src.core.validate import tried_steps, validate


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
    """Only the draft is customer-facing; evidence may carry the placeholder."""
    evidence = example(reply="Follow the guide here: <URL>")
    errors = validate("Recalibrate the controller in Settings.", request("stick drift"), (evidence,))
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
