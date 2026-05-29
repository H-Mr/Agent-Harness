"""Helper to emit structured events via an ObservabilityBackend instance.

Usage::

    from llm_harness.adapters.observability.emit_helpers import EventEmitter
    emitter = EventEmitter(backend)
    emitter.send(SessionOpened(session_key="alice:chat1"))
"""

from __future__ import annotations

import logging
from typing import Any

from llm_harness.adapters.observability.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ErrorEvent,
    MemoryConsolidated,
    SessionClosed,
    SessionOpened,
    SubagentCompleted,
    SubagentSpawned,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)

logger = logging.getLogger(__name__)

_EVENT_TYPE_MAP: dict[type, str] = {
    AssistantTextDelta:     "assistant:delta",
    AssistantTurnComplete:  "assistant:complete",
    ToolExecutionStarted:   "tool:executing",
    ToolExecutionCompleted: "tool:completed",
    ErrorEvent:             "error",
    SessionOpened:          "session:opened",
    SessionClosed:          "session:closed",
    SubagentSpawned:        "agent:spawned",
    SubagentCompleted:      "agent:completed",
    MemoryConsolidated:     "memory:consolidated",
}


class EventEmitter:
    """Wraps an ``ObservabilityBackend`` with typed event methods."""

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    async def send(self, event: object) -> None:
        event_type = _EVENT_TYPE_MAP.get(type(event), event.__class__.__name__)
        payload = _to_dict(event)
        try:
            await self._backend.emit(event_type, payload)
        except Exception:
            logger.debug("emit failed for %s", event_type, exc_info=True)

    # -- convenience methods -------------------------------------------

    async def tool_executing(self, name: str, args: dict) -> None:
        await self.send(ToolExecutionStarted(tool_name=name, tool_input=args))

    async def tool_completed(self, name: str, output: str, is_error: bool = False) -> None:
        await self.send(ToolExecutionCompleted(tool_name=name, output=output, is_error=is_error))


def _to_dict(event: object) -> dict:
    data = {}
    for field_name in event.__dataclass_fields__:
        data[field_name] = getattr(event, field_name)
    return data
