"""Tests for the periodic heartbeat line."""

import asyncio
import logging

import pytest

from src.heartbeat import run_heartbeat


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_heartbeat_logs_health_state(caplog):
    """A healthy service emits a readable line on every tick."""
    caplog.set_level(logging.INFO)
    state = {"status": "ok", "polling": True, "telegram_connected": True}

    task = asyncio.create_task(run_heartbeat(lambda: state, interval=0.01))
    await asyncio.sleep(0.05)
    await _stop(task)

    lines = [r.getMessage() for r in caplog.records if "[HEARTBEAT]" in r.getMessage()]
    assert len(lines) >= 2
    assert lines[0] == "[HEARTBEAT] status=ok polling=True telegram=True"


@pytest.mark.asyncio
async def test_heartbeat_survives_a_failing_snapshot(caplog):
    """A broken snapshot must not kill the loop or lose later heartbeats."""
    caplog.set_level(logging.INFO)
    calls = {"count": 0}

    def snapshot():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return {"status": "degraded", "polling": False, "telegram_connected": False}

    task = asyncio.create_task(run_heartbeat(snapshot, interval=0.01))
    await asyncio.sleep(0.06)
    await _stop(task)

    messages = [record.getMessage() for record in caplog.records]
    assert any("Heartbeat snapshot failed" in message for message in messages)
    assert "[HEARTBEAT] status=degraded polling=False telegram=False" in messages
