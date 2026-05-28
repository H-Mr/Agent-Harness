"""Default observability backend: in-memory EventBus + JSONL Tracker."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_harness.adapters.observability.backend import EventHandler, ObservabilityBackend

logger = logging.getLogger(__name__)


class DefaultObservabilityBackend:
    def __init__(self, track_dir: Path | None = None):
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._track_dir = Path(track_dir) if track_dir else None
        if self._track_dir:
            self._track_dir.mkdir(parents=True, exist_ok=True)
        self._track_lock = asyncio.Lock()

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            for handler in self._subscribers.get(event_type, []):
                try:
                    await handler(event_type, payload)
                except Exception:
                    logger.debug("Event handler failed", exc_info=True)
            if self._track_dir:
                async with self._track_lock:
                    with open(self._track_dir / "events.jsonl", "a", encoding="utf-8") as f:
                        f.write(json.dumps({"type": event_type, "payload": payload, "ts": datetime.now().isoformat()}, ensure_ascii=False, default=str) + "\n")
        except Exception:
            logger.debug("emit failed", exc_info=True)

    async def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    async def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        handlers = self._subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
