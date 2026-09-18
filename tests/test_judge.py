"""The judge grades replies it did not write, on a rubric that stays in range.

No network: the LLM is a stub. The golden set must never be reachable from the calibration path.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import load_config
from src.contracts import RetrievedExample, SupportRequest
from src.eval.judge import (DIMENSIONS, RUBRIC, ReplyJudgement, judge_reply, rubric_markdown,
                            system_prompt, user_prompt)

ROOT = Path(__file__).resolve().parents[1]


def request(text: str = "my controller keeps drifting") -> SupportRequest:
    return SupportRequest(request_id="D01", brand="XboxSupport", customer_text=text)


def judgement(**kwargs) -> ReplyJudgement:
    base = {d: 4 for d in DIMENSIONS} | {"unsupported_claims": False,
                                         "escalation_appropriate": True}
    return ReplyJudgement(**(base | kwargs))


class FakeLLM:
    def __init__(self, result: ReplyJudgement) -> None:
        self.result = result
        self.model = "fake/judge"
        self.calls: list[dict] = []

    def complete(self, prompt, *, system=None, schema=None):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema})
        return self.result


def test_the_judge_is_not_the_production_agent():
    """A model must never grade its own replies."""
    cfg = load_config()
    assert cfg["models"]["judge"]["name"] != cfg["models"]["agent"]["name"]
    assert cfg["models"]["agent"]["name"] == "groq/qwen/qwen3.8-27b"
    assert cfg["models"]["judge"]["name"] == "groq/openai/gpt-oss-120b"


@pytest.mark.parametrize("score", [0, 6, -1])
def test_scores_outside_one_to_five_are_rejected(score):
    with pytest.raises(ValidationError):
        judgement(groundedness=score)


def test_every_dimension_has_a_full_set_of_anchors():
    for name in DIMENSIONS:
        assert sorted(RUBRIC[name]) == [1, 2, 3, 4, 5], name


def test_the_reference_is_marked_as_not_the_answer():
    text = user_prompt(request(), "try recalibrating", (), reference="Please DM us.")
    assert "REFERENCE, not gold" in text
    assert "Please DM us." in text
    assert "not the correct answer" in system_prompt()


def test_a_missing_reference_is_stated_rather_than_faked():
    assert "(no historical reply available)" in user_prompt(request(), "hi", (), reference="")


def test_the_scores_come_back_keyed_by_dimension():
    llm = FakeLLM(judgement(safety=5))
    result = judge_reply(request(), "try recalibrating", (), llm)
    assert result.scores() == {**{d: 4 for d in DIMENSIONS}, "safety": 5}


def test_the_evidence_reaches_the_judge():
    example = RetrievedExample(record_id="T7", customer_text="drift",
                               brand_reply="Recalibrate.", similarity=0.9)
    llm = FakeLLM(judgement())
    judge_reply(request(), "recalibrate it", (example,), llm)
    assert "T7" in llm.calls[0]["prompt"]


def test_the_human_rubric_matches_the_judge_rubric():
    """One source of truth: the rater and the judge must grade against identical anchors."""
    human = rubric_markdown()
    for name in DIMENSIONS:
        assert name in human
        for score in (1, 5):
            assert RUBRIC[name][score] in human


def test_the_calibration_scripts_never_load_golden():
    """Calibration is dev-only; the golden set must not be reachable from these scripts."""
    forbidden = re.compile(r"golden_final|golden_labeling_sheet|golden_sample_key")
    for name in ("probe_judge.py", "make_rating_sheet.py", "run_judge_calibration.py"):
        path = ROOT / "scripts" / name
        if not path.exists():
            continue
        offending = [line for line in path.read_text(encoding="utf-8").splitlines()
                     if forbidden.search(line)]
        assert not offending, f"{name} references the golden set: {offending}"
