"""
Azure Table Storage writer for occupancy readings.

Writes each reading as an individual row to Azure Table Storage,
providing immediate persistence (zero data loss on crash) and
efficient range queries by date.

Table schema:
    PartitionKey : str   – date "YYYY-MM-DD" (groups one day together)
    RowKey       : str   – time "HH:MM:SS.ffffff" (unique, sorted)
    occupancy    : int   – current fill count
    timestamp    : str   – full ISO-8601 timestamp with timezone
"""

import logging

from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceExistsError

logger = logging.getLogger(__name__)

_TABLE_NAME = "occupancy"


def get_table_client(connection_string: str, table_name: str = _TABLE_NAME):
    """
    Create a TableClient, ensuring the table exists.

    Call once at startup; reuse the returned client for all writes.
    """
    service = TableServiceClient.from_connection_string(connection_string)
    try:
        service.create_table(table_name)
        logger.info(f"Created table: {table_name}")
    except ResourceExistsError:
        pass

    return service.get_table_client(table_name)


def write_reading(table_client, reading: dict) -> None:
    """
    Write a single occupancy reading to Table Storage.

    Args:
        table_client: Azure TableClient instance.
        reading: {"occupancy": int, "timestamp": str}
                 where timestamp is ISO-8601 with timezone.

    The entity is keyed so that:
        - PartitionKey groups all readings for one calendar day
        - RowKey is the time portion, giving natural sort order
    """
    ts_str = reading["timestamp"]

    # Split "2026-02-27T14:03:07.123456+01:00" into date + time parts
    # Date part = everything before 'T'
    date_part = ts_str[:10]          # "2026-02-27"
    time_part = ts_str[11:26]        # "14:03:07.123456" (up to microseconds)

    # If the timestamp has no microseconds, pad to ensure uniqueness
    if len(time_part) < 15:
        time_part = time_part.ljust(15, "0")

    entity = {
        "PartitionKey": date_part,
        "RowKey": time_part,
        "occupancy": reading["occupancy"],
        # Full timestamp is reconstructable from PartitionKey + RowKey.
        # The system 'Timestamp' column (immutable) records write time.
    }

    table_client.upsert_entity(entity)
