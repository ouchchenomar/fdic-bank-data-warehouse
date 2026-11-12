"""Simulated correction (DWH-04, REC-04): one value changed in a copy of the last loaded file.

The batch goes through the normal pipeline with mode 'simulated', so it is validated,
hashed and versioned like a real revision, and stays identified as simulated everywhere.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg

from .config import ROOT
from .contract import DatasetSpec
from .sources import FetchResult


def parse_value(text: str) -> int | float:
    try:
        return int(text)
    except ValueError:
        return float(text)


class SimulatedSource:
    mode = "simulated"

    def __init__(
        self,
        conn: psycopg.Connection,
        cert: int,
        field: str,
        value: Any = None,
        change_pct: float | None = None,
    ) -> None:
        if (value is None) == (change_pct is None):
            raise ValueError("give either a value or a percentage change")
        self.conn, self.cert, self.field = conn, cert, field
        self.value, self.change_pct = value, change_pct

    def fetch(self, spec: DatasetSpec, partition: str | None) -> FetchResult:
        if self.field not in spec.fields or self.field in spec.key:
            raise ValueError(f"{self.field} is not a non-key field of {spec.name}")
        found = self.conn.execute(
            "select batch_id, file_path, source_index_name, source_index_created_at"
            " from ops.batch where dataset = %s and partition_value = %s and status = 'loaded'"
            " order by started_at desc, batch_id desc limit 1",
            (spec.name, partition or "all"),
        ).fetchone()
        if not found:
            raise LookupError(f"no loaded batch for {spec.name} {partition}: ingest it first")
        base_batch, file_path, index_name, index_created = found
        path = Path(file_path) if Path(file_path).is_absolute() else ROOT / file_path
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        matches = [row for row in rows if row.get("CERT") == self.cert]
        if len(matches) != 1:
            raise LookupError(f"CERT {self.cert} not found in {base_batch}")
        previous = matches[0].get(self.field)
        if self.change_pct is not None:
            if not isinstance(previous, (int, float)):
                raise ValueError(f"{self.field} is {previous!r}: a percentage needs a number")
            new_value = previous * (1 + self.change_pct / 100)
            new_value = round(new_value) if isinstance(previous, int) else round(new_value, 6)
        else:
            new_value = self.value
        matches[0][self.field] = new_value
        return FetchResult(
            rows=rows,
            rows_announced=len(rows),
            pages=1,
            request_url=f"simulated://{base_batch}",
            request_params={
                "simulated": True,
                "base_batch_id": base_batch,
                "cert": self.cert,
                "field": self.field,
                "previous_value": previous,
                "new_value": new_value,
            },
            index_name=index_name,
            index_created_at=index_created.isoformat() if index_created else None,
        )
