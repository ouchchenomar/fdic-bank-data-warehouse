"""Where rows come from: the live API, or the versioned offline sample."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .client import FdicClient
from .contract import DatasetSpec


@dataclass
class FetchResult:
    rows: list[dict[str, Any]]
    rows_announced: int
    pages: int
    request_url: str
    request_params: dict[str, Any]
    index_name: str | None
    index_created_at: str | None


class Source(Protocol):
    mode: str

    def fetch(self, spec: DatasetSpec, partition: str | None) -> FetchResult: ...


class ApiSource:
    mode = "api"

    def __init__(self, client: FdicClient) -> None:
        self.client = client

    def fetch(self, spec: DatasetSpec, partition: str | None) -> FetchResult:
        fields = spec.requested_fields
        filters = spec.filter_for(partition)
        page_size = spec.page_size or self.client.page_size
        rows: list[dict[str, Any]] = []
        pages = 0
        announced = 0
        index_name = index_created_at = None
        first_url = ""
        for page in self.client.iter_pages(
            spec.endpoint, fields=fields, sort_by=spec.sort_by, filters=filters,
            page_size=page_size,
        ):
            pages += 1
            first_url = first_url or page.url
            announced = page.total
            index_name, index_created_at = page.index_name, page.index_created_at
            # Keep contract fields only, without inventing missing keys:
            # a field the API stops sending must stay detectable.
            rows.extend({k: v for k, v in row.items() if k in spec.fields} for row in page.rows)
        return FetchResult(
            rows=rows,
            rows_announced=announced,
            pages=pages,
            request_url=first_url,
            request_params={
                "endpoint": spec.endpoint,
                "fields": fields,
                "filters": filters,
                "sort_by": spec.sort_by,
                "page_size": page_size,
            },
            index_name=index_name,
            index_created_at=index_created_at,
        )


class OfflineSource:
    """Reads data/sample/<dataset>/<partition>.jsonl and its .meta.json."""

    mode = "offline"

    def __init__(self, sample_dir: Path) -> None:
        self.sample_dir = sample_dir

    def fetch(self, spec: DatasetSpec, partition: str | None) -> FetchResult:
        label = partition or "all"
        data_file = self.sample_dir / spec.name / f"{label}.jsonl"
        meta_file = self.sample_dir / spec.name / f"{label}.meta.json"
        if not data_file.exists():
            raise FileNotFoundError(f"no offline sample for {spec.name} {label}: {data_file}")
        rows = [
            json.loads(line)
            for line in data_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        return FetchResult(
            rows=rows,
            rows_announced=len(rows),
            pages=1,
            request_url=data_file.as_posix(),
            request_params={"sample_of": meta.get("source_batch_id"), "certs": meta.get("certs")},
            index_name=meta.get("source_index_name"),
            index_created_at=meta.get("source_index_created_at"),
        )
