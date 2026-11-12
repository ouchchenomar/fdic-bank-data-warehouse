"""End-to-end ingestion against the local PostgreSQL (REC-03, REC-05)."""

from __future__ import annotations

import copy

import pytest

from fdic_dwh.pipeline import ingest
from fdic_dwh.sources import FetchResult

pytestmark = pytest.mark.db

FIELDS = ("ASSET", "DEP", "LNLSNET", "EQ", "NETINC", "INTINC", "NCLNLS", "RBCT1J", "ROA", "ROE",
          "NIMY", "EEFFR", "EQV", "LNLSDEPR", "NCLNLSR", "NTLNLSR", "RBC1AAJ")


def rows(n=3, overrides=None):
    out = []
    for cert in range(1, n + 1):
        row = {name: cert * 100 for name in FIELDS}
        row.update(CERT=cert, REPDTE="20260630")
        out.append(row)
    for (cert, field), value in (overrides or {}).items():
        out[cert - 1][field] = value
    return out


class FakeSource:
    mode = "offline"

    def __init__(self, data, announced=None, error=None):
        self.data, self.announced, self.error = data, announced, error

    def fetch(self, spec, partition):
        if self.error:
            raise self.error
        return FetchResult(
            rows=copy.deepcopy(self.data),
            rows_announced=len(self.data) if self.announced is None else self.announced,
            pages=1, request_url="fake://", request_params={}, index_name="risview_test",
            index_created_at="2026-08-19T18:58:33Z",
        )


def raw_count(pg):
    return pg.execute("select count(*) from raw.fdic_financials").fetchone()[0]


def statuses(pg):
    return [r[0] for r in pg.execute("select status from ops.batch order by started_at")]


def test_load_then_replay_same_file_is_traced_but_not_reloaded(pg, specs, tmp_path):
    spec = specs["financials"]
    first = ingest(pg, spec, FakeSource(rows()), tmp_path, "20260630")
    assert (first.status, first.rows_loaded) == ("loaded", 3)

    second = ingest(pg, spec, FakeSource(list(reversed(rows()))), tmp_path, "20260630")
    assert second.status == "duplicate"
    assert second.duplicate_of == first.batch_id
    assert raw_count(pg) == 3
    assert statuses(pg) == ["loaded", "duplicate"]


def test_revised_value_creates_a_new_loaded_batch(pg, specs, tmp_path):
    spec = specs["financials"]
    ingest(pg, spec, FakeSource(rows()), tmp_path, "20260630")
    revised_rows = rows(overrides={(2, "ASSET"): 999})
    revised = ingest(pg, spec, FakeSource(revised_rows), tmp_path, "20260630")
    assert revised.status == "loaded"
    hashes = pg.execute(
        "select count(distinct row_hash) from raw.fdic_financials where record_key = '2|20260630'"
    ).fetchone()[0]
    assert hashes == 2  # both versions of bank 2 are kept


def test_incomplete_source_is_refused_and_keeps_previous_state(pg, specs, tmp_path):
    spec = specs["financials"]
    ingest(pg, spec, FakeSource(rows()), tmp_path, "20260630")
    missing_page = ingest(pg, spec, FakeSource(rows(2), announced=3), tmp_path, "20260630")
    assert missing_page.status == "failed"
    assert "coverage: 2 rows extracted for 3 announced" in missing_page.error
    assert raw_count(pg) == 3


def test_dropped_field_is_refused(pg, specs, tmp_path):
    data = rows()
    for row in data:
        del row["DEP"]
    outcome = ingest(pg, specs["financials"], FakeSource(data), tmp_path, "20260630")
    assert outcome.status == "failed"
    assert "absent from every row: DEP" in outcome.error
    assert raw_count(pg) == 0


def test_rejected_value_is_recorded_with_its_reason(pg, specs, tmp_path):
    outcome = ingest(pg, specs["financials"], FakeSource(rows(overrides={(1, "ASSET"): "n/a"})),
                     tmp_path, "20260630")
    assert outcome.status == "failed"  # the contract allows 0 % rejects
    reject = pg.execute(
        "select record_key, field, reason, raw_value from ops.batch_reject"
    ).fetchone()
    assert reject == ("1|20260630", "ASSET", "not a number", "n/a")


def test_source_error_reaches_the_register(pg, specs, tmp_path):
    outcome = ingest(pg, specs["financials"], FakeSource([], error=TimeoutError("api down")),
                     tmp_path, "20260630")
    assert outcome.status == "failed"
    assert outcome.error == "TimeoutError: api down"
