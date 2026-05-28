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
    # Tracking (JSONL file)
    # ------------------------------------------------------------------

    async def test_track_mode_writes_to_events_jsonl(self, tmp_workspace: Path) -> None:
        """When track_dir is set, emit must write an entry to events.jsonl."""
        backend = DefaultObservabilityBackend(track_dir=tmp_workspace)
        await backend.emit("test_event", {"foo": "bar"})

        track_file = tmp_workspace / "events.jsonl"
        assert track_file.exists()
        lines = track_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["type"] == "test_event"
        assert record["payload"] == {"foo": "bar"}
        assert "ts" in record

    async def test_multiple_concurrent_emits_no_corruption(
        self, tmp_workspace: Path,
    ) -> None:
        """Multiple concurrent emits must not corrupt the events.jsonl file."""
        import asyncio

        backend = DefaultObservabilityBackend(track_dir=tmp_workspace)

        async def emit_task(idx: int) -> None:
            for _ in range(10):
                await backend.emit("conc", {"idx": idx})

        tasks = [emit_task(i) for i in range(5)]
        await asyncio.gather(*tasks)

        track_file = tmp_workspace / "events.jsonl"
        lines = track_file.read_text(encoding="utf-8").strip().splitlines()
        # 5 tasks * 10 emits each
        assert len(lines) == 50
        # Every line must be valid JSON
        for line in lines:
            record = json.loads(line)
            assert record["type"] == "conc"
            assert "idx" in record["payload"]

    async def test_track_mode_creates_directory(self, tmp_workspace: Path) -> None:
        """The track_dir must be created if it does not exist."""
        nested = tmp_workspace / "nested" / "track"
        backend = DefaultObservabilityBackend(track_dir=nested)
        await backend.emit("init", {})
        assert nested.exists()
        assert (nested / "events.jsonl").exists()
