"""
v2 dashboard — mobile-first status card.

Routes:
    GET /                        — redirect to /pool/oerlikon
    GET /pool/{location}         — HTML shell (Jinja template)
    GET /api/v2/status?location  — JSON payload for the card
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter()

_TZ = ZoneInfo("Europe/Zurich")

_HOURS_OERLIKON: dict[int, tuple[int, int]] = {
    0: (6, 20),
    1: (6, 20),
    2: (6, 22),
    3: (6, 20),
    4: (6, 22),
    5: (6, 22),
    6: (6, 22),
}
_HOURS_CITY: dict[int, tuple[int, int]] = {i: (6, 22) for i in range(7)}

_LOCATION_HOURS = {"oerlikon": _HOURS_OERLIKON, "city": _HOURS_CITY}
_LOCATION_LABEL = {"oerlikon": "Hallenbad Oerlikon", "city": "Hallenbad City"}


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home() -> RedirectResponse:
    return RedirectResponse("/pool/oerlikon", status_code=302)


@router.get("/pool/{location}", response_class=HTMLResponse, include_in_schema=False)
async def pool_page(request: Request, location: str):
    if location not in _LOCATION_HOURS:
        return RedirectResponse("/pool/oerlikon", status_code=302)

    return request.app.state.templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "location": location,
            "label": _LOCATION_LABEL[location],
        },
    )


@router.get("/api/v2/status")
async def status(
    request: Request,
    location: str = Query(default="oerlikon", pattern="^(oerlikon|city)$"),
) -> JSONResponse:
    pool = request.app.state.pool
    col = f"occupancy_{location}"
    now = datetime.now(_TZ)
    dow = now.weekday()
    hour = now.hour
    quarter = now.minute // 15

    open_h, close_h = _LOCATION_HOURS[location][dow]
    is_open = open_h <= hour < close_h

    # 1. Current — average of the last 5 minutes (smoothes WebSocket jitter)
    current_row = await pool.fetchrow(
        f"""
        SELECT ROUND(AVG({col})::numeric, 1) AS avg
        FROM occupancy
        WHERE ts >= NOW() - INTERVAL '5 minutes'
          AND {col} IS NOT NULL
        """
    )

    # 2. Typical — same weekday + same 15-min slot, full history
    typical_row = await pool.fetchrow(
        f"""
        SELECT
          ROUND(AVG({col})::numeric, 1) AS avg,
          ROUND(STDDEV({col})::numeric, 1) AS std
        FROM occupancy
        WHERE EXTRACT(DOW FROM ts AT TIME ZONE 'Europe/Zurich')::int = $1
          AND EXTRACT(HOUR FROM ts AT TIME ZONE 'Europe/Zurich')::int = $2
          AND (EXTRACT(MINUTE FROM ts AT TIME ZONE 'Europe/Zurich')::int / 15) = $3
          AND {col} IS NOT NULL
        """,
        dow, hour, quarter,
    )

    # 3. Best window today — lowest historical 15-min slot still ahead of us
    best = None
    if is_open:
        current_slot_min = hour * 60 + quarter * 15
        # leave 30 min for a swim before close
        best_row = await pool.fetchrow(
            f"""
            WITH slots AS (
              SELECT
                (EXTRACT(HOUR FROM ts AT TIME ZONE 'Europe/Zurich')::int * 60
                  + (EXTRACT(MINUTE FROM ts AT TIME ZONE 'Europe/Zurich')::int / 15) * 15
                ) AS slot_min,
                AVG({col})::numeric AS avg
              FROM occupancy
              WHERE EXTRACT(DOW FROM ts AT TIME ZONE 'Europe/Zurich')::int = $1
                AND {col} IS NOT NULL
              GROUP BY slot_min
            )
            SELECT slot_min, ROUND(avg, 1) AS avg
            FROM slots
            WHERE slot_min >= $2 AND slot_min <= $3
            ORDER BY avg ASC
            LIMIT 1
            """,
            dow, current_slot_min, close_h * 60 - 30,
        )
        if best_row:
            sm = int(best_row["slot_min"])
            best = {
                "start": f"{sm // 60:02d}:{sm % 60:02d}",
                "avg": float(best_row["avg"]),
            }

    # 4. Today's sparkline — 15-min buckets from local midnight to now
    sparkline_rows = await pool.fetch(
        f"""
        SELECT
          time_bucket(INTERVAL '15 minutes', ts) AS bucket,
          ROUND(AVG({col})::numeric, 1) AS avg
        FROM occupancy
        WHERE ts >= date_trunc('day', NOW() AT TIME ZONE 'Europe/Zurich')
                    AT TIME ZONE 'Europe/Zurich'
          AND ts <= NOW()
          AND {col} IS NOT NULL
        GROUP BY bucket
        ORDER BY bucket
        """
    )
    sparkline = [
        {
            "t": r["bucket"].astimezone(_TZ).strftime("%H:%M"),
            "v": float(r["avg"]) if r["avg"] is not None else None,
        }
        for r in sparkline_rows
    ]

    return JSONResponse(
        {
            "now": now.strftime("%H:%M"),
            "current": float(current_row["avg"]) if current_row["avg"] is not None else None,
            "typical": {
                "avg": float(typical_row["avg"]) if typical_row and typical_row["avg"] is not None else None,
                "std": float(typical_row["std"]) if typical_row and typical_row["std"] is not None else None,
            },
            "status": {
                "is_open": is_open,
                "open_h": open_h,
                "close_h": close_h,
            },
            "best": best,
            "sparkline": sparkline,
        },
        headers={"Cache-Control": "public, max-age=30"},
    )
