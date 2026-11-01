"""Periodic liveness line so a quiet container log still proves the app is alive."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 600


async def run_heartbeat(snapshot, interval: float = HEARTBEAT_INTERVAL_SECONDS) -> None:
    """Logs one line per interval with the health state returned by ``snapshot``.

    ``snapshot`` is a zero-argument callable returning the /health payload.  A
    failing snapshot must not kill the task: the next tick tries again.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            state = snapshot()
        except Exception:
            logger.exception("Heartbeat snapshot failed.")
            continue
        logger.info(
            "[HEARTBEAT] status=%s polling=%s telegram=%s",
            state.get("status"),
            state.get("polling"),
            state.get("telegram_connected"),
        )
