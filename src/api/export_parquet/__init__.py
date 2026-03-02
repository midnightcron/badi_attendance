"""
Azure Function: Nightly Parquet export of occupancy data.

Timer trigger: daily at 02:00 UTC (03:00 CET / 04:00 CEST).

Reads the previous calendar day's rows from Azure Table Storage and writes
a single Parquet file to Blob Storage for ML/analytics consumption.

Output path in the occupancy-parquet container:
    year=YYYY/month=MM/day=DD/occupancy.parquet

Schema:
    timestamp           datetime64[us, UTC]  full UTC timestamp
    occupancy_oerlikon  Int32                swimmer count (SSD-7), nullable
    occupancy_city      Int32                swimmer count (SSD-4), nullable
    hour                int8                 0–23 (CET/CEST local time)
    minute              int8                 0–59
    day_of_week         int8                 0=Mon … 6=Sun
    is_open_oerlikon    bool
    is_open_city        bool

Environment variables:
    AZURE_STORAGE_CONNECTION_STRING   Storage connection string (required)
    TABLE_NAME                        Table name (default: occupancy)
    PARQUET_CONTAINER_NAME            Blob container (default: occupancy-parquet)
"""

import io
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import azure.functions as func

logger = logging.getLogger("export_parquet")

_TZ = ZoneInfo("Europe/Zurich")

# Opening hours — keep in sync with dashboard_builder.py
_HOURS_OERLIKON: dict[int, tuple[int, int]] = {
    0: (6, 20), 1: (6, 20), 2: (6, 22), 3: (6, 20),
    4: (6, 22), 5: (6, 22), 6: (6, 22),
}
_HOURS_CITY: dict[int, tuple[int, int]] = {i: (6, 22) for i in range(7)}


def _is_open(dow: int, h: int, hours: dict) -> bool:
    open_h, close_h = hours.get(dow, (0, 0))
    return open_h <= h < close_h


def main(timer: func.TimerRequest) -> None:
    """Export yesterday's Table Storage rows to Parquet in Blob Storage."""
    yesterday = (datetime.now(_TZ) - timedelta(days=1)).date()
    logger.info(f"Starting Parquet export for {yesterday}")

    try:
        rows = _read_table_for_date(yesterday)
    except Exception as e:
        logger.error(f"Failed to read Table Storage: {e}", exc_info=True)
        raise

    if not rows:
        logger.warning(f"No rows found for {yesterday} — skipping export")
        return

    df = _build_dataframe(rows)
    _write_parquet(df, yesterday)
    logger.info(f"Exported {len(df)} rows for {yesterday}")


def _read_table_for_date(date) -> list[dict]:
    from azure.data.tables import TableServiceClient

    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING not set")

    table_name = os.getenv("TABLE_NAME", "occupancy")
    svc = TableServiceClient.from_connection_string(conn_str)
    table = svc.get_table_client(table_name)

    pk = date.isoformat()
    rows = []
    for entity in table.query_entities(f"PartitionKey eq '{pk}'"):
        rows.append({
            "timestamp": f"{entity['PartitionKey']}T{entity['RowKey']}",
            "occupancy_oerlikon": entity.get("occupancy_oerlikon"),
            "occupancy_city": entity.get("occupancy_city"),
        })

    rows.sort(key=lambda x: x["timestamp"])
    logger.info(f"Read {len(rows)} rows from table for {pk}")
    return rows


def _build_dataframe(rows: list[dict]):
    import pandas as pd

    df = pd.DataFrame(rows)

    # Parse timestamps as UTC (the raw strings are CET/CEST local, without tz info,
    # so we localise first then convert to UTC for the canonical stored column).
    df["timestamp"] = (
        pd.to_datetime(df["timestamp"])
        .dt.tz_localize(_TZ, ambiguous="infer", nonexistent="shift_forward")
        .dt.tz_convert("UTC")
    )

    # Local time components for feature engineering
    local_ts = df["timestamp"].dt.tz_convert(_TZ)
    df["hour"] = local_ts.dt.hour.astype("int8")
    df["minute"] = local_ts.dt.minute.astype("int8")
    df["day_of_week"] = local_ts.dt.dayofweek.astype("int8")

    # Nullable integer types preserve None/NaN correctly in Parquet
    df["occupancy_oerlikon"] = pd.array(df["occupancy_oerlikon"], dtype="Int32")
    df["occupancy_city"] = pd.array(df["occupancy_city"], dtype="Int32")

    # Opening hours flags — useful as ready-made features for ML models
    df["is_open_oerlikon"] = df.apply(
        lambda r: _is_open(int(r["day_of_week"]), int(r["hour"]), _HOURS_OERLIKON),
        axis=1,
    )
    df["is_open_city"] = df.apply(
        lambda r: _is_open(int(r["day_of_week"]), int(r["hour"]), _HOURS_CITY),
        axis=1,
    )

    return df


def _write_parquet(df, date) -> None:
    from azure.storage.blob import BlobServiceClient

    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    container = os.getenv("PARQUET_CONTAINER_NAME", "occupancy-parquet")
    blob_path = (
        f"year={date.year}/month={date.month:02d}/day={date.day:02d}/occupancy.parquet"
    )

    buf = io.BytesIO()
    df.to_parquet(buf, index=False, compression="snappy", engine="pyarrow")
    size = buf.tell()
    buf.seek(0)

    svc = BlobServiceClient.from_connection_string(conn_str)
    blob = svc.get_blob_client(container=container, blob=blob_path)
    blob.upload_blob(buf, overwrite=True)

    logger.info(f"Written {size:,} bytes → {container}/{blob_path}")
