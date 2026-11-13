"""Quarter labels (2025Q4) to FDIC report dates (20251231)."""

from __future__ import annotations

import re

_QUARTER_END = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}
_PATTERN = re.compile(r"(\d{4})Q([1-4])")


def _parse(label: str) -> tuple[int, int]:
    match = _PATTERN.fullmatch(label.strip().upper())
    if not match:
        raise ValueError(f"invalid quarter {label!r}, expected e.g. 2025Q4")
    return int(match.group(1)), int(match.group(2))


def quarter_to_repdte(label: str) -> str:
    year, quarter = _parse(label)
    return f"{year}{_QUARTER_END[quarter]}"


def repdte_to_quarter(repdte: str) -> str:
    """'20260630' -> '2026Q2'."""
    return f"{repdte[:4]}Q{int(repdte[4:6]) // 3}"


def quarter_range(spec: str) -> list[str]:
    """'2025Q1:2026Q2' -> ['20250331', ..., '20260630']; a single quarter is accepted too."""
    start, _, end = spec.partition(":")
    first, last = _parse(start), _parse(end or start)
    if last < first:
        raise ValueError(f"empty quarter range {spec!r}")
    dates = []
    year, quarter = first
    while (year, quarter) <= last:
        dates.append(f"{year}{_QUARTER_END[quarter]}")
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
    return dates
