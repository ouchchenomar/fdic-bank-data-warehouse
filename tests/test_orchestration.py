from datetime import date

import pytest

from fdic_dwh.orchestration import ended_since, plan_quarters, quarter_after

LOADED = ["20250331", "20250630", "20250930", "20251231", "20260331", "20260630"]


def test_quarter_after_wraps_the_year():
    assert quarter_after("20260630") == "20260930"
    assert quarter_after("20261231") == "20270331"


def test_only_quarters_already_ended_are_probed():
    assert ended_since("20260630", date(2026, 9, 30)) == []
    assert ended_since("20260630", date(2026, 11, 12)) == ["20260930"]
    assert ended_since("20260630", date(2027, 2, 1)) == ["20260930", "20261231"]


def test_daily_run_probes_the_next_quarter_only():
    assert plan_quarters(LOADED, date(2026, 11, 12), include_window=False) == ["20260930"]


def test_weekly_run_adds_the_revision_window():
    assert plan_quarters(LOADED, date(2026, 11, 12), include_window=True) == [
        "20250930", "20251231", "20260331", "20260630", "20260930",
    ]


def test_up_to_date_warehouse_has_nothing_to_probe():
    assert plan_quarters([*LOADED, "20260930"], date(2026, 12, 15), include_window=False) == []


def test_requested_quarters_replace_the_plan():
    assert plan_quarters(LOADED, date(2026, 11, 12), include_window=True,
                         requested="2026Q2") == ["20260630"]


def test_first_load_needs_explicit_quarters():
    with pytest.raises(ValueError, match="explicit quarters"):
        plan_quarters([], date(2026, 11, 12), include_window=True)
    assert plan_quarters([], date(2026, 11, 12), include_window=True,
                         requested="2025Q1:2025Q2") == ["20250331", "20250630"]
