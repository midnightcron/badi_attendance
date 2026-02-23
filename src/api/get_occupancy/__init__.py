"""
Azure Function: HTTP API for occupancy data.

GET /api/occupancy?days=7&resolution=5min

Returns aggregated occupancy data from blob storage CSVs.
Supports date-range queries and downsampling for dashboard use.
"""

import azure.functions as func
import csv
import io
import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("get_occupancy")


def main(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP GET /api/occupancy

    Query params:
        days        - Number of days to look back (default: 7, max: 30)
        resolution  - Aggregation: 'raw', '5min' (default), '1hour', '1day'
        date        - Specific date YYYY-MM-DD (overrides days)

    Returns:
        JSON array of {timestamp, occupancy, [min, max]} objects
    """
    try:
        # Parse query params
        days = min(int(req.params.get("days", "7")), 30)
        resolution = req.params.get("resolution", "5min")
        specific_date = req.params.get("date")

        if resolution not in ("raw", "5min", "1hour", "1day"):
            return _json_response(
                {"error": f"Invalid resolution: {resolution}. "
                 "Use: raw, 5min, 1hour, 1day"},
                status_code=400,
            )

        # Determine date range
        if specific_date:
            try:
                start_date = datetime.strptime(specific_date, "%Y-%m-%d")
                end_date = start_date + timedelta(days=1)
            except ValueError:
                return _json_response(
                    {"error": f"Invalid date format: {specific_date}. Use YYYY-MM-DD"},
                    status_code=400,
                )
        else:
            end_date = datetime.now(timezone.utc).replace(tzinfo=None)
            start_date = end_date - timedelta(days=days)

        # Read data from blobs
        raw_data = _read_blobs(start_date, end_date)

        if not raw_data:
            return _json_response({
                "data": [],
                "meta": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "resolution": resolution,
                    "count": 0,
                },
            })

        # Aggregate based on resolution
        if resolution == "raw":
            data = raw_data
        elif resolution == "5min":
            data = _aggregate(raw_data, minutes=5)
        elif resolution == "1hour":
            data = _aggregate(raw_data, minutes=60)
        elif resolution == "1day":
            data = _aggregate(raw_data, minutes=1440)

        return _json_response({
            "data": data,
            "meta": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "resolution": resolution,
                "count": len(data),
                "raw_readings": len(raw_data),
            },
        })

    except Exception as e:
        logger.error(f"Error in get_occupancy: {e}", exc_info=True)
        return _json_response(
            {"error": "Internal server error", "message": str(e)},
            status_code=500,
        )


def _get_blob_service_client():
    """Get a BlobServiceClient using configured connection string."""
    from azure.storage.blob import BlobServiceClient

    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        aws = os.getenv("AzureWebJobsStorage", "")
        if aws and aws != "UseDevelopmentStorage=true":
            conn_str = aws

    if not conn_str:
        raise ValueError("No storage connection string configured")

    return BlobServiceClient.from_connection_string(conn_str)


def _read_blobs(start_date: datetime, end_date: datetime) -> list:
    """
    Read all CSV blobs in the date range.

    Blob naming convention: YYYY-MM-DD/occupancy_HH_MM.csv
    Each CSV has: timestamp,occupancy
    """
    container_name = os.getenv("BLOB_CONTAINER_NAME", "occupancy-data")
    blob_service = _get_blob_service_client()
    container_client = blob_service.get_container_client(container_name)

    all_readings = []
    current_date = start_date.date()
    end_date_only = end_date.date()

    while current_date <= end_date_only:
        prefix = current_date.strftime("%Y-%m-%d/")
        logger.info(f"Scanning blobs with prefix: {prefix}")

        try:
            blobs = container_client.list_blobs(name_starts_with=prefix)
            for blob in blobs:
                try:
                    blob_client = container_client.get_blob_client(blob.name)
                    content = blob_client.download_blob().readall().decode("utf-8")

                    reader = csv.DictReader(io.StringIO(content))
                    for row in reader:
                        ts_str = row.get("timestamp", "")
                        occ_str = row.get("occupancy", "")
                        if ts_str and occ_str:
                            all_readings.append({
                                "timestamp": ts_str,
                                "occupancy": int(float(occ_str)),
                            })
                except Exception as e:
                    logger.warning(
                        f"Failed to read blob {blob.name}: {e}"
                    )
        except Exception as e:
            logger.warning(f"Failed to list blobs for {prefix}: {e}")

        current_date += timedelta(days=1)

    # Sort by timestamp
    all_readings.sort(key=lambda x: x["timestamp"])
    return all_readings


def _aggregate(readings: list, minutes: int) -> list:
    """
    Aggregate raw readings into time buckets.

    For each bucket, compute avg, min, max occupancy.
    Timestamp is set to the bucket start.
    """
    if not readings:
        return []

    bucket_seconds = minutes * 60
    buckets = {}

    for r in readings:
        try:
            # Parse ISO timestamp (handle both with/without microseconds)
            ts_str = r["timestamp"]
            if "." in ts_str:
                ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S.%f")
            else:
                ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")

            # Floor to bucket boundary
            epoch = ts.timestamp()
            bucket_epoch = (int(epoch) // bucket_seconds) * bucket_seconds
            bucket_key = datetime.utcfromtimestamp(bucket_epoch).isoformat()

            if bucket_key not in buckets:
                buckets[bucket_key] = []
            buckets[bucket_key].append(r["occupancy"])

        except (ValueError, KeyError) as e:
            logger.debug(f"Skipping reading: {e}")
            continue

    # Build aggregated output
    result = []
    for bucket_ts in sorted(buckets.keys()):
        values = buckets[bucket_ts]
        result.append({
            "timestamp": bucket_ts,
            "occupancy": round(sum(values) / len(values), 1),
            "min": min(values),
            "max": max(values),
            "readings": len(values),
        })

    return result


def _json_response(data: dict, status_code: int = 200) -> func.HttpResponse:
    """Build a JSON HTTP response with CORS headers."""
    return func.HttpResponse(
        json.dumps(data),
        status_code=status_code,
        mimetype="application/json",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET",
            "Cache-Control": "public, max-age=60",
        },
    )
