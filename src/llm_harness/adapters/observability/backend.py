"""ObservabilityBackend Protocol."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

EventPayload = dict[str, Any]
EventHandler = Callable[[str, EventPayload], Awaitable[None]]


@runtime_checkable
class ObservabilityBackend(Protocol):
    async def emit(self, event_type: str, payload: EventPayload) -> None: ...
    async def subscribe(self, event_type: str, handler: EventHandler) -> None: ...
    async def unsubscribe(self, event_type: str, handler: EventHandler) -> None: ...
