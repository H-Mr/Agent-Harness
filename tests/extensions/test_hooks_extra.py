"""Tests for additional hook functionality (executor.py, events.py, loader.py)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_harness.extensions.hooks.events import HookEvent
from llm_harness.extensions.hooks.executor import (
    HookExecutionContext,
    HookExecutor,
    _inject_arguments,
    _matches_hook,
    _parse_hook_json,
)
from llm_harness.extensions.hooks.loader import HookRegistry
from llm_harness.extensions.hooks.schemas import CommandHookDefinition, HttpHookDefinition

# =============================================================================
# _parse_hook_json
# =============================================================================


class TestParseHookJson:
    """_parse_hook_json response parsing."""

    def test_valid_json_ok_true(self):
        """Parses JSON with ok=true."""
        result = _parse_hook_json('{"ok": true}')
        assert result == {"ok": True}

    def test_valid_json_ok_false(self):
        """Parses JSON with ok=false."""
        result = _parse_hook_json('{"ok": false}')
        assert result == {"ok": False}

    def test_valid_json_with_reason(self):
        """Parses JSON with ok=false and a reason."""
        result = _parse_hook_json('{"ok": false, "reason": "nope"}')
        assert result == {"ok": False, "reason": "nope"}

    def test_lowercase_ok_text(self):
        """Lowercase 'ok' text returns {ok: True}."""
        assert _parse_hook_json("ok") == {"ok": True}

    def test_lowercase_true_text(self):
        """Lowercase 'true' text returns {ok: True}."""
        assert _parse_hook_json("true") == {"ok": True}

    def test_lowercase_yes_text(self):
        """Lowercase 'yes' text returns {ok: True}."""
        assert _parse_hook_json("yes") == {"ok": True}

    def test_mixed_case_ok(self):
        """Mixed case 'Ok' still matches via lowered check."""
        assert _parse_hook_json("Ok") == {"ok": True}

    def test_invalid_text(self):
        """Invalid text returns {ok: False} with the text as reason."""
        result = _parse_hook_json("garbage response")
        assert result == {"ok": False, "reason": "garbage response"}

    def test_empty_string(self):
        """Empty string returns {ok: False} with default reason."""
        result = _parse_hook_json("")
        assert result == {"ok": False, "reason": "hook returned invalid JSON"}

    def test_json_without_ok_field(self):
        """Valid JSON without ok field falls through to text matching."""
        result = _parse_hook_json('{"status": "ok"}')
        # Not valid JSON for our purpose (no bool ok field)
        assert result == {"ok": False, "reason": '{"status": "ok"}'}

    def test_json_with_non_bool_ok(self):
        """Valid JSON with non-bool ok field falls through."""
        result = _parse_hook_json('{"ok": "true"}')
        # "true" (string) is not bool, so falls through to text match;
        # the full text '{"ok": "true"}' does not match 'true' exactly
        assert result == {"ok": False, "reason": '{"ok": "true"}'}


# =============================================================================
# _inject_arguments
# =============================================================================


class TestInjectArguments:
    """_inject_arguments replacement and shell escaping."""

    def test_replaces_arguments(self):
        """$ARGUMENTS is replaced with JSON payload."""
        result = _inject_arguments("echo $ARGUMENTS", {"key": "value"})
        assert result == 'echo {"key": "value"}'

    def test_no_placeholder(self):
        """Template without $ARGUMENTS is returned unchanged."""
        result = _inject_arguments("echo hello", {"key": "value"})
        assert result == "echo hello"

    def test_multiple_arguments(self):
        """Multiple $ARGUMENTS placeholders are all replaced."""
        result = _inject_arguments("$ARGUMENTS $ARGUMENTS", {"a": 1})
        assert result == '{"a": 1} {"a": 1}'

    def test_shell_escape(self):
        """When shell_escape=True, the JSON is wrapped in shell quotes."""
        result = _inject_arguments("echo $ARGUMENTS", {"key": "value"}, shell_escape=True)
        # shlex.quote wraps in single quotes
        assert "'{\"key\": \"value\"}'" in result

    def test_shell_escape_empty_payload(self):
        """Shell escape works with empty payload."""
        result = _inject_arguments("echo $ARGUMENTS", {}, shell_escape=True)
        # shlex.quote("{}") returns '{}'
        assert "'{}'" in result


# =============================================================================
# _matches_hook
# =============================================================================


class TestMatchesHook:
    """_matches_hook matcher logic."""

    def test_true_when_no_matcher(self):
        """Returns True when the hook has no matcher attribute."""
        hook = CommandHookDefinition(command="echo hi")
        assert _matches_hook(hook, {"tool_name": "anything"}) is True

    def test_matches_tool_name(self):
        """Matches tool_name with fnmatch pattern."""
        hook = CommandHookDefinition(command="echo hi", matcher="read*")
        assert _matches_hook(hook, {"tool_name": "read_file"}) is True

    def test_no_match(self):
        """Returns False when fnmatch does not match."""
        hook = CommandHookDefinition(command="echo hi", matcher="write*")
        assert _matches_hook(hook, {"tool_name": "read_file"}) is False

    def test_fallback_to_prompt(self):
        """Falls back to prompt key when tool_name is absent."""
        hook = CommandHookDefinition(command="echo hi", matcher="check_*")
        assert _matches_hook(hook, {"prompt": "check_something"}) is True

    def test_fallback_to_event(self):
        """Falls back to event key when tool_name and prompt are absent."""
        hook = CommandHookDefinition(command="echo hi", matcher="session_*")
        assert _matches_hook(hook, {"event": "session_start"}) is True

    def test_empty_subject_no_match(self):
        """Returns False when subject is empty and matcher is not empty."""
        hook = CommandHookDefinition(command="echo hi", matcher="someskill")
        assert _matches_hook(hook, {}) is False


# =============================================================================
# _run_command_hook
# =============================================================================


class TestRunCommandHook:
    """_run_command_hook subprocess execution."""

    @pytest.mark.asyncio
    async def test_success_with_exit_code_0(self, tmp_workspace: Path):
        """Returns success=True when the command exits with 0."""
        hook = CommandHookDefinition(command="echo hello", timeout_seconds=5)
        executor = HookExecutor(
            HookRegistry(),
            HookExecutionContext(cwd=tmp_workspace),
        )
        result = await executor._run_command_hook(hook, HookEvent.SESSION_START, {})
        assert result.success is True
        assert result.output == "hello"

    @pytest.mark.asyncio
    async def test_failure_with_nonzero_exit(self, tmp_workspace: Path):
        """Returns success=False when the command exits with non-zero."""
        hook = CommandHookDefinition(command="python -c \"exit(1)\"", timeout_seconds=5)
        executor = HookExecutor(
            HookRegistry(),
            HookExecutionContext(cwd=tmp_workspace),
        )
        result = await executor._run_command_hook(hook, HookEvent.SESSION_START, {})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self, tmp_workspace: Path):
        """Returns timeout error when command exceeds timeout_seconds."""
        script = tmp_workspace / "long_sleep.py"
        script.write_text("import time; time.sleep(30)")

        hook = CommandHookDefinition(
            command=f"{sys.executable} {script}",
            timeout_seconds=1,
        )
        executor = HookExecutor(
            HookRegistry(),
            HookExecutionContext(cwd=tmp_workspace),
        )
        result = await executor._run_command_hook(hook, HookEvent.SESSION_START, {})
        assert result.success is False
        assert "timed out" in result.reason

    @pytest.mark.asyncio
    async def test_block_on_failure(self, tmp_workspace: Path):
        """block_on_failure=True propagates to the result when command fails."""
        hook = CommandHookDefinition(
            command="python -c \"exit(1)\"",
            timeout_seconds=5,
            block_on_failure=True,
        )
        executor = HookExecutor(
            HookRegistry(),
            HookExecutionContext(cwd=tmp_workspace),
        )
        result = await executor._run_command_hook(hook, HookEvent.SESSION_START, {})
        assert result.success is False
        assert result.blocked is True
        assert result.metadata.get("returncode") != 0


# =============================================================================
# _run_http_hook
# =============================================================================


class TestRunHttpHook:
    """_run_http_hook HTTP request execution (with mocked httpx)."""

    @pytest.fixture
    def executor(self, tmp_workspace):
        return HookExecutor(HookRegistry(), HookExecutionContext(cwd=tmp_workspace))

    @pytest.fixture
    def mock_httpx(self):
        """Patch httpx.AsyncClient so no real network call is made."""
        with patch("llm_harness.extensions.hooks.executor.httpx.AsyncClient") as mock_cls:
            client = MagicMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.post = AsyncMock()
            mock_cls.return_value = client
            yield client

    @pytest.mark.asyncio
    async def test_success_with_200(self, executor: HookExecutor, mock_httpx: MagicMock):
        """Returns success=True for a 200 response."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.text = "OK"
        mock_response.status_code = 200
        mock_httpx.post.return_value = mock_response

        hook = HttpHookDefinition(url="http://example.com/hook")
        result = await executor._run_http_hook(hook, HookEvent.SESSION_START, {"key": "val"})

        assert result.success is True
        assert result.output == "OK"
        mock_httpx.post.assert_called_once_with(
            "http://example.com/hook",
            json={"event": "session_start", "payload": {"key": "val"}},
            headers={},
        )

    @pytest.mark.asyncio
    async def test_failure_with_500(self, executor: HookExecutor, mock_httpx: MagicMock):
        """Returns success=False for a 500 response."""
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.text = "Internal Server Error"
        mock_response.status_code = 500
        mock_httpx.post.return_value = mock_response

        hook = HttpHookDefinition(url="http://example.com/fail")
        result = await executor._run_http_hook(hook, HookEvent.SESSION_START, {})

        assert result.success is False
        assert result.output == "Internal Server Error"

    @pytest.mark.asyncio
    async def test_block_on_failure(self, executor: HookExecutor, mock_httpx: MagicMock):
        """block_on_failure=True marks result as blocked when request fails."""
        mock_response = MagicMock()
        mock_response.is_success = False
        mock_response.text = "Error"
        mock_response.status_code = 500
        mock_httpx.post.return_value = mock_response

        hook = HttpHookDefinition(url="http://example.com/fail", block_on_failure=True)
        result = await executor._run_http_hook(hook, HookEvent.SESSION_START, {})

        assert result.blocked is True

    @pytest.mark.asyncio
    async def test_custom_headers(self, executor: HookExecutor, mock_httpx: MagicMock):
        """Custom headers are sent with the request."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.text = "OK"
        mock_response.status_code = 200
        mock_httpx.post.return_value = mock_response

        hook = HttpHookDefinition(
            url="http://example.com/hook",
            headers={"Authorization": "Bearer token123"},
        )
        await executor._run_http_hook(hook, HookEvent.SESSION_START, {})

        mock_httpx.post.assert_called_once_with(
            "http://example.com/hook",
            json={"event": "session_start", "payload": {}},
            headers={"Authorization": "Bearer token123"},
        )


# =============================================================================
# _run_prompt_like_hook (negative test — no provider)
# =============================================================================


class TestRunPromptHook:
    """_run_prompt_like_hook with no provider available."""

    @pytest.mark.asyncio
    async def test_no_provider_returns_failure(self, tmp_workspace: Path):
        """Returns failure when no LLM provider is available."""
        from llm_harness.extensions.hooks.schemas import PromptHookDefinition

        hook = PromptHookDefinition(prompt="Is this ok?")
        executor = HookExecutor(
            HookRegistry(),
            HookExecutionContext(cwd=tmp_workspace, provider=None),
        )
        result = await executor._run_prompt_like_hook(
            hook, HookEvent.SESSION_START, {}, agent_mode=False,
        )
        assert result.success is False
        assert "no LLM provider" in result.reason


# =============================================================================
# HookRegistry
# =============================================================================


class TestHookRegistry:
    """HookRegistry register / get."""

    def test_register_and_retrieve(self):
        """Hooks registered for an event are returned by get()."""
        registry = HookRegistry()
        hook = CommandHookDefinition(command="echo hi")
        registry.register(HookEvent.SESSION_START, hook)
        hooks = registry.get(HookEvent.SESSION_START)
        assert len(hooks) == 1
        assert hooks[0] is hook

    def test_get_returns_copy(self):
        """get returns a new list, not the internal one."""
        registry = HookRegistry()
        hook = CommandHookDefinition(command="echo hi")
        registry.register(HookEvent.SESSION_START, hook)
        hooks = registry.get(HookEvent.SESSION_START)
        hooks.append(None)
        # Internal list should not be affected
        assert len(registry.get(HookEvent.SESSION_START)) == 1

    def test_get_nonexistent_event(self):
        """get returns empty list for an event with no hooks."""
        registry = HookRegistry()
        assert registry.get(HookEvent.SESSION_END) == []

    def test_multiple_events(self):
        """Hooks for different events are stored separately."""
        registry = HookRegistry()
        h1 = CommandHookDefinition(command="echo 1")
        h2 = CommandHookDefinition(command="echo 2")
        registry.register(HookEvent.SESSION_START, h1)
        registry.register(HookEvent.SESSION_END, h2)
        assert len(registry.get(HookEvent.SESSION_START)) == 1
        assert len(registry.get(HookEvent.SESSION_END)) == 1


# =============================================================================
# HookEvent enum
# =============================================================================


class TestHookEvent:
    """HookEvent enum values are correct."""

    def test_session_start(self):
        assert HookEvent.SESSION_START == "session_start"

    def test_session_end(self):
        assert HookEvent.SESSION_END == "session_end"

    def test_pre_tool_use(self):
        assert HookEvent.PRE_TOOL_USE == "pre_tool_use"

    def test_post_tool_use(self):
        assert HookEvent.POST_TOOL_USE == "post_tool_use"

    def test_all_values_unique(self):
        values = [e.value for e in HookEvent]
        assert len(values) == len(set(values))
