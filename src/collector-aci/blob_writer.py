"""
Async blob-storage writer for occupancy CSV files.

Writes buffered occupancy readings as CSV to Azure Blob Storage,
matching the existing naming convention used by the Functions collector:

    occupancy-data/
        YYYY-MM-DD/
            occupancy_HH_MM.csv
"""

import logging
from datetime import datetime

from azure.storage.blob import BlobServiceClient

logger = logging.getLogger(__name__)


async def write_csv_to_blob(
    updates: list[dict],
    window_start: datetime,
    connection_string: str,
    container_name: str = "occupancy-data",
) -> None:
    """
    Write occupancy readings to blob storage as CSV.

    Args:
        updates: List of {"occupancy": int, "timestamp": str} dicts.
        window_start: Start of the collection window (used for blob path).
        connection_string: Azure Storage connection string.
        container_name: Blob container name.
    """
    if not connection_string:
        logger.warning(
            "No AZURE_STORAGE_CONNECTION_STRING — skipping blob write"
        )
        return

    if not updates:
        logger.debug("No updates to write")
        return

    # Build blob path matching existing convention
    date_folder = window_start.strftime("%Y-%m-%d")
    blob_name = f"{date_folder}/{window_start.strftime('occupancy_%H_%M.csv')}"

    # Build CSV content
    csv_lines = ["timestamp,occupancy"]
    for entry in updates:
        csv_lines.append(f"{entry['timestamp']},{entry['occupancy']}")
    csv_content = "\n".join(csv_lines)

    # Upload (sync SDK — fine for small CSVs, avoids aiohttp dep)
    blob_service = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service.get_container_client(container_name)

    # Ensure container exists
    try:
        container_client.create_container()
        logger.info(f"Created container: {container_name}")
    except Exception:
        pass  # already exists

    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(csv_content, overwrite=True)

    logger.info(
        f"Wrote {len(updates)} readings → {container_name}/{blob_name}"
    )
