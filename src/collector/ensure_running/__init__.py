"""Self-healing timer: ensures the collection orchestrator is always running.

Fires every 10 minutes (and on startup after deployment / instance recycle).
If the orchestrator isn't running, it starts a new singleton instance.
"""

import logging

import azure.functions as func
import azure.durable_functions as df

_INSTANCE_ID = "collector_singleton"
logger = logging.getLogger("ensure_running")


async def main(mytimer: func.TimerRequest, starter: str) -> None:
    client = df.DurableOrchestrationClient(starter)

    status = await client.get_status(_INSTANCE_ID)

    if status and status.runtime_status in (
        df.OrchestrationRuntimeStatus.Running,
        df.OrchestrationRuntimeStatus.Pending,
    ):
        logger.info(
            f"Orchestrator already active "
            f"(status={status.runtime_status})"
        )
        return

    reason = "not found" if status is None else str(status.runtime_status)
    logger.warning(
        f"Orchestrator not running ({reason}) — starting new instance"
    )
    await client.start_new(
        "collection_orchestrator", _INSTANCE_ID, None
    )
    logger.info(f"Started orchestrator: {_INSTANCE_ID}")
