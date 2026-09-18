"""Agreement maths, checked against values computed by hand.

Ordinal ratings: 5-vs-4 is a near miss, 5-vs-1 is a real disagreement, and quadratic weighting is
what encodes that. Plain kappa would treat them identically.
"""
from __future__ import annotations

import math

from src.eval.agreement import agreement_table, score_agreement, weighted_kappa


def test_perfect_agreement():
    r = score_agreement("groundedness", [1, 2, 3, 4, 5], [1, 2, 3, 4, 5], n_boot=200)
    assert r.weighted_kappa == 1.0
    assert r.exact == 1.0 and r.within_one == 1.0
    assert r.bias == 0.0


def test_within_one_is_looser_than_exact():
    r = score_agreement("helpfulness", [3, 3, 3, 3], [4, 4, 2, 3], n_boot=200)
    assert r.exact == 0.25          # only the last matches exactly
    assert r.within_one == 1.0      # all are within one point


def test_bias_shows_a_generous_judge():
    r = score_agreement("safety", [2, 2, 2, 2], [4, 4, 4, 4], n_boot=200)
    assert r.bias == 2.0
    assert r.human_mean == 2.0 and r.judge_mean == 4.0


def test_kappa_is_undefined_when_one_side_never_varies():
    """A judge that says 4 every time cannot be chance-corrected; report nan, never 0."""
    assert math.isnan(weighted_kappa([4, 4, 4, 4], [3, 4, 5, 4]))
    r = score_agreement("conciseness", [4, 4, 4, 4], [3, 4, 5, 4], n_boot=200)
    assert math.isnan(r.weighted_kappa)


def test_quadratic_weighting_punishes_distant_disagreement_more():
    near = score_agreement("d", [1, 2, 4, 5, 3, 1], [2, 3, 5, 4, 3, 1], n_boot=200)
    far = score_agreement("d", [1, 2, 4, 5, 3, 1], [5, 4, 1, 1, 3, 5], n_boot=200)
    assert near.weighted_kappa > far.weighted_kappa


def test_mismatched_lengths_are_an_error():
    try:
        score_agreement("d", [1, 2], [1], n_boot=10)
    except ValueError as error:
        assert "human ratings" in str(error)
    else:
        raise AssertionError("expected a ValueError")


def test_the_table_reports_the_interval_and_the_bias():
    rows = [score_agreement("groundedness", [1, 2, 3, 4, 5], [1, 2, 3, 4, 4], n_boot=200)]
    table = "\n".join(agreement_table(rows))
    assert "weighted κ" in table and "bias (judge−human)" in table
    assert "`groundedness`" in table
