"""The versioned offline sample must satisfy the same contract as the API."""

import pytest

from fdic_dwh.config import ROOT
from fdic_dwh.contract import validate_rows
from fdic_dwh.sources import OfflineSource

SAMPLE_DIR = ROOT / "data" / "sample"
PARTITIONS = [
    (dataset, path.name.removesuffix(".jsonl"))
    for dataset in ("financials", "institutions", "failures")
    for path in sorted((SAMPLE_DIR / dataset).glob("*.jsonl"))
]


@pytest.mark.parametrize(("dataset", "partition"), PARTITIONS)
def test_sample_partition_passes_the_contract(specs, dataset, partition):
    spec = specs[dataset]
    fetched = OfflineSource(SAMPLE_DIR).fetch(spec, None if partition == "all" else partition)
    assert fetched.rows, "empty sample partition"
    assert validate_rows(spec, fetched.rows).blocking_errors(spec.max_reject_rate) == []


def test_sample_covers_six_quarters():
    quarters = [p for d, p in PARTITIONS if d == "financials"]
    assert quarters == ["20250331", "20250630", "20250930", "20251231", "20260331", "20260630"]
