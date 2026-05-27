"""
PostgreSQL writer for occupancy readings (replaces Azure table_writer.py).

Schema:
    occupancy (ts TIMESTAMPTZ, occupancy_oerlikon INTEGER, occupancy_city INTEGER)

The hypertable is defined in deploy/init.sql.
"""

import logging
import os
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

_DSN = os.environ["DATABASE_URL"]
_PW_FILE = Path("/run/secrets/pg_password")


def _password() -> str:
    if _PW_FILE.exists():
        return _PW_FILE.read_text().strip()
    return os.getenv("PG_PASSWORD", "")


async def create_pool() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(
        _DSN,
        password=_password(),
        min_size=1,
        max_size=3,
        command_timeout=10,
    )
    logger.info("PostgreSQL pool ready")
    return pool


async def write_reading(pool: asyncpg.Pool, reading: dict) -> None:
    """
    Insert one occupancy reading.

    Args:
        reading: {"ts": datetime, "occupancy_oerlikon": int|None, "occupancy_city": int|None}
    """
    await pool.execute(
        """
        INSERT INTO occupancy (ts, occupancy_oerlikon, occupancy_city)
        VALUES ($1, $2, $3)
        ON CONFLICT DO NOTHING
        """,
        reading["ts"],
        reading.get("occupancy_oerlikon"),
        reading.get("occupancy_city"),
    )
