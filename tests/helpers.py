from __future__ import annotations

import asyncio


async def wait_for_run(manager, run_id: str, timeout: float = 8.0, statuses: set[str] | None = None):
    statuses = statuses or {"completed", "failed", "awaiting_approval", "awaiting_user_input"}
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        run = manager.storage.find_run(run_id)
        if run.status.value in statuses:
            return run
        await asyncio.sleep(0.05)
    raise TimeoutError(run_id)
