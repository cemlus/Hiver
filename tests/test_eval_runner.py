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
