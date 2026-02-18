"""Simple HTTP function to verify Azure Functions runtime is working."""

import azure.functions as func
import json
import os
from datetime import datetime


def main(req: func.HttpRequest) -> func.HttpResponse:
    """Simple health check endpoint."""
    
    response_data = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "function": "health_check",
        "environment": {
            "WEBSOCKET_URL": os.getenv("WEBSOCKET_URL", "not set"),
            "TARGET_UID": os.getenv("TARGET_UID", "not set"),
            "AZURE_STORAGE_CONNECTION_STRING": "configured" if os.getenv("AZURE_STORAGE_CONNECTION_STRING") else "not set"
        }
    }
    
    return func.HttpResponse(
        json.dumps(response_data, indent=2),
        status_code=200,
        mimetype="application/json"
    )
