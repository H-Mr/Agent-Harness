"""Integration tests for llm-harness."""

import asyncio, tempfile
from pathlib import Path

import pytest
from llm_harness.core.bus.events import InboundMessage
from llm_harness.adapters.session import FileSessionBackend
from llm_harness.adapters.memory import FileMemoryBackend
from llm_harness.adapters.observability import DefaultObservabilityBackend
from llm_harness.core.session import SessionManager
from llm_harness.core.harness import Harness


class TestHarness:
    def test_create_minimal(self):
        h = Harness(memory="file:///tmp/test", sandbox="none")
        assert h.memory is not None
        assert h.sandbox is None

    def test_url_resolution(self):
        h = Harness(memory="tencentdb://localhost:8420", sandbox="opensandbox://localhost:8080")
        from llm_harness.adapters.memory.tencentdb import TencentDBMemoryBackend
        from llm_harness.adapters.sandbox.opensandbox import OpenSandboxBackend
        assert isinstance(h.memory, TencentDBMemoryBackend)
        assert isinstance(h.sandbox, OpenSandboxBackend)


class TestSessionBackend:
    @pytest.mark.asyncio
    async def test_save_and_load(self):
        d = tempfile.mkdtemp()
        b = FileSessionBackend(Path(d))
        await b.save("test:1", {"messages": [{"role": "user", "content": "hi"}], "metadata": {}, "last_consolidated": 0})
        state = await b.load("test:1")
        assert len(state["messages"]) == 1
        assert state["messages"][0]["content"] == "hi"

    @pytest.mark.asyncio
    async def test_list_keys(self):
        d = tempfile.mkdtemp()
        b = FileSessionBackend(Path(d))
        await b.save("a:1", {"messages": [], "metadata": {}, "last_consolidated": 0})
        await b.save("b:2", {"messages": [], "metadata": {}, "last_consolidated": 0})
        keys = await b.list_keys()
        assert "a:1" in keys and "b:2" in keys


class TestSessionManager:
    @pytest.mark.asyncio
    async def test_cache_and_persist(self):
        d = tempfile.mkdtemp()
        backend = FileSessionBackend(Path(d))
        sm = SessionManager(backend)
        s = await sm.get_or_create("cli:u")
        s.add_message("user", "hello")
        await sm.save(s)
        sm.invalidate("cli:u")
        s2 = await sm.get_or_create("cli:u")
        assert len(s2.messages) == 1
        assert s2.messages[0]["content"] == "hello"


class TestMemoryBackend:
    @pytest.mark.asyncio
    async def test_append_and_read(self):
        d = tempfile.mkdtemp()
        b = FileMemoryBackend(Path(d))
        await b.append_section("ns:1", "memory", "fact 1")
        await b.append_section("ns:1", "memory", "fact 2")
        ctx = await b.get_context("ns:1")
        assert "fact 1" in ctx and "fact 2" in ctx

    @pytest.mark.asyncio
    async def test_namespace_isolation(self):
        d = tempfile.mkdtemp()
        b = FileMemoryBackend(Path(d))
        await b.append_section("ns-a", "memory", "a")
        await b.append_section("ns-b", "memory", "b")
        assert "a" in await b.get_context("ns-a")
        assert "b" not in await b.get_context("ns-a")

    @pytest.mark.asyncio
    async def test_consolidate_no_provider_raw_archive(self):
        d = tempfile.mkdtemp()
        b = FileMemoryBackend(Path(d))
        ok = await b.consolidate("ns:1", [{"role": "user", "content": "test"}])
        assert ok is True


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
