import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health_check")
async def health_check(request: Request) -> JSONResponse:
    pool = request.app.state.pool
    try:
        await pool.fetchval("SELECT 1")
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    return JSONResponse({
        "status": "healthy" if db_status == "ok" else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db_status,
        "websocket_url": os.getenv("WEBSOCKET_URL", "not set"),
    })
