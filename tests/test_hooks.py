"""Tests for HookExecutor: timeout enforcement, short-circuit on blocked hooks."""

import asyncio as _asyncio
import pytest
from unittest.mock import MagicMock
from pathlib import Path
from llm_harness.extensions.hooks.executor import HookExecutor, HookExecutionContext
from llm_harness.extensions.hooks.loader import HookRegistry
from llm_harness.extensions.hooks.events import HookEvent
from llm_harness.extensions.hooks.schemas import (
    PromptHookDefinition,
)
from llm_harness.extensions.hooks.types import HookResult


class TestTimeoutEnforcement:
    """Prompt and agent hooks must respect timeout_seconds."""

    @pytest.mark.asyncio
    async def test_prompt_hook_uses_timeout(self):
        """A slow provider must be cut off by the hook's timeout."""
        registry = HookRegistry()
        hook = PromptHookDefinition(
            prompt="check this", timeout_seconds=1, block_on_failure=False
        )
        registry.register(HookEvent.PRE_TOOL_USE, hook)

        provider = MagicMock()
        async def slow_chat(**kw):
            await _asyncio.sleep(10)
            return MagicMock(content='{"ok": true}')
        provider.chat_with_retry = slow_chat

        ctx = HookExecutionContext(cwd=Path("/tmp"), provider=provider, default_model="test")
        executor = HookExecutor(registry, ctx)

        with pytest.raises(_asyncio.TimeoutError):
            await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "exec"})

    @pytest.mark.asyncio
    async def test_prompt_hook_with_no_provider(self):
        """Hook without a provider must return failure, not crash."""
        registry = HookRegistry()
        hook = PromptHookDefinition(
            prompt="check", timeout_seconds=30, block_on_failure=False
        )
        registry.register(HookEvent.PRE_TOOL_USE, hook)

        ctx = HookExecutionContext(cwd=Path("/tmp"), provider=None)
        executor = HookExecutor(registry, ctx)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "exec"})
        assert not result.results[0].success
        assert "no LLM provider" in result.results[0].reason


class TestShortCircuit:
    """Blocked hooks must short-circuit subsequent hook execution."""

    @pytest.mark.asyncio
    async def test_blocked_hook_stops_execution(self):
        """When a hook returns blocked=True, subsequent hooks must be skipped."""
        registry = HookRegistry()

        # Hook 1: will fail and block
        hook1 = PromptHookDefinition(
            prompt="validate", timeout_seconds=30, block_on_failure=True
        )
        registry.register(HookEvent.PRE_TOOL_USE, hook1)

        # Hook 2: should never execute
        hook2 = PromptHookDefinition(
            prompt="never run", timeout_seconds=30, block_on_failure=False
        )
        registry.register(HookEvent.PRE_TOOL_USE, hook2)

        provider = MagicMock()
        async def fail_chat(**kw):
            return MagicMock(content='invalid json {{{', has_tool_calls=False)
        provider.chat_with_retry = fail_chat

        ctx = HookExecutionContext(cwd=Path("/tmp"), provider=provider, default_model="test")
        executor = HookExecutor(registry, ctx)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "exec"})
        # Only hook1 should have run (hook2 skipped via short-circuit)
        assert len(result.results) == 1


class TestMatcher:
    """Hook matchers must filter by payload fields."""

    @pytest.mark.asyncio
    async def test_matching_hook_runs(self):
        registry = HookRegistry()
        hook = PromptHookDefinition(
            prompt="match", matcher="exec", timeout_seconds=5, block_on_failure=False
        )
        registry.register(HookEvent.PRE_TOOL_USE, hook)

        provider = MagicMock()
        async def ok_chat(**kw):
            return MagicMock(content='{"ok": true}', has_tool_calls=False)
        provider.chat_with_retry = ok_chat

        ctx = HookExecutionContext(cwd=Path("/tmp"), provider=provider, default_model="test")
        executor = HookExecutor(registry, ctx)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "exec"})
        assert len(result.results) == 1  # matched, so it runs

    @pytest.mark.asyncio
    async def test_non_matching_hook_skipped(self):
        registry = HookRegistry()
        hook = PromptHookDefinition(
            prompt="no match", matcher="read*", timeout_seconds=5, block_on_failure=False
        )
        registry.register(HookEvent.PRE_TOOL_USE, hook)

        ctx = HookExecutionContext(cwd=Path("/tmp"), provider=None)
        executor = HookExecutor(registry, ctx)

        result = await executor.execute(HookEvent.PRE_TOOL_USE, {"tool_name": "exec"})
        assert len(result.results) == 0  # didn't match matcher
