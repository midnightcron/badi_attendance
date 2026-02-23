"""
Azure Function: Serve the occupancy dashboard as a single-page HTML app.

GET /api/dashboard → Returns the full HTML page with embedded JS/CSS.

This keeps everything self-contained: no separate static hosting needed.
The page fetches data from the sibling /api/occupancy endpoint.
"""

import azure.functions as func
import os

# Read HTML at module load (cold start only)
_html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")


def main(req: func.HttpRequest) -> func.HttpResponse:
    """Serve the dashboard HTML page."""
    try:
        with open(_html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        return func.HttpResponse(
            html_content,
            status_code=200,
            mimetype="text/html",
        )
    except FileNotFoundError:
        return func.HttpResponse(
            "<h1>Dashboard not found</h1><p>dashboard.html is missing.</p>",
            status_code=500,
            mimetype="text/html",
        )
