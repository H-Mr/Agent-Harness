"""Tests for DefaultObservabilityBackend -- in-memory event bus + JSONL tracker."""

import json
from pathlib import Path

import pytest

from llm_harness.adapters.observability.default import DefaultObservabilityBackend


class TestDefaultObservabilityBackend:
    """DefaultObservabilityBackend: subscribe/emit/unsubscribe, tracker file."""

    # ------------------------------------------------------------------
    # Subscription / notification
    # ------------------------------------------------------------------

    async def test_emit_notifies_subscribers_for_matching_event(self) -> None:
        """Emit must notify all subscribers registered for the same event type."""
        backend = DefaultObservabilityBackend()
        received: list[tuple[str, dict]] = []

        async def handler(event_type: str, payload: dict) -> None:
            received.append((event_type, payload))

        await backend.subscribe("user_message", handler)
        await backend.emit("user_message", {"text": "hello"})

        assert len(received) == 1
        assert received[0] == ("user_message", {"text": "hello"})

    async def test_emit_does_not_notify_wrong_event_type(self) -> None:
        """Subscribers for one event type must not be called for a different type."""
        backend = DefaultObservabilityBackend()
        received: list[tuple[str, dict]] = []

        async def handler(event_type: str, payload: dict) -> None:
            received.append((event_type, payload))

        await backend.subscribe("type_a", handler)
        await backend.emit("type_b", {"data": 1})

        assert len(received) == 0

    async def test_subscribe_unsubscribe_cycle(self) -> None:
        """After unsubscribing, a handler must not receive further events."""
        backend = DefaultObservabilityBackend()
        received: list[str] = []

        async def handler(event_type: str, payload: dict) -> None:
            received.append(payload.get("msg", ""))

        await backend.subscribe("test", handler)
        await backend.emit("test", {"msg": "first"})
        await backend.unsubscribe("test", handler)
        await backend.emit("test", {"msg": "second"})

        assert received == ["first"]

    async def test_multiple_subscribers_all_receive_event(self) -> None:
        """All subscribers for the same event type must be notified on emit."""
        backend = DefaultObservabilityBackend()
        results: list[str] = []

        async def handler_a(et: str, p: dict) -> None:
            results.append("a")

        async def handler_b(et: str, p: dict) -> None:
            results.append("b")

        await backend.subscribe("evt", handler_a)
        await backend.subscribe("evt", handler_b)
        await backend.emit("evt", {})

        assert sorted(results) == ["a", "b"]

    # ------------------------------------------------------------------
    # Handler resilience
    # ------------------------------------------------------------------

    async def test_handler_exception_does_not_crash_emit(self) -> None:
        """A failing handler must not prevent other handlers from running."""
        backend = DefaultObservabilityBackend()
        results: list[str] = []

        async def failing_handler(et: str, p: dict) -> None:
            raise RuntimeError("oops")

        async def good_handler(et: str, p: dict) -> None:
            results.append("ok")

        await backend.subscribe("evt", failing_handler)
        await backend.subscribe("evt", good_handler)

        # This must not raise
        await backend.emit("evt", {})

        assert results == ["ok"]

    # ------------------------------------------------------------------
    # Persistence via on_emit callback
    # ------------------------------------------------------------------

    async def test_on_emit_receives_all_events(self) -> None:
        """on_emit callback receives every emitted event."""
        events = []

        async def track(event_type, payload):
            events.append((event_type, payload))

        backend = DefaultObservabilityBackend(on_emit=track)
        await backend.emit("test_event", {"foo": "bar"})
        assert len(events) == 1
        assert events[0] == ("test_event", {"foo": "bar"})

    async def test_on_emit_concurrent(self) -> None:
        """Multiple concurrent emits all reach on_emit."""
        import asyncio

        events = []

        async def track(event_type, payload):
            events.append(payload["idx"])

        backend = DefaultObservabilityBackend(on_emit=track)
        tasks = [backend.emit("conc", {"idx": i}) for i in range(50)]
        await asyncio.gather(*tasks)
        assert len(events) == 50
