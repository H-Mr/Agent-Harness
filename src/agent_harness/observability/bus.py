"""Global event bus — all modules push events here, consumers drain from here."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

Listener = Callable[[object], Awaitable[None]]


class EventBus:
    """Async-buffered event bus. Thread-safe via asyncio.Queue.

    Any module calls ``emit(event)``. Consumers call ``subscribe(fn)`` to
    receive every event, or drain manually via ``consume()``.
    """

    def __init__(self, maxsize: int = 4096):
        self._queue: asyncio.Queue[object] = asyncio.Queue(maxsize=maxsize)
        self._listeners: list[Listener] = []

    async def emit(self, event: object) -> None:
        """Push an event. Drops silently when queue is full (never blocks the caller)."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.debug("EventBus queue full, dropping event: %s", type(event).__name__)
            return
        for listener in self._listeners:
            try:
                await listener(event)
            except Exception:
                logger.debug("EventBus listener failed", exc_info=True)

    async def consume(self) -> object:
        """Block until an event is available. For poll-based consumers."""
        return await self._queue.get()

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Register a real-time listener. Returns unsubscribe function."""
        self._listeners.append(listener)

        def _unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _unsubscribe

    @property
    def pending(self) -> int:
        return self._queue.qsize()


# Global singleton — import and use from any module
_GLOBAL_BUS: EventBus | None = None


def get_event_bus() -> EventBus:
    """Return the global EventBus singleton, creating it on first call."""
    global _GLOBAL_BUS
    if _GLOBAL_BUS is None:
        _GLOBAL_BUS = EventBus()
    return _GLOBAL_BUS


def is_active() -> bool:
    """Return True if there is at least one subscriber or tracker attached."""
    return _GLOBAL_BUS is not None


async def emit(event: object) -> None:
    """Convenience: emit to global bus. No-op if no tracker is active."""
    if _GLOBAL_BUS is None:
        return  # silently skip — no consumer attached
    await _GLOBAL_BUS.emit(event)
