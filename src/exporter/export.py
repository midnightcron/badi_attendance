"""
Nightly Parquet export of occupancy data.

Reads yesterday's rows from PostgreSQL and writes a Parquet file to
the local SSD mount:
    /data/parquet/year=YYYY/month=MM/day=DD/occupancy.parquet

Schema matches the existing Azure export format for ML/analytics compatibility:
    timestamp           datetime64[us, UTC]
    occupancy_oerlikon  Int32 (nullable)
    occupancy_city      Int32 (nullable)
    hour                int8
    minute              int8
    day_of_week         int8
    is_open_oerlikon    bool
    is_open_city        bool

Invoked by:
    docker compose run --rm exporter     (from systemd timer badi-exporter.timer)

Environment variables:
    DATABASE_URL   postgresql://badi@postgres/badi
    PARQUET_DIR    /data/parquet  (mounted from /mnt/data/parquet on host)
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg
import pandas as pd

_TZ = ZoneInfo("Europe/Zurich")
_PW_FILE = Path("/run/secrets/pg_password")

_HOURS_OERLIKON: dict[int, tuple[int, int]] = {
    0: (6, 20), 1: (6, 20), 2: (6, 22), 3: (6, 20),
    4: (6, 22), 5: (6, 22), 6: (6, 22),
}
_HOURS_CITY: dict[int, tuple[int, int]] = {i: (6, 22) for i in range(7)}

logging.basicConfig(
    level="INFO",
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("exporter")


def _password() -> str:
    if _PW_FILE.exists():
        return _PW_FILE.read_text().strip()
    return os.getenv("PG_PASSWORD", "")


def _is_open(dow: int, h: int, hours: dict) -> bool:
    oh, ch = hours.get(dow, (0, 0))
    return oh <= h < ch


async def export_yesterday() -> None:
    yesterday = (datetime.now(_TZ) - timedelta(days=1)).date()
    log.info(f"Exporting {yesterday}")

    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn, password=_password())
    try:
        rows = await conn.fetch(
            """
            SELECT ts, occupancy_oerlikon, occupancy_city
            FROM occupancy
            WHERE ts >= $1::date AND ts < $1::date + INTERVAL '1 day'
            ORDER BY ts
            """,
            yesterday,
        )
    finally:
        await conn.close()

    if not rows:
        log.warning(f"No rows for {yesterday} — skipping")
        return

    df = pd.DataFrame([dict(r) for r in rows])

    df["ts"] = df["ts"].dt.tz_convert("UTC")
    df = df.rename(columns={"ts": "timestamp"})

    local_ts = df["timestamp"].dt.tz_convert(_TZ)
    df["hour"] = local_ts.dt.hour.astype("int8")
    df["minute"] = local_ts.dt.minute.astype("int8")
    df["day_of_week"] = local_ts.dt.dayofweek.astype("int8")

    df["occupancy_oerlikon"] = pd.array(df["occupancy_oerlikon"], dtype="Int32")
    df["occupancy_city"] = pd.array(df["occupancy_city"], dtype="Int32")

    df["is_open_oerlikon"] = df.apply(
        lambda r: _is_open(int(r["day_of_week"]), int(r["hour"]), _HOURS_OERLIKON),
        axis=1,
    )
    df["is_open_city"] = df.apply(
        lambda r: _is_open(int(r["day_of_week"]), int(r["hour"]), _HOURS_CITY),
        axis=1,
    )

    parquet_dir = Path(os.getenv("PARQUET_DIR", "/data/parquet"))
    out_path = parquet_dir / f"year={yesterday.year}" / f"month={yesterday.month:02d}" / f"day={yesterday.day:02d}" / "occupancy.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df.to_parquet(out_path, index=False, compression="snappy", engine="pyarrow")
    log.info(f"Exported {len(df)} rows → {out_path} ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    asyncio.run(export_yesterday())
