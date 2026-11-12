from fdic_dwh.contract import validate_rows


def fin_row(cert, **overrides):
    row = {name: 1 for name in (
        "ASSET", "DEP", "LNLSNET", "EQ", "NETINC", "INTINC", "NCLNLS", "RBCT1J", "ROA", "ROE",
        "NIMY", "EEFFR", "EQV", "LNLSDEPR", "NCLNLSR", "NTLNLSR", "RBC1AAJ",
    )}
    row.update(CERT=cert, REPDTE="20260630", **overrides)
    return row


def test_contract_declares_the_three_datasets(specs):
    assert set(specs) == {"financials", "institutions", "failures"}
    assert specs["financials"].key == ("CERT", "REPDTE")
    assert specs["financials"].filter_for("20260630") == "REPDTE:20260630"
    assert specs["financials"].fields["NETINC"].cumulative == "year_to_date"
    assert specs["institutions"].filter_for(None) is None


def test_valid_rows_pass(specs):
    result = validate_rows(specs["financials"], [fin_row(1), fin_row(2)])
    assert result.blocking_errors(0.0) == []
    assert result.rejects == []


def test_zero_and_null_are_both_accepted_and_stay_distinct(specs):
    rows = [fin_row(1, DEP=0, LNLSDEPR=0), fin_row(2, DEP=None)]
    result = validate_rows(specs["financials"], rows)
    assert result.blocking_errors(0.0) == []
    assert rows[0]["DEP"] == 0 and rows[1]["DEP"] is None


def test_field_missing_from_every_row_blocks(specs):
    rows = [fin_row(1), fin_row(2)]
    for row in rows:
        del row["DEP"]
    errors = validate_rows(specs["financials"], rows).blocking_errors(0.0)
    assert errors == ["contract fields absent from every row: DEP"]


def test_duplicate_key_blocks(specs):
    errors = validate_rows(specs["financials"], [fin_row(1), fin_row(1)]).blocking_errors(0.0)
    assert errors == ["rows 1 and 2: duplicate key 1|20260630"]


def test_bad_value_is_rejected_with_its_reason(specs):
    result = validate_rows(specs["financials"], [fin_row(1, ASSET="n/a"), fin_row(2)])
    [reject] = result.rejects
    assert (reject.row_number, reject.field, reject.reason, reject.raw_value) == (
        1, "ASSET", "not a number", "n/a")
    assert result.reject_rate == 0.5
    assert result.blocking_errors(0.0)[-1].startswith("reject rate 50.0000%")
    assert result.blocking_errors(0.6) == []


def test_dates_follow_each_endpoint_format(specs):
    failures = specs["failures"]
    base = {name: None for name in failures.fields}
    ok = {**base, "ID": "4115", "CERT": 25796, "FAILDATE": "5/1/2026"}
    iso = {**base, "ID": "4116", "CERT": None, "FAILDATE": "2026-05-01"}
    result = validate_rows(failures, [ok, iso])
    assert [(r.row_number, r.field) for r in result.rejects] == [(2, "FAILDATE")]


def test_no_rows_blocks(specs):
    assert validate_rows(specs["financials"], []).blocking_errors(0.0) == ["no rows extracted"]
