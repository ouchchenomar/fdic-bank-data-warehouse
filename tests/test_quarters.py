import pytest

from fdic_dwh.quarters import quarter_range, quarter_to_repdte


def test_quarter_to_repdte():
    assert quarter_to_repdte("2025Q4") == "20251231"
    assert quarter_to_repdte("2026q2") == "20260630"


def test_range_crosses_year_end():
    assert quarter_range("2025Q1:2026Q2") == [
        "20250331", "20250630", "20250930", "20251231", "20260331", "20260630",
    ]


def test_single_quarter():
    assert quarter_range("2026Q3") == ["20260930"]


@pytest.mark.parametrize("bad", ["2025Q5", "2025-Q1", "Q1", "2026Q2:2025Q1"])
def test_invalid_quarters(bad):
    with pytest.raises(ValueError):
        quarter_range(bad)
