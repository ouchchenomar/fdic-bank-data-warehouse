from fdic_dwh.cli import EXIT_NOT_PUBLISHED, _exit_code
from fdic_dwh.pipeline import Outcome


def outcome(status, announced=100):
    return Outcome("b", "financials", "20260930", status, announced, announced, 0, None, None,
                   None)


def test_success_and_duplicates_exit_zero():
    assert _exit_code([outcome("loaded"), outcome("duplicate")]) == 0


def test_quarter_not_published_yet_is_not_an_error():
    assert _exit_code([outcome("duplicate"), outcome("failed", announced=0)]) == EXIT_NOT_PUBLISHED


def test_any_real_failure_wins():
    assert _exit_code([outcome("failed", announced=0), outcome("failed", announced=4313)]) == 1
