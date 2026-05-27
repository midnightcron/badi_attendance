from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from db import fetch_occupancy

router = APIRouter()

_TZ = ZoneInfo("Europe/Zurich")

_RESOLUTION_MINUTES: dict[str, int | None] = {
    "raw":   None,
    "5min":  5,
    "15min": 15,
    "1hour": 60,
    "1day":  1440,
}


@router.get("/occupancy")
async def get_occupancy(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    resolution: str = Query(default="15min"),
    date: str | None = Query(default=None, description="YYYY-MM-DD — overrides days"),
    location: str = Query(default="oerlikon", pattern="^(oerlikon|city)$"),
) -> JSONResponse:
    if resolution not in _RESOLUTION_MINUTES:
        return JSONResponse(
            {"error": f"Invalid resolution '{resolution}'. Use: {', '.join(_RESOLUTION_MINUTES)}"},
            status_code=400,
        )

    if date:
        try:
            start_dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=_TZ)
            end_dt = start_dt + timedelta(days=1)
        except ValueError:
            return JSONResponse(
                {"error": f"Invalid date format: {date!r}. Use YYYY-MM-DD"},
                status_code=400,
            )
    else:
        end_dt = datetime.now(_TZ)
        start_dt = end_dt - timedelta(days=days)

    pool = request.app.state.pool
    try:
        data = await fetch_occupancy(
            pool,
            start_dt,
            end_dt,
            _RESOLUTION_MINUTES[resolution],
            location,
        )
    except Exception as e:
        return JSONResponse({"error": "Internal server error", "detail": str(e)}, status_code=500)

    return JSONResponse(
        {
            "data": data,
            "meta": {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "resolution": resolution,
                "location": location,
                "count": len(data),
            },
        },
        headers={"Cache-Control": "public, max-age=60"},
    )
