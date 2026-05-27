from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from db import fetch_readings
from dashboard_builder import build_dashboard_html

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(
    request: Request,
    days: int = Query(default=30, ge=1, le=90),
    location: str = Query(default="oerlikon", pattern="^(oerlikon|city)$"),
) -> HTMLResponse:
    pool = request.app.state.pool
    try:
        readings = await fetch_readings(pool, days)
        html = build_dashboard_html(readings, lookback_days=days, location=location)
        return HTMLResponse(html, headers={"Cache-Control": "public, max-age=300"})
    except Exception as e:
        return HTMLResponse(
            f"<h1>Dashboard error</h1><pre>{e}</pre>",
            status_code=500,
        )
