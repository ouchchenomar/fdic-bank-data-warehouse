import hashlib

from fdic_dwh.rawfiles import canonical_bytes, row_hash, sort_rows, write_raw


def test_same_content_gives_same_bytes_whatever_the_page_order(specs):
    spec = specs["financials"]
    a = [{"CERT": 10, "REPDTE": "20260630", "ASSET": 5}, {"REPDTE": "20260630", "CERT": 2}]
    b = [{"ASSET": 5, "REPDTE": "20260630", "CERT": 10}, {"CERT": 2, "REPDTE": "20260630"}][::-1]
    assert canonical_bytes(sort_rows(spec, a)) == canonical_bytes(sort_rows(spec, b))


def test_numeric_sort_and_lf_endings(specs):
    rows = sort_rows(specs["financials"], [{"CERT": 10}, {"CERT": 9}, {"CERT": 100}])
    assert [r["CERT"] for r in rows] == [9, 10, 100]
    content = canonical_bytes(rows)
    assert b"\r" not in content and content.count(b"\n") == 3


def test_row_hash_distinguishes_zero_from_null():
    assert row_hash({"DEP": 0}) != row_hash({"DEP": None})
    assert row_hash({"a": 1, "b": 2}) == row_hash({"b": 2, "a": 1})


def test_write_raw_returns_the_file_hash(tmp_path):
    content = b'{"CERT":1}\n'
    path, sha = write_raw(tmp_path, "financials", "20260630", "batch_x", content, {"k": "v"})
    assert path.read_bytes() == content
    assert sha == hashlib.sha256(content).hexdigest()
    assert (path.parent / "batch_x.manifest.json").exists()
