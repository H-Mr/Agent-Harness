"""Helper to safely emit observability events from any module.

Usage:
    from agent_harness.observability.emit_helpers import emit_event
    emit_event(SessionOpened(session_key="cli:test"))
"""

from __future__ import annotations

import asyncio


def emit_event(event: object) -> None:
    """Push an event to the global EventBus. Fire-and-forget — never raises.

    No-op when no tracker is active (global bus not created yet).
    """
    try:
        from agent_harness.observability.bus import emit as _emit
    except ImportError:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_emit(event))
