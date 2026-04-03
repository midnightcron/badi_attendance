"""
Azure Function: Serve the occupancy dashboard.

GET /api/dashboard → Returns a Plotly-generated HTML page built entirely
in Python.  No hand-written HTML/JS — all charts come from
utils/dashboard_builder.py.
"""

import azure.functions as func
import logging

logger = logging.getLogger("serve_dashboard")


def main(req: func.HttpRequest) -> func.HttpResponse:
    """Build and return the Plotly dashboard."""
    try:
        from utils.dashboard_builder import build_dashboard_html

        days = min(int(req.params.get("days", "30")), 90)
        location = req.params.get("location", "oerlikon")
        html = build_dashboard_html(lookback_days=days, location=location)

        return func.HttpResponse(
            html,
            status_code=200,
            mimetype="text/html",
            headers={"Cache-Control": "public, max-age=300"},
        )

    except Exception as e:
        logger.error(f"Dashboard error: {e}", exc_info=True)
        return func.HttpResponse(
            f"<h1>Dashboard error</h1><pre>{e}</pre>",
            status_code=500,
            mimetype="text/html",
        )
