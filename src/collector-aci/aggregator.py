"""
Daily aggregation of raw occupancy readings into per-weekday pattern statistics.

Reads all rows from the `occupancy` table, groups by (weekday, 15-min slot),
and upserts summary statistics into the `occupancy_patterns` table.

Pattern table schema:
    PartitionKey  : str   – weekday "0"–"6" (Monday=0, Sunday=6)
    RowKey        : str   – time slot "HH:MM" (06:00, 06:15, … 21:45)
    avg_oerlikon  : float – mean occupancy for Hallenbad Oerlikon
    avg_city      : float – mean occupancy for Hallenbad City
    std_oerlikon  : float – std dev (used for ±1σ forecast bands)
    std_city      : float
    day_count     : int   – number of distinct dates that contributed
    reading_count : int   – total raw readings in this slot
    last_computed : str   – ISO-8601 timestamp of last aggregation run
"""

import logging
import math
from collections import defaultdict
from datetime import datetime, date
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Europe/Zurich")
logger = logging.getLogger(__name__)

_OPEN = 6
_CLOSE = 22


def _bin15(hour: int, minute: int) -> tuple[int, int]:
    """Floor a (hour, minute) to the nearest 15-min boundary."""
    return hour, (minute // 15) * 15


def _slot_label(h: int, m: int) -> str:
    return f"{h:02d}:{m:02d}"


def _parse_row_key(row_key: str) -> tuple[int, int, int]:
    """Parse 'HH:MM:SS.ffffff' → (hour, minute, second)."""
    parts = row_key.split(":")
    h = int(parts[0])
    m = int(parts[1])
    s = int(parts[2].split(".")[0]) if len(parts) > 2 else 0
    return h, m, s


def compute_and_store_patterns(occupancy_client, patterns_client) -> int:
    """
    Read all raw rows, compute per-(weekday, 15-min slot) stats, write to patterns table.

    Returns the number of pattern slots written.
    """
    logger.info("Aggregation run started — reading raw occupancy table")

    # Structure: slot_data[(weekday, h, m)] = {
    #     "oerlikon": [int, ...], "city": [int, ...], "dates": set()
    # }
    slot_data: dict[tuple[int, int, int], dict] = defaultdict(
        lambda: {"oerlikon": [], "city": [], "dates": set()}
    )

    row_count = 0
    try:
        for entity in occupancy_client.list_entities():
            partition_key = entity.get("PartitionKey", "")  # "YYYY-MM-DD"
            row_key = entity.get("RowKey", "")              # "HH:MM:SS.ffffff"

            try:
                day = date.fromisoformat(partition_key)
                h, m, _ = _parse_row_key(row_key)
            except (ValueError, IndexError):
                continue

            if not (_OPEN <= h < _CLOSE):
                continue

            dow = day.weekday()  # 0=Monday, 6=Sunday
            bh, bm = _bin15(h, m)
            bucket = (dow, bh, bm)

            occ_o = entity.get("occupancy_oerlikon")
            occ_c = entity.get("occupancy_city")

            if occ_o is not None:
                slot_data[bucket]["oerlikon"].append(int(occ_o))
            if occ_c is not None:
                slot_data[bucket]["city"].append(int(occ_c))
            slot_data[bucket]["dates"].add(partition_key)

            row_count += 1
    except Exception as e:
        logger.error(f"Failed to read occupancy table: {e}", exc_info=True)
        raise

    logger.info(f"Read {row_count} raw rows, aggregating {len(slot_data)} slot buckets")

    now_str = datetime.now(_TZ).isoformat()
    written = 0

    for (dow, h, m), d in slot_data.items():
        entity = {
            "PartitionKey": str(dow),
            "RowKey": _slot_label(h, m),
            "last_computed": now_str,
            "day_count": len(d["dates"]),
            "reading_count": max(len(d["oerlikon"]), len(d["city"])),
        }

        for key, values in (("oerlikon", d["oerlikon"]), ("city", d["city"])):
            if values:
                avg = sum(values) / len(values)
                std = (
                    math.sqrt(sum((x - avg) ** 2 for x in values) / len(values))
                    if len(values) > 1 else 0.0
                )
                entity[f"avg_{key}"] = round(avg, 2)
                entity[f"std_{key}"] = round(std, 2)
            else:
                entity[f"avg_{key}"] = None
                entity[f"std_{key}"] = None

        try:
            patterns_client.upsert_entity(entity)
            written += 1
        except Exception as e:
            logger.error(f"Failed to write pattern {dow}/{h}:{m:02d}: {e}")

    logger.info(f"Aggregation complete: {written} pattern slots written")
    return written


async def aggregation_loop(occupancy_client, patterns_client, shutdown_event) -> None:
    """
    Async loop: aggregate once at startup, then daily at 02:00 Europe/Zurich.

    Errors are caught and logged; the loop retries the next day rather than crashing.
    """
    import asyncio

    # Run immediately on startup to populate the table from existing data
    try:
        compute_and_store_patterns(occupancy_client, patterns_client)
    except Exception as e:
        logger.error(f"Startup aggregation failed: {e}", exc_info=True)

    while not shutdown_event.is_set():
        # Sleep until next 02:00 Zurich
        now = datetime.now(_TZ)
        next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if next_run <= now:
            from datetime import timedelta
            next_run += timedelta(days=1)

        wait_seconds = (next_run - now).total_seconds()
        logger.info(
            f"Next aggregation at {next_run.strftime('%Y-%m-%d %H:%M %Z')} "
            f"(in {wait_seconds / 3600:.1f}h)"
        )

        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=wait_seconds,
            )
            # shutdown_event was set — exit cleanly
            return
        except asyncio.TimeoutError:
            pass  # Time to aggregate

        if shutdown_event.is_set():
            return

        try:
            compute_and_store_patterns(occupancy_client, patterns_client)
        except Exception as e:
            logger.error(f"Daily aggregation failed: {e}", exc_info=True)
