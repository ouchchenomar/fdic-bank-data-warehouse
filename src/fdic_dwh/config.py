"""Settings read from the environment and the local .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    api_base: str
    page_size: int
    data_dir: Path
    contract_path: Path
    pg_host: str
    pg_port: int
    pg_db: str
    pg_user: str
    pg_password: str
    reader_password: str | None = None

    @property
    def conninfo(self) -> str:
        return make_conninfo(
            host=self.pg_host,
            port=self.pg_port,
            dbname=self.pg_db,
            user=self.pg_user,
            password=self.pg_password,
            connect_timeout=10,
        )

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def sample_dir(self) -> Path:
        return self.data_dir / "sample"


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    return Settings(
        api_base=os.getenv("FDIC_API_BASE", "https://api.fdic.gov/banks"),
        page_size=int(os.getenv("FDIC_PAGE_SIZE", "1000")),
        data_dir=data_dir,
        contract_path=ROOT / "contracts" / "fdic.yml",
        pg_host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        pg_port=int(os.getenv("POSTGRES_PORT", "5435")),
        pg_db=os.getenv("POSTGRES_DB", "fdic_dwh"),
        pg_user=os.getenv("POSTGRES_USER", "fdic"),
        pg_password=os.getenv("POSTGRES_PASSWORD", ""),
        reader_password=os.getenv("FDIC_READER_PASSWORD") or None,
    )
