"""Track file writer — drains the EventBus and writes JSON Lines to disk.

Usage:
    from agent_harness.observability.tracker import Tracker

    tracker = Tracker(Path("~/.agent-harness/track.jsonl"))
    await tracker.start()  # begins background consumer task
    ...
    await tracker.stop()   # graceful drain + close
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from pathlib import Path

from agent_harness.observability.bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class Tracker:
    """Background consumer: drains EventBus → JSON Lines file.

    Uses the global EventBus by default. Pass ``bus=`` to use an isolated bus
    (useful in tests or multi-tenant deployments).
    """

    def __init__(self, file_path: str | Path, *, bus: EventBus | None = None):
        self._path = Path(file_path).expanduser()
        self._bus = bus  # None means "use global"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Launch the background consumer task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._drain())
        logger.info("Tracker started: %s", self._path)

    async def stop(self) -> None:
        """Signal the consumer to drain remaining events and exit."""
        self._running = False
        if self._task is not None:
            await self._task
            self._task = None
        logger.info("Tracker stopped: %s", self._path)

    async def _drain(self) -> None:
        bus = self._bus or get_event_bus()
        with open(self._path, "a", encoding="utf-8") as f:
            while self._running:
                try:
                    event = await asyncio.wait_for(bus.consume(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
                try:
                    line = _serialize(event)
                    f.write(line + "\n")
                    f.flush()
                except Exception:
                    logger.debug("Failed to serialize event", exc_info=True)


def _serialize(event: object) -> str:
    """Convert any dataclass event to a JSON line: {"type":"...","ts":"...","data":{...}}."""
    if dataclasses.is_dataclass(event) and not isinstance(event, type):
        d = dataclasses.asdict(event)
        ts = d.pop("timestamp", None)
        record = {
            "type": type(event).__name__,
            "ts": ts,
            "data": d,
        }
    else:
        record = {
            "type": type(event).__name__,
            "ts": None,
            "data": str(event),
        }
    return json.dumps(record, ensure_ascii=False, default=str)


async def start_tracker_from_config(config) -> Tracker | None:
    """Auto-start a Tracker if ``config.observability.track_file`` is set.

    Returns the Tracker instance, or None if tracking is not configured.
    """
    track_file = getattr(getattr(config, "observability", None), "track_file", None)
    if not track_file:
        return None
    tracker = Tracker(track_file)
    await tracker.start()
    return tracker
