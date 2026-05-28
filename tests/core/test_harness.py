"""Tests for Harness — IoC container that resolves backends and assembles Agent."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_harness.core.harness import Harness
from llm_harness.core.agent import Agent
from llm_harness.core.permissions.checker import PermissionChecker


def test_create_minimal():
    """Harness with memory=file creates without error (srt sandbox default)."""
    from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
    harness = Harness(
        provider=MagicMock(),
        model="test-model",
        memory="file:///tmp/test",
    )
    assert harness.memory is not None
    assert isinstance(harness.sandbox, SRTSandboxBackend)
    assert harness.workspace == Path.cwd().resolve()


def test_resolve_memory_file():
    """file:// URI resolves to FileMemoryBackend."""
    harness = Harness(provider=MagicMock(), model="x")
    mem = harness._resolve_memory("file:///tmp/mem")
    from llm_harness.adapters.memory.file import FileMemoryBackend
    assert isinstance(mem, FileMemoryBackend)


def test_resolve_memory_tencentdb():
    """tencentdb:// URI resolves to TencentDBMemoryBackend."""
    harness = Harness(provider=MagicMock(), model="x")
    mem = harness._resolve_memory("tencentdb://localhost:8080")
    from llm_harness.adapters.memory.tencentdb import TencentDBMemoryBackend
    assert isinstance(mem, TencentDBMemoryBackend)


def test_resolve_memory_plain_path():
    """A plain path string resolves to FileMemoryBackend."""
    harness = Harness(provider=MagicMock(), model="x")
    mem = harness._resolve_memory("/tmp/plain")
    from llm_harness.adapters.memory.file import FileMemoryBackend
    assert isinstance(mem, FileMemoryBackend)


def test_resolve_memory_none():
    """None returns None."""
    harness = Harness(provider=MagicMock(), model="x")
    assert harness._resolve_memory(None) is None


def test_resolve_memory_type_error():
    """Unexpected type raises TypeError."""
    harness = Harness(provider=MagicMock(), model="x")
    with pytest.raises(TypeError):
        harness._resolve_memory(123)


def test_resolve_sandbox_srt():
    """'srt' string resolves to SRTSandboxBackend."""
    harness = Harness(provider=MagicMock(), model="x")
    sb = harness._resolve_sandbox("srt")
    from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
    assert isinstance(sb, SRTSandboxBackend)


def test_resolve_sandbox_srt_default():
    """None sandbox defaults to SRTSandboxBackend."""
    harness = Harness(provider=MagicMock(), model="x")
    sb = harness._resolve_sandbox(None)
    from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
    assert isinstance(sb, SRTSandboxBackend)


def test_workspace_expanded():
    """Workspace path is expanded and resolved to absolute."""
    harness = Harness(provider=MagicMock(), model="x", workspace=".")
    assert harness.workspace.is_absolute()
    assert harness.workspace == Path.cwd().resolve()


def test_create_agent_returns_agent():
    """create_agent returns an Agent with properly configured loop."""
    harness = Harness(
        provider=MagicMock(),
        model="test-model",
        memory="file:///tmp/test",
    )
    agent = harness.create_agent()
    assert isinstance(agent, Agent)
    assert agent._loop is not None
    assert agent._loop.model == "test-model"
    assert agent._loop.provider is not None


def test_on_tool_check_passes_file_path_and_command():
    """The on_tool_check lambda extracts file_path and command from parsed args."""
    harness = Harness(
        provider=MagicMock(),
        model="x",
        permissions="default",
    )
    # Patch the permission checker evaluate method
    with patch.object(harness._permissions, "evaluate", return_value=MagicMock(allowed=True)) as mock_eval:
        agent = harness.create_agent()
        on_check = agent._loop._check_tool
        # Simulate checking a read_file tool
        from llm_harness.core.tools.read_file import ReadFileTool, ReadFileInput
        tool = ReadFileTool(sandbox=MagicMock())
        args = ReadFileInput(path="/some/file.py")
        on_check("read_file", tool, args)
        mock_eval.assert_called_once()
        call_kwargs = mock_eval.call_args[1]
        assert call_kwargs["file_path"] == "/some/file.py"


def test_permission_checker_evaluate_receives_correct_params():
    """PermissionChecker.evaluate receives proper params from Harness on_tool_check."""
    harness = Harness(
        provider=MagicMock(),
        model="x",
        permissions="default",
    )
    agent = harness.create_agent()
    on_check = agent._loop._check_tool

    # Create an ExecTool-like scenario so command is extracted
    from llm_harness.core.tools.exec import ExecTool, ExecInput
    tool = ExecTool(sandbox=MagicMock())
    args = ExecInput(command="ls -la")

    # This should not raise and should return a PermissionDecision
    decision = on_check("exec", tool, args)
    assert hasattr(decision, "allowed")
