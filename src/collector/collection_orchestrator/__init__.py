"""Durable Functions orchestrator: eternal collection loop.

Runs forever (via continue_as_new) collecting data every 5 minutes.
Each iteration:
    1. Call collect_activity (runs ~296 s)
    2. Create a timer until 300 s after the cycle started
    3. continue_as_new → history stays at 3 events, never grows
"""

import azure.durable_functions as df
from datetime import timedelta

_CYCLE_SECONDS = 300  # 5 minutes between collection starts


def orchestrator_function(context: df.DurableOrchestrationContext):
    cycle_start = context.current_utc_datetime

    # Perform one collection cycle (~296 s)
    yield context.call_activity("collect_activity", "")

    # Wait until 5 min after the cycle started
    next_start = cycle_start + timedelta(seconds=_CYCLE_SECONDS)
    if context.current_utc_datetime < next_start:
        yield context.create_timer(next_start)

    # Restart with clean history — prevents unbounded replay growth
    context.continue_as_new(None)


main = df.Orchestrator.create(orchestrator_function)
