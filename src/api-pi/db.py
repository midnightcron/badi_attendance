"""
asyncpg connection pool for the FastAPI app.

Call create_pool() once at startup; pass the pool to route handlers.
"""

import os
from pathlib import Path

import asyncpg

_DSN = os.environ["DATABASE_URL"]
_PW_FILE = Path("/run/secrets/pg_password")


def _password() -> str:
    if _PW_FILE.exists():
        return _PW_FILE.read_text().strip()
    return os.getenv("PG_PASSWORD", "")


async def create_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(
        _DSN,
        password=_password(),
        min_size=2,
        max_size=10,
        command_timeout=30,
    )


async def fetch_readings(pool: asyncpg.Pool, lookback_days: int) -> list[dict]:
    """
    Fetch raw readings for the last N days, ordered ascending by ts.
    Used by the dashboard builder.
    """
    rows = await pool.fetch(
        """
        SELECT ts, occupancy_oerlikon, occupancy_city
        FROM occupancy
        WHERE ts >= NOW() - ($1::int * INTERVAL '1 day')
        ORDER BY ts ASC
        """,
        lookback_days,
    )
    return [
        {
            "ts": r["ts"],
            "occupancy_oerlikon": r["occupancy_oerlikon"],
            "occupancy_city": r["occupancy_city"],
        }
        for r in rows
    ]


async def fetch_occupancy(
    pool: asyncpg.Pool,
    start_ts,
    end_ts,
    bucket_minutes: int | None,
    location: str,
) -> list[dict]:
    """
    Return occupancy data for a date range at a given resolution.

    Args:
        bucket_minutes: None → raw; otherwise GROUP BY time_bucket.
        location: 'oerlikon' or 'city'.
    """
    col = f"occupancy_{location}"

    if bucket_minutes is None:
        rows = await pool.fetch(
            f"""
            SELECT ts AS bucket, {col} AS occupancy
            FROM occupancy
            WHERE ts >= $1 AND ts < $2 AND {col} IS NOT NULL
            ORDER BY ts
            """,
            start_ts, end_ts,
        )
        return [
            {"timestamp": r["bucket"].isoformat(), "occupancy": r["occupancy"]}
            for r in rows
        ]

    rows = await pool.fetch(
        f"""
        SELECT
            time_bucket($1::interval, ts)    AS bucket,
            ROUND(AVG({col})::numeric, 1)    AS avg,
            MIN({col})                       AS min,
            MAX({col})                       AS max,
            COUNT({col})                     AS readings
        FROM occupancy
        WHERE ts >= $2 AND ts < $3 AND {col} IS NOT NULL
        GROUP BY bucket
        ORDER BY bucket
        """,
        f"{bucket_minutes} minutes",
        start_ts,
        end_ts,
    )
    return [
        {
            "timestamp": r["bucket"].isoformat(),
            f"occupancy_{location}": float(r["avg"]),
            f"occupancy_{location}_min": r["min"],
            f"occupancy_{location}_max": r["max"],
            "readings": r["readings"],
        }
        for r in rows
    ]
