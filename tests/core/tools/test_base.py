"""Tests for tool abstractions — BaseTool, ToolRegistry, ToolExecutionContext, ToolResult."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from llm_harness.core.tools.base import (
    BaseTool, ToolExecutionContext, ToolRegistry, ToolResult,
)


class SampleInput(BaseModel):
    msg: str


class SampleTool(BaseTool):
    name = "sample"
    description = "A sample tool"
    input_model = SampleInput

    async def execute(self, arguments, context):
        return ToolResult(output=f"executed: {arguments.msg}")


class ReadOnlyInput(BaseModel):
    val: int


class ReadOnlyTool(BaseTool):
    name = "readonly"
    description = "Read-only tool"
    input_model = ReadOnlyInput

    async def execute(self, arguments, context):
        return ToolResult(output=str(arguments.val))

    def is_read_only(self, arguments):
        return True


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------

class TestToolRegistry:
    def test_register_and_get(self):
        """A registered tool can be retrieved by name."""
        reg = ToolRegistry()
        tool = SampleTool()
        reg.register(tool)
        assert reg.get("sample") is tool

    def test_unregister_removes_tool(self):
        """Unregister removes the tool from the registry."""
        reg = ToolRegistry()
        reg.register(SampleTool())
        reg.unregister("sample")
        assert reg.get("sample") is None

    def test_has_returns_true_for_registered(self):
        """has returns True for a registered tool."""
        reg = ToolRegistry()
        reg.register(SampleTool())
        assert reg.has("sample") is True
        assert reg.has("nonexistent") is False

    def test_list_tools_returns_all(self):
        """list_tools returns every registered tool instance."""
        reg = ToolRegistry()
        reg.register(SampleTool())
        reg.register(ReadOnlyTool())
        tools = reg.list_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"sample", "readonly"}

    def test_len_reflects_count(self):
        """__len__ returns the number of registered tools."""
        reg = ToolRegistry()
        assert len(reg) == 0
        reg.register(SampleTool())
        assert len(reg) == 1

    def test_contains_operator(self):
        """__contains__ checks registration by name."""
        reg = ToolRegistry()
        reg.register(SampleTool())
        assert "sample" in reg
        assert "nope" not in reg

    def test_to_api_schema_openai_format(self):
        """to_api_schema produces valid OpenAI function-calling format."""
        reg = ToolRegistry()
        reg.register(SampleTool())
        schema = reg.to_api_schema("openai")
        assert len(schema) == 1
        entry = schema[0]
        assert entry["type"] == "function"
        assert entry["function"]["name"] == "sample"

    def test_to_api_schema_anthropic_format(self):
        """to_api_schema produces valid Anthropic tool format."""
        reg = ToolRegistry()
        reg.register(SampleTool())
        schema = reg.to_api_schema("anthropic")
        assert len(schema) == 1
        entry = schema[0]
        assert entry["name"] == "sample"
        assert "input_schema" in entry


# ---------------------------------------------------------------------------
# ToolExecutionContext
# ---------------------------------------------------------------------------

class TestToolExecutionContext:
    def test_creation_with_defaults(self):
        """ToolExecutionContext can be created with just a cwd."""
        ctx = ToolExecutionContext(cwd=Path("/tmp"))
        assert ctx.cwd == Path("/tmp")
        assert ctx.metadata == {}

    def test_creation_with_metadata(self):
        """ToolExecutionContext accepts metadata dictionary."""
        ctx = ToolExecutionContext(
            cwd=Path("/ws"),
            metadata={"session_key": "test:session", "extra": "val"},
        )
        assert ctx.metadata["session_key"] == "test:session"


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------

class TestToolResult:
    def test_default_is_not_error(self):
        """ToolResult defaults to is_error=False."""
        result = ToolResult(output="ok")
        assert result.is_error is False

    def test_error_flag(self):
        """ToolResult can be created with is_error=True."""
        result = ToolResult(output="fail", is_error=True)
        assert result.is_error is True

    def test_frozen_dataclass(self):
        """ToolResult is frozen and cannot be modified."""
        result = ToolResult(output="test")
        with pytest.raises(AttributeError):
            result.output = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BaseTool
# ---------------------------------------------------------------------------

class TestBaseTool:
    def test_is_read_only_default(self):
        """BaseTool.is_read_only returns False by default."""
        tool = SampleTool()
        assert tool.is_read_only(SampleInput(msg="x")) is False

    def test_is_read_only_override(self):
        """Tools can override is_read_only to return True."""
        tool = ReadOnlyTool()
        assert tool.is_read_only(ReadOnlyInput(val=42)) is True

    def test_to_api_schema_openai(self):
        """BaseTool.to_api_schema with 'openai' returns function schema."""
        tool = SampleTool()
        schema = tool.to_api_schema("openai")
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "sample"

    def test_to_api_schema_anthropic(self):
        """BaseTool.to_api_schema with 'anthropic' returns name+input_schema."""
        tool = SampleTool()
        schema = tool.to_api_schema("anthropic")
        assert schema["name"] == "sample"
        assert "input_schema" in schema
