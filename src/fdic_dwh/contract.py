"""Data contract: load contracts/fdic.yml and check extracted rows against it."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

_INTEGER = re.compile(r"-?\d+")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    nullable: bool = True
    unit: str | None = None
    date_format: str | None = None
    cumulative: str | None = None
    description: str = ""
    requested: bool = True  # False for fields the API returns without being asked (ID)


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    endpoint: str
    key: tuple[str, ...]
    sort_by: str
    fields: dict[str, FieldSpec]
    partition_field: str | None = None
    partition_filter: str | None = None
    max_reject_rate: float = 0.0
    page_size: int | None = None  # overrides the default when no stable sort key exists

    @property
    def requested_fields(self) -> list[str]:
        return [name for name, f in self.fields.items() if f.requested]

    @property
    def raw_table(self) -> str:
        return f"raw.fdic_{self.name}"

    def record_key(self, row: dict[str, Any]) -> str:
        return "|".join("" if row.get(k) is None else str(row[k]) for k in self.key)

    def sort_key(self, row: dict[str, Any]) -> tuple:
        # Integers sort numerically, everything else as text; None first.
        return tuple(
            (0, 0, "") if row.get(k) is None
            else (1, row[k], "") if isinstance(row[k], int)
            else (2, 0, str(row[k]))
            for k in self.key
        )

    def filter_for(self, partition: str | None) -> str | None:
        if self.partition_filter is None or partition is None:
            return None
        return self.partition_filter.format(value=partition)


def load_contract(path: Path) -> dict[str, DatasetSpec]:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    datasets = {}
    for name, ds in doc["datasets"].items():
        fields = {
            fname: FieldSpec(
                name=fname,
                type=f["type"],
                nullable=f.get("nullable", True),
                unit=f.get("unit"),
                date_format=f.get("format"),
                cumulative=f.get("cumulative"),
                description=f.get("description", ""),
                requested=f.get("requested", True),
            )
            for fname, f in ds["fields"].items()
        }
        partition = ds.get("partition") or {}
        datasets[name] = DatasetSpec(
            name=name,
            endpoint=ds["endpoint"],
            key=tuple(ds["key"]),
            sort_by=ds["sort_by"],
            fields=fields,
            partition_field=partition.get("field"),
            partition_filter=partition.get("filter"),
            max_reject_rate=float(ds.get("max_reject_rate", 0.0)),
            page_size=ds.get("page_size"),
        )
    return datasets


@dataclass(frozen=True)
class Reject:
    row_number: int
    record_key: str
    field: str
    reason: str
    raw_value: str | None


@dataclass
class ValidationResult:
    row_count: int
    schema_errors: list[str] = field(default_factory=list)
    key_errors: list[str] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)

    @property
    def rejected_rows(self) -> set[int]:
        return {r.row_number for r in self.rejects}

    @property
    def reject_rate(self) -> float:
        return len(self.rejected_rows) / self.row_count if self.row_count else 0.0

    def blocking_errors(self, max_reject_rate: float) -> list[str]:
        errors = [*self.schema_errors, *self.key_errors]
        if self.reject_rate > max_reject_rate:
            errors.append(
                f"reject rate {self.reject_rate:.4%} above the contract limit {max_reject_rate:.4%}"
            )
        return errors


def _type_error(spec: FieldSpec, value: Any) -> str | None:
    """Return why a non-null value does not match its declared type, or None."""
    if spec.type == "integer":
        if isinstance(value, bool):
            return "boolean where an integer is expected"
        if isinstance(value, int) or (isinstance(value, str) and _INTEGER.fullmatch(value)):
            return None
        return "not an integer"
    if spec.type == "numeric":
        if isinstance(value, bool):
            return "boolean where a number is expected"
        if isinstance(value, (int, float)):
            return None
        if isinstance(value, str):
            if value == "":
                return None  # empty string is treated as missing, like null
            try:
                Decimal(value)
                return None
            except InvalidOperation:
                return "not a number"
        return "not a number"
    if spec.type == "date":
        if isinstance(value, str) and value == "":
            return None
        try:
            datetime.strptime(str(value), spec.date_format or "%Y-%m-%d")
            return None
        except ValueError:
            return f"not a date in format {spec.date_format}"
    if spec.type == "text":
        return None if isinstance(value, (str, int, float)) else "not a scalar value"
    return f"unknown contract type {spec.type}"


def validate_rows(spec: DatasetSpec, rows: list[dict[str, Any]]) -> ValidationResult:
    """Check schema, keys and types. Row numbers are 1-based positions in `rows`."""
    result = ValidationResult(row_count=len(rows))
    if not rows:
        result.schema_errors.append("no rows extracted")
        return result

    present = set().union(*(row.keys() for row in rows))
    missing = [name for name in spec.fields if name not in present]
    if missing:
        result.schema_errors.append(f"contract fields absent from every row: {', '.join(missing)}")

    seen: dict[str, int] = {}
    for number, row in enumerate(rows, start=1):
        key = spec.record_key(row)
        for name in spec.key:
            if row.get(name) in (None, ""):
                result.key_errors.append(f"row {number}: key field {name} is empty")
        if key in seen:
            result.key_errors.append(f"rows {seen[key]} and {number}: duplicate key {key}")
        else:
            seen[key] = number

        for name, fspec in spec.fields.items():
            value = row.get(name)
            if value is None:
                if not fspec.nullable:
                    result.rejects.append(Reject(number, key, name, "required value missing", None))
                continue
            reason = _type_error(fspec, value)
            if reason:
                result.rejects.append(Reject(number, key, name, reason, str(value)[:200]))

    # Keep the report readable when a source is badly broken.
    if len(result.key_errors) > 20:
        extra = len(result.key_errors) - 20
        result.key_errors = [*result.key_errors[:20], f"... and {extra} more key errors"]
    return result
