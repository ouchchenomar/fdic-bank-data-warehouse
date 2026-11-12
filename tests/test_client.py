import pytest
import responses

from fdic_dwh.client import FdicApiError, FdicClient, SourceChangedError

BASE = "https://api.example.test/banks"
URL = f"{BASE}/financials"


def page(rows, total, index="risview_1"):
    return {
        "meta": {
            "total": total,
            "index": {"name": index, "createTimestamp": "2026-08-19T18:58:33Z"},
        },
        "data": [{"data": row, "score": 0} for row in rows],
    }


def client(**kwargs):
    sleeps = []
    c = FdicClient(BASE, page_size=2, sleep=sleeps.append, **kwargs)
    return c, sleeps


@responses.activate
def test_paginates_until_announced_total():
    rows = [{"CERT": n} for n in range(1, 6)]
    for offset in (0, 2, 4):
        responses.get(URL, json=page(rows[offset:offset + 2], total=5))
    c, _ = client()
    pages = list(c.iter_pages("/financials", fields=["CERT"], sort_by="CERT"))
    assert [p.offset for p in pages] == [0, 2, 4]
    assert [r["CERT"] for p in pages for r in p.rows] == [1, 2, 3, 4, 5]
    offsets = [call.request.params["offset"] for call in responses.calls]
    assert offsets == ["0", "2", "4"]
    assert all(call.request.params["sort_by"] == "CERT" for call in responses.calls)


@responses.activate
def test_retries_on_503_then_succeeds():
    responses.get(URL, status=503)
    responses.get(URL, status=429, headers={"Retry-After": "7"})
    responses.get(URL, json=page([{"CERT": 1}], total=1))
    c, sleeps = client(backoff_base=0.5)
    pages = list(c.iter_pages("/financials", fields=["CERT"], sort_by="CERT"))
    assert pages[0].rows == [{"CERT": 1}]
    assert len(sleeps) == 2
    assert 0.5 <= sleeps[0] <= 1.0  # backoff_base * 2**0 + jitter
    assert sleeps[1] == 7.0         # Retry-After is honoured


@responses.activate
def test_gives_up_after_max_retries():
    for _ in range(3):
        responses.get(URL, status=502)
    c, sleeps = client(max_retries=2)
    with pytest.raises(FdicApiError, match="gave up after 3 attempts"):
        list(c.iter_pages("/financials", fields=["CERT"], sort_by="CERT"))
    assert len(sleeps) == 2


@responses.activate
def test_client_error_is_not_retried():
    responses.get(URL, status=400, body="bad filter")
    c, sleeps = client()
    with pytest.raises(FdicApiError, match="HTTP 400"):
        list(c.iter_pages("/financials", fields=["CERT"], sort_by="CERT"))
    assert sleeps == []


@responses.activate
def test_index_rebuilt_during_pagination_is_refused():
    responses.get(URL, json=page([{"CERT": 1}, {"CERT": 2}], total=3, index="risview_1"))
    responses.get(URL, json=page([{"CERT": 3}], total=3, index="risview_2"))
    c, _ = client()
    with pytest.raises(SourceChangedError):
        list(c.iter_pages("/financials", fields=["CERT"], sort_by="CERT"))
