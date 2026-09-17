"""The drafting step asks for a grounded reply and passes rejection reasons into the revise pass.

No network: the LLM is a stub returning a canned ReplyDraft.
"""
from __future__ import annotations

from src.contracts import RetrievedExample, SupportRequest
from src.core.draft import ReplyDraft, draft, system_prompt, user_prompt


class FakeLLM:
    def __init__(self, *drafts: ReplyDraft) -> None:
        self.drafts = list(drafts)
        self.model = "fake/model"
        self.calls: list[dict] = []

    def complete(self, prompt, *, system=None, schema=None):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema})
        return self.drafts.pop(0)


def request(text: str = "my controller keeps drifting") -> SupportRequest:
    return SupportRequest(request_id="R1", brand="XboxSupport", customer_text=text)


def example() -> RetrievedExample:
    return RetrievedExample(record_id="T7", customer_text="stick drift",
                            brand_reply="Recalibrate in Settings.", similarity=0.9)


def test_the_draft_and_its_citations_come_back():
    llm = FakeLLM(ReplyDraft(reply="  Try recalibrating in Settings.  ", supported_by=["T7"]))
    text, cited = draft(request(), (example(),), llm)
    assert text == "Try recalibrating in Settings."
    assert cited == ("T7",)


def test_the_evidence_is_put_in_front_of_the_model():
    llm = FakeLLM(ReplyDraft(reply="ok"))
    draft(request(), (example(),), llm)
    prompt = llm.calls[0]["prompt"]
    assert "T7" in prompt and "Recalibrate in Settings." in prompt


def test_the_revise_pass_names_what_failed():
    llm = FakeLLM(ReplyDraft(reply="ok"))
    draft(request(), (example(),), llm, errors=("unsupported link: https://nope.example",))
    prompt = llm.calls[0]["prompt"]
    assert "previous draft was rejected" in prompt
    assert "https://nope.example" in prompt


def test_the_system_prompt_never_asks_the_model_to_escalate():
    text = system_prompt().lower()
    assert "do not decide whether a case goes to a human" in text
    assert "escalate?" not in text


def test_missing_evidence_is_stated_rather_than_faked():
    assert "(no similar past exchanges were found)" in user_prompt(request(), ())
