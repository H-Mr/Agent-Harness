"""Default observability backend — in-memory pub-sub, no persistence."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from llm_harness.adapters.observability.backend import EventHandler, ObservabilityBackend

logger = logging.getLogger(__name__)


class DefaultObservabilityBackend:
    """In-memory event bus — emit, subscribe, unsubscribe.

    No persistence by default.  To persist events, provide *on_emit* callback::

        backend = DefaultObservabilityBackend(
            on_emit=lambda event_type, payload: db.insert(...)
        )
    """

    def __init__(self, *, on_emit: EventHandler | None = None):
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._on_emit = on_emit

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            for handler in self._subscribers.get(event_type, []):
                try:
                    await handler(event_type, payload)
                except Exception:
                    logger.debug("Event handler failed", exc_info=True)
            if self._on_emit:
                try:
                    await self._on_emit(event_type, payload)
                except Exception:
                    logger.debug("on_emit callback failed", exc_info=True)
        except Exception:
            logger.debug("emit failed", exc_info=True)

    async def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    async def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        handlers = self._subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
