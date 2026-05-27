"""
One-shot script: import historical Parquet files into PostgreSQL.

Run after downloading the Azure blob container:
    az storage blob download-batch \
        --account-name badiacidevyb1a \
        --source occupancy-parquet \
        --destination ./historical_parquet/
    python infra/import_historical.py ./historical_parquet/

The Parquet schema (from the Azure exporter):
    timestamp           datetime64[us, UTC]
    occupancy_oerlikon  Int32
    occupancy_city      Int32
    hour, minute, day_of_week, is_open_oerlikon, is_open_city  (derived, ignored)

Target PostgreSQL schema:
    occupancy (ts TIMESTAMPTZ, occupancy_oerlikon INTEGER, occupancy_city INTEGER)

Usage:
    python infra/import_historical.py <parquet_root_dir> [--dsn postgresql://...]

The script uses COPY for bulk inserts (~21k rows/file → fast).
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg
import pandas as pd

_TZ = ZoneInfo("Europe/Zurich")
_PW_FILE = Path("/run/secrets/pg_password")

logging.basicConfig(
    level="INFO",
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("import_historical")


def _password() -> str:
    if _PW_FILE.exists():
        return _PW_FILE.read_text().strip()
    return os.getenv("PG_PASSWORD", "")


async def import_file(conn: asyncpg.Connection, parquet_path: Path) -> int:
    df = pd.read_parquet(parquet_path, columns=["timestamp", "occupancy_oerlikon", "occupancy_city"])

    if "timestamp" not in df.columns:
        log.warning(f"No 'timestamp' column in {parquet_path} — skipping")
        return 0

    # Ensure timezone-aware UTC
    ts_col = pd.to_datetime(df["timestamp"], utc=True)
    if ts_col.dt.tz is None:
        ts_col = ts_col.dt.tz_localize("UTC")

    records = [
        (ts.to_pydatetime(), row["occupancy_oerlikon"], row["occupancy_city"])
        for ts, (_, row) in zip(ts_col, df.iterrows())
    ]

    inserted = await conn.executemany(
        """
        INSERT INTO occupancy (ts, occupancy_oerlikon, occupancy_city)
        VALUES ($1, $2, $3)
        ON CONFLICT DO NOTHING
        """,
        records,
    )
    return len(records)


async def run(parquet_root: Path, dsn: str) -> None:
    files = sorted(parquet_root.rglob("*.parquet"))
    if not files:
        log.error(f"No Parquet files found under {parquet_root}")
        sys.exit(1)

    log.info(f"Found {len(files)} Parquet files")

    conn = await asyncpg.connect(dsn, password=_password())
    total = 0
    try:
        for i, path in enumerate(files, 1):
            try:
                n = await import_file(conn, path)
                total += n
                log.info(f"[{i}/{len(files)}] {path.name}: {n} rows  (running total: {total:,})")
            except Exception as e:
                log.error(f"Failed {path}: {e}")
    finally:
        await conn.close()

    log.info(f"Import complete: {total:,} rows from {len(files)} files")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import historical Parquet → PostgreSQL")
    parser.add_argument("parquet_dir", help="Root directory of downloaded Parquet files")
    parser.add_argument(
        "--dsn",
        default=os.getenv("DATABASE_URL", "postgresql://badi@localhost/badi"),
        help="PostgreSQL DSN (default: $DATABASE_URL or postgresql://badi@localhost/badi)",
    )
    args = parser.parse_args()

    asyncio.run(run(Path(args.parquet_dir), args.dsn))


if __name__ == "__main__":
    main()
