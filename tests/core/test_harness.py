"""Tests for Harness — pure assembler, all parameters explicit."""

from unittest.mock import MagicMock, patch

from llm_harness.core.harness import Harness
from llm_harness.core.agent import Agent
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend
from llm_harness.adapters.memory.tencentdb import TencentDBMemoryBackend
from llm_harness.core.permissions.checker import PermissionChecker
from llm_harness.core.permissions.settings import PermissionSettings
from llm_harness.core.tools.base import ToolRegistry
from llm_harness.core.tools.factory import ToolFactory


def _make_sandbox():
    import tempfile
    from pathlib import Path
    return SRTSandboxBackend(Path(tempfile.mkdtemp()))


def _make_tools():
    factory = ToolFactory(sandbox=_make_sandbox())
    registry = ToolRegistry()
    for name in ["read_file", "exec", "glob", "web_search"]:
        tool = factory.build(name)
        if tool:
            registry.register(tool)
    return registry


def _make_harness(**kwargs):
    return Harness(
        provider=MagicMock(), model="test-model",
        tools=_make_tools(), sandbox=_make_sandbox(),
        **kwargs,
    )


def test_create_minimal():
    h = _make_harness()
    assert isinstance(h._sandbox, SRTSandboxBackend)


def test_create_agent():
    h = _make_harness(memory=TencentDBMemoryBackend())
    agent = h.create_agent()
    assert isinstance(agent, Agent)
    assert agent._loop is not None
    assert agent._loop.model == "test-model"


def test_on_tool_check_passes_file_path():
    perms = PermissionChecker(PermissionSettings())
    h = _make_harness(permissions=perms)
    with patch.object(perms, "evaluate", return_value=MagicMock(allowed=True)) as mock_eval:
        agent = h.create_agent()
        on_check = agent._loop._check_tool
        from llm_harness.core.tools.read_file import ReadFileTool, ReadFileInput
        tool = ReadFileTool(sandbox=MagicMock())
        args = ReadFileInput(path="/some/file.py")
        on_check("read_file", tool, args)
        mock_eval.assert_called_once()
        assert mock_eval.call_args[1]["file_path"] == "/some/file.py"


def test_create_agent_no_permissions_allows_all():
    h = _make_harness()  # no permissions → allow-all
    agent = h.create_agent()
    on_check = agent._loop._check_tool
    from llm_harness.core.tools.exec import ExecTool, ExecInput
    tool = ExecTool(sandbox=MagicMock())
    args = ExecInput(command="ls -la")
    decision = on_check("exec", tool, args)
    assert hasattr(decision, "allowed")
    assert decision.allowed is True
