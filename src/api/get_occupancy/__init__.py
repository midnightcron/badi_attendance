"""
Azure Function: HTTP API for occupancy data.

GET /api/occupancy?days=7&resolution=5min

Returns aggregated occupancy data from blob storage CSVs.
Supports date-range queries and downsampling for dashboard use.
"""

import azure.functions as func
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Europe/Zurich")

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
            end_date = datetime.now(_TZ).replace(tzinfo=None)
            start_date = end_date - timedelta(days=days)

        # Read data from Table Storage
        raw_data = _read_table(start_date, end_date)

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


def _read_table(start_date: datetime, end_date: datetime) -> list:
    """
    Read occupancy rows from Azure Table Storage for the given date range.

    Each entity has PartitionKey (date), RowKey (time), occupancy_oerlikon, occupancy_city.
    """
    from azure.data.tables import TableServiceClient

    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        aws = os.getenv("AzureWebJobsStorage", "")
        if aws and aws != "UseDevelopmentStorage=true":
            conn_str = aws
    if not conn_str:
        raise ValueError("No storage connection string configured")

    table_name = os.getenv("TABLE_NAME", "occupancy")
    svc = TableServiceClient.from_connection_string(conn_str)
    table = svc.get_table_client(table_name)

    all_readings = []
    current_date = start_date.date()
    end_date_only = end_date.date()

    while current_date <= end_date_only:
        pk = current_date.isoformat()
        logger.info(f"Querying table for PartitionKey={pk}")
        try:
            for e in table.query_entities(f"PartitionKey eq '{pk}'"):
                ts = f"{e['PartitionKey']}T{e['RowKey']}"
                all_readings.append({
                    "timestamp": ts,
                    "occupancy_oerlikon": e.get("occupancy_oerlikon"),
                    "occupancy_city": e.get("occupancy_city"),
                })
        except Exception as ex:
            logger.warning(f"Failed to query table for {pk}: {ex}")
        current_date += timedelta(days=1)

    all_readings.sort(key=lambda x: x["timestamp"])
    return all_readings


def _aggregate(readings: list, minutes: int) -> list:
    """
    Aggregate raw readings into time buckets.

    For each bucket, compute avg, min, max for both occupancy columns.
    Timestamp is set to the bucket start.
    """
    if not readings:
        return []

    bucket_seconds = minutes * 60
    buckets: dict[str, dict] = {}

    for r in readings:
        try:
            ts_str = r["timestamp"]
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is not None:
                ts = ts.astimezone(_TZ).replace(tzinfo=None)

            epoch = ts.timestamp()
            bucket_epoch = (int(epoch) // bucket_seconds) * bucket_seconds
            bucket_key = datetime.fromtimestamp(
                bucket_epoch, tz=_TZ
            ).strftime("%Y-%m-%dT%H:%M:%S")

            if bucket_key not in buckets:
                buckets[bucket_key] = {"oerlikon": [], "city": []}

            occ_o = r.get("occupancy_oerlikon")
            occ_c = r.get("occupancy_city")
            if occ_o is not None:
                buckets[bucket_key]["oerlikon"].append(int(occ_o))
            if occ_c is not None:
                buckets[bucket_key]["city"].append(int(occ_c))

        except (ValueError, KeyError) as e:
            logger.debug(f"Skipping reading: {e}")
            continue

    result = []
    for bucket_ts in sorted(buckets.keys()):
        o = buckets[bucket_ts]["oerlikon"]
        c = buckets[bucket_ts]["city"]
        entry: dict = {"timestamp": bucket_ts, "readings": max(len(o), len(c))}
        if o:
            entry["occupancy_oerlikon"] = round(sum(o) / len(o), 1)
            entry["occupancy_oerlikon_min"] = min(o)
            entry["occupancy_oerlikon_max"] = max(o)
        if c:
            entry["occupancy_city"] = round(sum(c) / len(c), 1)
            entry["occupancy_city_min"] = min(c)
            entry["occupancy_city_max"] = max(c)
        result.append(entry)

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
