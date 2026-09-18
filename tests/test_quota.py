"""Reading rate-limit errors: the daily budget and the per-minute one need different waits."""
from __future__ import annotations

import pytest

from src.eval.quota import DAILY, PER_MINUTE, classify, parse_wait

TPD = ("Rate limit reached for model `openai/gpt-oss-120b` ... Limit 200000, Used 197596, "
       "Requested 3972. Please try again in 11m17.376s.")
TPM = "Rate limit reached: tokens per minute (TPM). Please try again in 8.5s."


@pytest.mark.parametrize("text,seconds", [
    ("try again in 11m17.376s", 677.376),
    ("try again in 1h2m3s", 3723.0),
    ("try again in 8.5s", 8.5),
])
def test_parse_wait_reads_the_named_window(text, seconds):
    assert parse_wait(text) == pytest.approx(seconds)


def test_parse_wait_returns_none_when_no_window_is_named():
    assert parse_wait("some other failure") is None


def test_a_daily_limit_is_recognised_with_its_numbers():
    limit = classify("tokens per day (TPD): Limit 200000, Used 197596, Requested 3972. "
                     "Please try again in 11m17.376s.")
    assert limit.kind is DAILY
    assert limit.used == 197596 and limit.cap == 200000
    assert limit.wait_seconds == pytest.approx(697.376)


def test_a_per_minute_limit_waits_briefly():
    limit = classify(TPM)
    assert limit.kind is PER_MINUTE
    assert limit.wait_seconds == pytest.approx(13.5)


def test_a_long_daily_wait_is_capped_so_it_rechecks():
    limit = classify("tokens per day (TPD): Limit 200000, Used 199999, Requested 10. "
                     "Please try again in 5h.", max_wait=1800)
    assert limit.wait_seconds == pytest.approx(1820.0)


def test_an_unrelated_error_is_not_a_rate_limit():
    assert classify("connection reset by peer") is None
