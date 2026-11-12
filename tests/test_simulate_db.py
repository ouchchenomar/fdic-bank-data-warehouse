"""Simulated correction (REC-04): one value changed, everything else identical."""

from __future__ import annotations

import pytest

from fdic_dwh.pipeline import ingest
from fdic_dwh.simulate import SimulatedSource, parse_value
from test_pipeline_db import FakeSource, rows

pytestmark = pytest.mark.db


def payloads(pg, batch_id):
    return {
        key: payload
        for key, payload in pg.execute(
            "select record_key, payload from raw.fdic_financials where batch_id = %s", (batch_id,)
        )
    }


@pytest.fixture
def loaded(pg, specs, tmp_path):
    outcome = ingest(pg, specs["financials"], FakeSource(rows()), tmp_path, "20260630")
    assert outcome.status == "loaded"
    return outcome


def test_simulation_changes_one_value_and_is_flagged(pg, specs, tmp_path, loaded):
    source = SimulatedSource(pg, cert=2, field="EQ", value=12345)
    outcome = ingest(pg, specs["financials"], source, tmp_path, "20260630")

    assert outcome.status == "loaded"
    mode, params = pg.execute(
        "select mode, request_params from ops.batch where batch_id = %s", (outcome.batch_id,)
    ).fetchone()
    assert mode == "simulated"
    assert params["base_batch_id"] == loaded.batch_id
    assert (params["previous_value"], params["new_value"]) == (200, 12345)

    before, after = payloads(pg, loaded.batch_id), payloads(pg, outcome.batch_id)
    assert after["2|20260630"]["EQ"] == 12345
    after["2|20260630"]["EQ"] = before["2|20260630"]["EQ"]
    assert after == before


def test_percentage_change_keeps_whole_thousands(pg, specs, tmp_path, loaded):
    source = SimulatedSource(pg, cert=3, field="ASSET", change_pct=10)
    outcome = ingest(pg, specs["financials"], source, tmp_path, "20260630")
    assert payloads(pg, outcome.batch_id)["3|20260630"]["ASSET"] == 330


def test_unknown_cert_is_a_failed_batch(pg, specs, tmp_path, loaded):
    outcome = ingest(pg, specs["financials"], SimulatedSource(pg, 99, "EQ", value=1), tmp_path,
                     "20260630")
    assert outcome.status == "failed"
    assert "CERT 99 not found" in outcome.error


def test_key_fields_cannot_be_simulated(pg, specs, tmp_path, loaded):
    outcome = ingest(pg, specs["financials"], SimulatedSource(pg, 1, "REPDTE", value="20260331"),
                     tmp_path, "20260630")
    assert outcome.status == "failed"
    assert "not a non-key field" in outcome.error


def test_a_quarter_never_loaded_cannot_be_simulated(pg, specs, tmp_path):
    outcome = ingest(pg, specs["financials"], SimulatedSource(pg, 1, "EQ", value=1), tmp_path,
                     "20260331")
    assert outcome.status == "failed"
    assert "ingest it first" in outcome.error


def test_value_and_percentage_are_exclusive(pg):
    with pytest.raises(ValueError):
        SimulatedSource(pg, 1, "EQ", value=1, change_pct=5)
    with pytest.raises(ValueError):
        SimulatedSource(pg, 1, "EQ")


def test_parse_value_keeps_integers_whole():
    assert parse_value("120") == 120 and isinstance(parse_value("120"), int)
    assert parse_value("12.5") == 12.5
