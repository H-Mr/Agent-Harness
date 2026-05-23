"""Tests for hook execution engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_harness.hooks import (
    HookEvent,
    HookExecutionContext,
    HookExecutor,
)
from agent_harness.hooks.executor import _inject_arguments
from agent_harness.hooks.loader import HookRegistry
from agent_harness.hooks.schemas import (
    CommandHookDefinition,
    HttpHookDefinition,
    PromptHookDefinition,
)


# ============================================================================
# Command hooks
# ============================================================================


class TestCommandHooks:
    async def test_executes_and_returns_output(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="echo hooked"))
        executor = HookExecutor(registry, HookExecutionContext(cwd=tmp_path, provider=None, default_model="test"))

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "bash", "tool_input": {}})
        assert result.blocked is False
        assert result.results[0].success is True
        assert "hooked" in result.results[0].output

    async def test_block_on_failure_blocks_execution(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="exit 1", block_on_failure=True))
        executor = HookExecutor(registry, HookExecutionContext(cwd=tmp_path, provider=None, default_model="test"))

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "bash", "tool_input": {}})
        assert result.blocked is True

    async def test_no_block_on_failure_by_default(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="exit 1"))
        executor = HookExecutor(registry, HookExecutionContext(cwd=tmp_path, provider=None, default_model="test"))

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "bash", "tool_input": {}})
        assert result.blocked is False


# ============================================================================
# Matcher filtering
# ============================================================================


class TestMatcher:
    async def test_matches_tool_name(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="echo matched", matcher="bash"))
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="echo unmatched", matcher="write_*"))
        executor = HookExecutor(registry, HookExecutionContext(cwd=tmp_path, provider=None, default_model="test"))

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "bash", "tool_input": {}})
        assert len(result.results) == 1
        assert "matched" in result.results[0].output

    async def test_glob_matcher(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="echo file_op", matcher="*_file"))
        executor = HookExecutor(registry, HookExecutionContext(cwd=tmp_path, provider=None, default_model="test"))

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "write_file", "tool_input": {}})
        assert len(result.results) == 1
        assert "file_op" in result.results[0].output

    async def test_no_matcher_matches_all(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="echo always"))
        executor = HookExecutor(registry, HookExecutionContext(cwd=tmp_path, provider=None, default_model="test"))

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "any_tool", "tool_input": {}})
        assert len(result.results) == 1

    async def test_unmatched_matcher_skips(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="echo skipped", matcher="specific_tool"))
        executor = HookExecutor(registry, HookExecutionContext(cwd=tmp_path, provider=None, default_model="test"))

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "other_tool", "tool_input": {}})
        assert len(result.results) == 0


# ============================================================================
# Prompt hooks (LLM-based validation)
# ============================================================================


class _MockProviderForHooks:
    """Returns a JSON string simulating LLM validation output."""

    def __init__(self, response_text: str):
        self._response = response_text
        self.calls: list[dict] = []

    async def chat_with_retry(self, messages, tools=None, model=None, max_tokens=4096,
                              temperature=0.7, reasoning_effort=None, tool_choice=None):
        self.calls.append({"messages": messages})
        from agent_harness.providers.base import LLMResponse
        return LLMResponse(content=self._response, finish_reason="stop")

    def get_default_model(self):
        return "test-model"


class TestPromptHooks:
    async def test_ok_response_allows(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, PromptHookDefinition(prompt="Check safety"))
        executor = HookExecutor(
            registry,
            HookExecutionContext(
                cwd=tmp_path,
                provider=_MockProviderForHooks('{"ok": true}'),
                default_model="test",
            ),
        )

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "bash", "tool_input": {"command": "ls"}})
        assert result.blocked is False

    async def test_ok_false_blocks(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, PromptHookDefinition(prompt="Check"))
        executor = HookExecutor(
            registry,
            HookExecutionContext(
                cwd=tmp_path,
                provider=_MockProviderForHooks('{"ok": false, "reason": "not allowed"}'),
                default_model="test",
            ),
        )

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "bash", "tool_input": {}})
        assert result.blocked is True
        assert result.reason == "not allowed"

    async def test_invalid_json_blocks_by_default(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, PromptHookDefinition(prompt="Check"))
        executor = HookExecutor(
            registry,
            HookExecutionContext(
                cwd=tmp_path,
                provider=_MockProviderForHooks("not valid json"),
                default_model="test",
            ),
        )

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "bash", "tool_input": {}})
        # Invalid JSON → _parse_hook_json returns ok=false → blocks (block_on_failure=True by default)
        assert result.blocked is True


# ============================================================================
# Multiple hooks and events
# ============================================================================


class TestMultipleHooks:
    async def test_all_registered_hooks_execute(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="echo first"))
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="echo second"))
        executor = HookExecutor(registry, HookExecutionContext(cwd=tmp_path, provider=None, default_model="test"))

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "echo", "tool_input": {}})
        assert len(result.results) == 2

    async def test_different_events_dont_cross_fire(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(command="echo pre_tool"))
        registry.register(HookEvent.POST_TOOL_USE, CommandHookDefinition(command="echo post_tool"))
        executor = HookExecutor(registry, HookExecutionContext(cwd=tmp_path, provider=None, default_model="test"))

        pre = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "echo", "tool_input": {}})
        assert len(pre.results) == 1
        assert "pre_tool" in pre.results[0].output

    async def test_multiple_events_registered_and_queried(self):
        registry = HookRegistry()
        registry.register(HookEvent.SESSION_START, CommandHookDefinition(command="echo boot"))
        registry.register(HookEvent.SESSION_END, CommandHookDefinition(command="echo shutdown"))

        assert len(registry.get(HookEvent.SESSION_START)) == 1
        assert len(registry.get(HookEvent.SESSION_END)) == 1
        assert len(registry.get(HookEvent.PRE_TOOL_USE)) == 0


# ============================================================================
# _inject_arguments
# ============================================================================


class TestInjectArguments:
    def test_no_escape_by_default(self):
        payload = {"command": "$(whoami)"}
        result = _inject_arguments("echo $ARGUMENTS", payload)
        assert result == 'echo {"command": "$(whoami)"}'

    def test_shell_escape_wraps_in_quotes(self):
        payload = {"command": "$(whoami)"}
        result = _inject_arguments("echo $ARGUMENTS", payload, shell_escape=True)
        assert result.startswith("echo '")
        assert "$(whoami)" in result

    def test_no_arguments_placeholder_passes_through(self):
        result = _inject_arguments("echo hello", {"x": 1})
        assert result == "echo hello"


# ============================================================================
# HTTP hooks
# ============================================================================


class TestHttpHooks:
    async def test_http_hook_blocks_on_failure_when_configured(self, tmp_path: Path):
        registry = HookRegistry()
        registry.register(
            HookEvent.PRE_TOOL_USE,
            HttpHookDefinition(url="http://127.0.0.1:1/nonexistent", timeout_seconds=1, block_on_failure=True),
        )
        executor = HookExecutor(registry, HookExecutionContext(cwd=tmp_path, provider=None, default_model="test"))

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "bash", "tool_input": {}})
        assert result.blocked is True
