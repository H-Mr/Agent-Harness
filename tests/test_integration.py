"""Integration tests for llm-harness."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from llm_harness.core.bus.events import InboundMessage
from llm_harness.adapters.observability import DefaultObservabilityBackend
from llm_harness.adapters.memory.tencentdb import TencentDBMemoryBackend
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory
from llm_harness.core.harness import Harness


def _make_harness():
    sandbox = SRTSandboxBackend(Path(tempfile.mkdtemp()))
    factory = ToolFactory(sandbox=sandbox, memory=TencentDBMemoryBackend())
    registry = ToolRegistry()
    for name in ["read_file", "exec", "glob", "web_search", "memory_read", "memory_write"]:
        tool = factory.build(name)
        if tool:
            registry.register(tool)
    return Harness(
        provider=MagicMock(), model="test", tools=registry, sandbox=sandbox,
        memory=TencentDBMemoryBackend(),
    )


class TestHarness:
    def test_create_minimal(self):
        h = _make_harness()
        assert h._sandbox is not None
        assert h._memory is not None


class TestObservability:
    @pytest.mark.asyncio
    async def test_emit_and_subscribe(self):
        events = []
        async def h(t, p): events.append((t, p))
        b = DefaultObservabilityBackend()
        await b.subscribe("test", h)
        await b.emit("test", {"msg": "hello"})
        assert len(events) == 1
        assert events[0][1]["msg"] == "hello"


class TestInboundMessage:
    def test_session_key(self):
        msg = InboundMessage("cli", "user", "chat", "hello")
        assert msg.session_key == "cli:chat"

    def test_session_key_override(self):
        msg = InboundMessage("cli", "user", "chat", "hello", session_key_override="custom:1")
        assert msg.session_key == "custom:1"
