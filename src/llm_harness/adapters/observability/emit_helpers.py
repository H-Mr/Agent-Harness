"""Helper to safely emit observability events from any module.

Usage:
    from llm_harness.adapters.observability.emit_helpers import emit_event
    emit_event(SessionOpened(session_key="cli:test"))
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def emit_event(event: object) -> None:
    """Push an event to the global EventBus. Fire-and-forget — never raises.

    No-op when no bus is available (global bus not created yet).
    """
    try:
        from llm_harness.adapters.observability.bus import emit as _emit
    except ImportError:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_emit(event))
