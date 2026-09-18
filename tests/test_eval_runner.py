"""The evaluation runner cannot silently omit the agent, score altered gold, or clobber a report.

Each test pins one audit finding: H1 (agent omitted from the default systems), H3 (golden.lock
recorded but never verified), H2 (a --limit smoke run overwriting the authoritative report).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_routing_eval.py"
SOURCE = SCRIPT.read_text(encoding="utf-8")


def eval_runner_parser():
    """The runner's real argparse parser, without executing main()."""
    import argparse
    import importlib.util

    spec = importlib.util.spec_from_file_location("_run_routing_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captured = {}
    original = argparse.ArgumentParser.parse_args

    def capture(self, *a, **kw):
        captured["parser"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = capture
    try:
        module.main()
    except SystemExit:
        pass
    finally:
        argparse.ArgumentParser.parse_args = original
    assert "parser" in captured, "could not capture the runner's parser"
    return captured["parser"]


def test_the_agent_is_in_the_default_system_list():
    """H1: the default once expanded to BASELINES only, silently dropping the system under test.

    Asserted against the parser's real default rather than the source text: a regex over the
    argument line is brittle (the first version stopped at the comma inside `",".join(...)`) and
    would pass or fail for reasons unrelated to behaviour.
    """
    from src.eval.baselines import BASELINES

    assert "agent" not in BASELINES, "guard assumes agent is not a baseline"
    parser = eval_runner_parser()
    default = parser.get_default("systems")
    assert default is not None, "--systems has no default"
    systems = [s for s in default.split(",") if s]
    assert "agent" in systems, f"the agent must be evaluated by default; got {systems}"
    assert set(BASELINES) <= set(systems), "every baseline must still be scored by default"


def test_the_runner_verifies_the_golden_lock():
    """H3: the digest was written into the manifest but never compared against the sheet."""
    assert "def require_golden_lock" in SOURCE
    assert "require_golden_lock()" in SOURCE
    assert "does not match" in SOURCE


def test_the_lock_currently_matches_the_sheet():
    sheet = ROOT / "data" / "golden" / "golden_labeling_sheet.csv"
    lock = ROOT / "data" / "golden" / "golden.lock"
    assert hashlib.sha256(sheet.read_bytes()).hexdigest() == lock.read_text().split()[0]


def test_a_limited_run_writes_to_its_own_filenames():
    """H2: a 2-item smoke run once replaced the committed 200-item table."""
    assert "routing_baselines_smoke" in SOURCE
    assert '(OUT / report_name)' in SOURCE and '(OUT / manifest_name)' in SOURCE
    assert '(OUT / "routing_baselines.md").write_text' not in SOURCE


def test_a_limited_run_does_not_touch_the_authoritative_predictions():
    """Isolating only the report filenames still let --limit clobber predictions/*.jsonl.

    It actually happened: a --limit 4 verification run overwrote all eight committed prediction
    files, agent.jsonl included, and every test still passed.
    """
    assert "predictions_smoke" in SOURCE, "smoke runs need their own predictions directory"
    assert '(OUT / "predictions" / f"{name}.jsonl")' not in SOURCE, \
        "predictions are written to a fixed path regardless of --limit"
    assert "(predictions_dir / f\"{name}.jsonl\")" in SOURCE


def test_the_committed_predictions_are_full_length():
    """A truncated prediction file means a smoke run reached an authoritative artifact."""
    predictions = sorted((ROOT / "results" / "eval" / "predictions").glob("*.jsonl"))
    assert predictions, "no prediction files found"
    for path in predictions:
        lines = sum(1 for _ in path.open(encoding="utf-8"))
        assert lines == 200, f"{path.name} has {lines} rows, expected the full golden set"


@pytest.mark.parametrize("limit,expected", [(0, "routing_baselines.md"), (2, "routing_baselines_smoke2.md")])
def test_the_report_name_depends_on_the_limit(limit, expected):
    name = f"routing_baselines_smoke{limit}.md" if limit else "routing_baselines.md"
    assert name == expected


def test_the_runner_does_not_sleep_through_cached_replays():
    """A cached replay makes no request; pacing it would make offline reproduction take hours.

    The runner inherits --sleep 32, so an ungated sleep turned a 200-item offline replay into
    ~1.8 hours of idling and made the documented "<15 minute" reproduction claim false.
    """
    import time as _time

    from src.contracts import GoldenExample, SupportRequest
    from src.core.classify import RoutingProposal
    from src.eval.agent_runner import run_agent

    class CachedLLM:
        model = "fake/model"
        last_usage = None                      # None == served from cache

        def complete(self, prompt, *, system=None, schema=None):
            return RoutingProposal(conversation_state="new_issue", intent="hardware_devices",
                                   confidence=0.95, rationale="t")

    examples = [GoldenExample(request=SupportRequest(request_id=f"G{i}", brand="XboxSupport",
                                                     customer_text="my controller drifts"),
                              label_conversation_state="new_issue",
                              label_intent="hardware_devices")
                for i in range(3)]
    started = _time.time()
    run = run_agent(examples, CachedLLM(), confidence_threshold=0.0, sleep=2.0)
    elapsed = _time.time() - started
    assert len(run.outputs) == 3
    assert elapsed < 1.0, f"slept through cached replays: {elapsed:.1f}s for 3 cached items"
