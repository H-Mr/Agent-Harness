"""Shared test fixtures for llm-harness tests."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def tmp_workspace():
    """Temporary workspace directory that cleans up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def mock_bus():
    """MessageBus mock with async queue support."""
    bus = MagicMock()
    bus.inbound = MagicMock()
    bus.outbound = MagicMock()
    bus.publish_inbound = AsyncMock()
    bus.consume_inbound = AsyncMock()
    bus.publish_outbound = AsyncMock()
    bus.consume_outbound = AsyncMock()
    return bus


@pytest.fixture
def mock_sandbox():
    """SandboxBackend mock that returns success for all operations."""
    from llm_harness.adapters.sandbox.backend import ExecResult

    sb = AsyncMock()
    sb.read_file = AsyncMock(return_value="file content")
    sb.write_file = AsyncMock()
    sb.list_dir = AsyncMock(return_value=["file1.txt", "file2.py"])
    sb.glob = AsyncMock(return_value=["/ws/file1.py"])
    sb.grep = AsyncMock(return_value=["file1.py:1:match"])
    sb.execute = AsyncMock(return_value=ExecResult(output="ok", exit_code=0))
    sb.create_session = AsyncMock()
    sb.destroy_session = AsyncMock()
    return sb


@pytest.fixture
def mock_memory():
    """MemoryBackend mock."""
    mb = AsyncMock()
    mb.get_context = AsyncMock(return_value="")
    mb.read_section = AsyncMock(return_value="")
    mb.append_section = AsyncMock()
    mb.consolidate = AsyncMock(return_value=True)
    return mb


@pytest.fixture
def mock_provider():
    """LLMProvider mock that returns a simple text response."""
    from llm_harness.adapters.providers.base import LLMResponse

    provider = AsyncMock()
    provider.api_format = "openai"
    response = LLMResponse(
        content="Hello, I am an AI assistant.",
        tool_calls=[],
        finish_reason="stop",
        usage={"prompt_tokens": 10, "completion_tokens": 5},
    )
    provider.chat_with_retry = AsyncMock(return_value=response)
    provider.chat_stream_with_retry = AsyncMock(return_value=response)
    provider.estimate_tokens = MagicMock(return_value=100)
    return provider


@pytest.fixture
def mock_tool_registry():
    """ToolRegistry populated with mock tools."""
    from llm_harness.core.tools.base import ToolRegistry
    return ToolRegistry()


@pytest.fixture
def tool_context():
    """Standard ToolExecutionContext for tests."""
    from llm_harness.core.tools.base import ToolExecutionContext
    return ToolExecutionContext(cwd=Path("/workspace"), metadata={"session_key": "test:session"})


@pytest.fixture
def event_loop():
    """Create a fresh event loop for each async test."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
