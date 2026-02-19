import azure.functions as func


def main(req: func.HttpRequest) -> func.HttpResponse:
    """Minimal test to verify function runtime works."""
    return func.HttpResponse(
        "OK - Runtime is working!",
        status_code=200
    )
