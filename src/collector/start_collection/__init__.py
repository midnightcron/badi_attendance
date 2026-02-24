"""HTTP endpoint to check status or manually (re)start the orchestrator."""

import json
import logging

import azure.functions as func
import azure.durable_functions as df

_INSTANCE_ID = "collector_singleton"
logger = logging.getLogger("start_collection")


async def main(req: func.HttpRequest, starter: str) -> func.HttpResponse:
    client = df.DurableOrchestrationClient(starter)
    status = await client.get_status(_INSTANCE_ID)

    # GET → return current status
    if req.method == "GET":
        if status:
            body = {
                "instance_id": _INSTANCE_ID,
                "runtime_status": str(status.runtime_status),
                "last_updated": str(status.last_updated_time),
            }
        else:
            body = {"instance_id": _INSTANCE_ID, "runtime_status": "not_found"}
        return func.HttpResponse(
            json.dumps(body), mimetype="application/json"
        )

    # POST → (re)start
    if status and status.runtime_status in (
        df.OrchestrationRuntimeStatus.Running,
        df.OrchestrationRuntimeStatus.Pending,
    ):
        await client.terminate(_INSTANCE_ID, "Manual restart via HTTP")
        logger.info("Terminated existing orchestrator for restart")
        # Purge old instance so the ID can be reused immediately
        await client.purge_instance_history(_INSTANCE_ID)

    await client.start_new("collection_orchestrator", _INSTANCE_ID, None)
    logger.info(f"Started orchestrator: {_INSTANCE_ID}")
    return func.HttpResponse(
        json.dumps({"status": "started", "instance_id": _INSTANCE_ID}),
        mimetype="application/json",
        status_code=202,
    )
