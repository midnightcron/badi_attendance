"""
v2 dashboard — predictions-first home page.

The value-add is *when to go*, not the current number.

Routes:
    GET /                        — redirect to /pool/oerlikon
    GET /pool/{location}         — HTML shell (Jinja template)
    GET /api/v2/status?location  — JSON: status pill, today pattern + best,
                                   next-7-days best
"""

from __future__ import annotations

from datetime import datetime, timedelta
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

_DOW_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home() -> RedirectResponse:
    return RedirectResponse("/pool/oerlikon", status_code=302)


@router.get(
    "/pool/{location}",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def pool_page(request: Request, location: str):
    if location not in _LOCATION_HOURS:
        return RedirectResponse("/pool/oerlikon", status_code=302)

    return request.app.state.templates.TemplateResponse(
        request,
        "home.html",
        {
            "location": location,
            "label": _LOCATION_LABEL[location],
        },
    )


def _slot_label(slot_min: int) -> str:
    return f"{slot_min // 60:02d}:{slot_min % 60:02d}"


def _candidate_30min_windows(slots, min_slot, max_start):
    """All 30-min windows (2 consecutive 15-min slots) sorted by avg ASC."""
    by_min = {s["slot_min"]: s["typical"] for s in slots}
    out = []
    for sm, t1 in by_min.items():
        if sm < min_slot or sm > max_start:
            continue
        t2 = by_min.get(sm + 15)
        if t2 is None:
            continue
        avg = round((t1 + t2) / 2, 1)
        out.append(
            {
                "t_start": _slot_label(sm),
                "t_end": _slot_label(sm + 30),
                "slot_min": sm,
                "avg": avg,
            }
        )
    out.sort(key=lambda x: (x["avg"], x["slot_min"]))
    return out


def _pick_non_overlapping(candidates, n, min_gap=60):
    """From candidates (sorted by avg), pick top-n with starts ≥ min_gap apart."""
    picks = []
    for c in candidates:
        if any(abs(c["slot_min"] - p["slot_min"]) < min_gap for p in picks):
            continue
        picks.append(c)
        if len(picks) == n:
            break
    return picks


@router.get("/api/v2/status")
async def status(
    request: Request,
    location: str = Query(
        default="oerlikon", pattern="^(oerlikon|city)$"
    ),
) -> JSONResponse:
    pool = request.app.state.pool
    col_raw = f"occupancy_{location}"
    col_avg = f"avg_{location}"
    now = datetime.now(_TZ)
    dow = now.weekday()
    current_slot_min = now.hour * 60 + (now.minute // 15) * 15

    open_h, close_h = _LOCATION_HOURS[location][dow]
    is_open = open_h <= now.hour < close_h
    hours_map = _LOCATION_HOURS[location]

    # 1. Current (last 5 min avg)
    current_row = await pool.fetchrow(
        f"""
        SELECT ROUND(AVG({col_raw})::numeric, 1) AS avg
        FROM occupancy
        WHERE ts >= NOW() - INTERVAL '5 minutes'
          AND {col_raw} IS NOT NULL
        """
    )

    # 2. Full week of historical typical patterns from the CAGG
    #    (~672 rows, well under 100 ms)
    week_rows = await pool.fetch(
        f"""
        SELECT
          EXTRACT(DOW FROM bucket AT TIME ZONE 'Europe/Zurich')::int AS day,
          (EXTRACT(HOUR FROM bucket AT TIME ZONE 'Europe/Zurich')::int * 60
            + (EXTRACT(MINUTE FROM bucket AT TIME ZONE 'Europe/Zurich')::int
               / 15) * 15
          ) AS slot_min,
          ROUND(AVG({col_avg})::numeric, 1) AS typical
        FROM occupancy_15min
        GROUP BY day, slot_min
        """
    )

    # postgres DOW is Sunday=0..Saturday=6, Python is Monday=0..Sunday=6.
    # convert: py_dow = (pg_dow + 6) % 7
    week_patterns: dict[int, list[dict]] = {d: [] for d in range(7)}
    for r in week_rows:
        pg_dow = int(r["day"])
        py_dow = (pg_dow + 6) % 7
        oh, ch = hours_map[py_dow]
        sm = int(r["slot_min"])
        if not (oh * 60 <= sm < ch * 60):
            continue
        week_patterns[py_dow].append(
            {
                "slot_min": sm,
                "typical": float(r["typical"]) if r["typical"] is not None else 0.0,
            }
        )
    for d in range(7):
        week_patterns[d].sort(key=lambda x: x["slot_min"])

    # 3. Today's actual data so far (15-min buckets)
    today_actual_rows = await pool.fetch(
        f"""
        SELECT
          (EXTRACT(HOUR FROM ts AT TIME ZONE 'Europe/Zurich')::int * 60
            + (EXTRACT(MINUTE FROM ts AT TIME ZONE 'Europe/Zurich')::int
               / 15) * 15
          ) AS slot_min,
          ROUND(AVG({col_raw})::numeric, 1) AS avg
        FROM occupancy
        WHERE ts >= date_trunc('day', NOW() AT TIME ZONE 'Europe/Zurich')
                    AT TIME ZONE 'Europe/Zurich'
          AND ts <= NOW()
          AND {col_raw} IS NOT NULL
        GROUP BY slot_min
        ORDER BY slot_min
        """
    )
    actual_by_slot = {
        int(r["slot_min"]): float(r["avg"]) for r in today_actual_rows
    }

    # 4. Build today_pattern (typical + actual merged)
    today_pattern = []
    for s in week_patterns[dow]:
        sm = s["slot_min"]
        today_pattern.append(
            {
                "t": _slot_label(sm),
                "slot_min": sm,
                "typical": s["typical"],
                "actual": actual_by_slot.get(sm),
            }
        )

    # 5. Today's top 3 best 30-min windows — non-overlapping, anytime today
    #    after now and at least 30 min before close. Don't gate on
    #    is_open right now (pool may open later today).
    today_candidates = _candidate_30min_windows(
        week_patterns[dow],
        min_slot=current_slot_min,
        max_start=close_h * 60 - 30,
    )
    today_best = _pick_non_overlapping(today_candidates, n=3, min_gap=60)

    # 6. Week's top 5 best windows across the *other* days of the week
    #    (offset 1..6). Today is already covered in section 5; including it
    #    here would just duplicate. One quietest window per day.
    day_winners = []
    for offset in range(1, 7):
        target_date = now.date() + timedelta(days=offset)
        target_dow = target_date.weekday()
        oh, ch = hours_map[target_dow]
        candidates = _candidate_30min_windows(
            week_patterns[target_dow],
            min_slot=oh * 60,
            max_start=ch * 60 - 30,
        )
        if not candidates:
            continue
        w = dict(candidates[0])
        w["dow"] = target_dow
        w["date_offset"] = offset
        w["day_name"] = "Tomorrow" if offset == 1 else _DOW_SHORT[target_dow]
        day_winners.append(w)
    day_winners.sort(key=lambda x: (x["avg"], x["date_offset"]))
    week_best = day_winners[:5]

    def _f(row, key):
        if row is None:
            return None
        v = row[key]
        return float(v) if v is not None else None

    return JSONResponse(
        {
            "now": now.strftime("%H:%M"),
            "now_slot_min": current_slot_min,
            "current": _f(current_row, "avg"),
            "status": {
                "is_open": is_open,
                "open_h": open_h,
                "close_h": close_h,
            },
            "today_pattern": today_pattern,
            "today_best": today_best,
            "week_best": week_best,
        },
        headers={"Cache-Control": "public, max-age=30"},
    )
