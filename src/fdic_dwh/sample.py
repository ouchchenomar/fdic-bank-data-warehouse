"""Build the versioned offline sample from the latest loaded API batches."""

from __future__ import annotations

import json
from pathlib import Path

import psycopg

from .config import ROOT
from .contract import DatasetSpec
from .rawfiles import canonical_bytes

# Largest banks, the 2025-2026 failures, and two edge cases with zero deposits.
DEFAULT_CERTS = [
    3511,   # Wells Fargo Bank, N.A.
    628,    # JPMorgan Chase Bank, N.A.
    3510,   # Bank of America, N.A.
    7213,   # Citibank, N.A.
    6548,   # U.S. Bank N.A.
    28611,  # failed 2025-01-17
    5520,   # failed 2025-06-27
    57488,  # failed 2026-01-30
    25796,  # failed 2026-05-01
    28722,  # failed 2026-07-10
    25744,  # failed 2026-07-17
    34065,  # zero deposits, FDIC publishes a 0 loans-to-deposits ratio
    57834,  # small bank, zero loans
    32961,  # trust company (class NC) absent from /institutions
]


def make_sample(
    conn: psycopg.Connection, specs: dict[str, DatasetSpec], sample_dir: Path, certs: list[int]
) -> list[str]:
    wanted = set(certs)
    written = []
    batches = conn.execute(
        "select distinct on (dataset, partition_value) dataset, partition_value, batch_id,"
        " file_path, source_index_name, source_index_created_at"
        " from ops.batch where status = 'loaded' and mode = 'api'"
        " order by dataset, partition_value, started_at desc"
    ).fetchall()
    for dataset, partition, batch_id, file_path, index_name, index_created in batches:
        if dataset not in specs:
            continue
        rows = [
            json.loads(line)
            for line in (ROOT / file_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        subset = [row for row in rows if row.get("CERT") in wanted]
        target = sample_dir / dataset
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{partition}.jsonl").write_bytes(canonical_bytes(subset))
        meta = {
            "source_batch_id": batch_id,
            "source_index_name": index_name,
            "source_index_created_at": index_created.isoformat() if index_created else None,
            "certs": sorted(wanted),
            "rows": len(subset),
            "rows_in_source_batch": len(rows),
        }
        (target / f"{partition}.meta.json").write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )
        written.append(f"{dataset}/{partition}: {len(subset)} rows")
    return written
