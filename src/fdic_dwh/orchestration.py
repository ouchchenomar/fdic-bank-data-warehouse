"""Which quarters a scheduled run should extract. Pure functions, used by run.py plan.

A run extracts:
- every quarter that has ended since the latest one loaded: the FDIC publishes a quarter
  7 to 8 weeks after it closes, so an attempt before that ends as "not published yet";
- on the weekly run, the revision window: the four most recent quarters already loaded,
  where the FDIC amends filings (DWH-04).
A rerun of chosen quarters replaces both.
"""

from __future__ import annotations

from datetime import date

from .quarters import quarter_range, quarter_to_repdte


def quarter_after(repdte: str) -> str:
    year, month = int(repdte[:4]), int(repdte[4:6])
    if month == 12:
        return quarter_to_repdte(f"{year + 1}Q1")
    return quarter_to_repdte(f"{year}Q{month // 3 + 1}")


def ended_since(latest: str, today: date) -> list[str]:
    """Quarters after `latest` whose last day is before `today`."""
    quarters = []
    candidate = quarter_after(latest)
    while date(int(candidate[:4]), int(candidate[4:6]), int(candidate[6:])) < today:
        quarters.append(candidate)
        candidate = quarter_after(candidate)
    return quarters


def plan_quarters(
    loaded: list[str],
    today: date,
    *,
    include_window: bool,
    window: int = 4,
    requested: str | None = None,
) -> list[str]:
    if requested:
        return quarter_range(requested)
    if not loaded:
        raise ValueError("no quarter loaded yet: run the first load with explicit quarters")
    latest = max(loaded)
    planned = set(ended_since(latest, today))
    if include_window:
        planned.update(sorted(loaded)[-window:])
    return sorted(planned)
