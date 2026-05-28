"""AgentLoop — pure ReAct skeleton. Behavior injected via callbacks."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from llm_harness.adapters.providers.base import LLMProvider
from llm_harness.core.tools.base import BaseTool, ToolExecutionContext, ToolRegistry

logger = logging.getLogger(__name__)


class BuildContextCallback(Protocol):
    def __call__(self, msg: Any, history: list[dict[str, Any]]) -> list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]: ...


class ToolCheckCallback(Protocol):
    def __call__(self, name: str, tool: BaseTool, args: Any) -> Any | Awaitable[Any]: ...


class ErrorCallback(Protocol):
    def __call__(self, exc: Exception, ctx: str) -> None: ...


class EventCallback(Protocol):
    def __call__(self, event_type: str, payload: dict[str, Any]) -> Awaitable[None]: ...


@dataclass
class TurnResult:
    final_content: str | None = None
    tools_used: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    new_messages_start: int = 0


class AgentLoop:
    TOOL_RESULT_MAX_CHARS = 16_000

    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        model: str,
        *,
        on_build_context: BuildContextCallback,
        on_tool_check: ToolCheckCallback,
        on_error: ErrorCallback,
        on_event: EventCallback | None = None,
        max_iterations: int = 40,
    ):
        self.provider = provider
        self.tools = tools
        self.model = model
        self._build_context = on_build_context
        self._check_tool = on_tool_check
        self._on_error = on_error
        self._on_event = on_event
        self.max_iterations = max_iterations

    async def run(self, msg: Any, history: list[dict[str, Any]], *, cwd: Path | None = None) -> TurnResult:
        workspace = cwd or Path("/workspace")
        result = TurnResult()
        messages = self._build_context(msg, history)
        if asyncio.iscoroutine(messages):
            messages = await messages

        # Track where the context ends and new assistant/tool messages begin.
        result.new_messages_start = len(messages)

        for _ in range(self.max_iterations):
            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=self.tools.to_api_schema(self.provider.api_format),
                model=self.model,
            )

            if not response.has_tool_calls:
                result.final_content = response.content or ""
                result.messages = messages
                return result

            tool_call_dicts = [tc.to_openai_tool_call() for tc in response.tool_calls]
            messages.append({"role": "assistant", "content": response.content or "",
                             "tool_calls": tool_call_dicts})

            for tc in response.tool_calls:
                if self._on_event:
                    await self._on_event("tool:executing", {"name": tc.name})

                tool_result = await self._execute_tool_call(tc, msg, workspace)
                tool_result = tool_result[:self.TOOL_RESULT_MAX_CHARS]
                if len(tool_result) >= self.TOOL_RESULT_MAX_CHARS:
                    tool_result += "\n... truncated"

                messages.append({"role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": tool_result})
                result.tools_used.append(tc.name)

            if self._on_event:
                await self._on_event("loop:iteration", {"tools_used": result.tools_used})

        result.final_content = "Max iterations reached."
        result.messages = messages
        return result

    async def _execute_tool_call(self, tc: Any, msg: Any, workspace: Path) -> str:
        """Execute a single tool call. Each step short-circuits on error."""
        tool = self.tools.get(tc.name)
        if tool is None:
            return f"Error: unknown tool '{tc.name}'"

        # 1. Parse arguments → Pydantic model
        args = tc.arguments
        if isinstance(args, str):
            args = json.loads(args)
        try:
            parsed = tool.input_model(**args)
        except Exception as e:
            return f"Error: invalid args for '{tc.name}': {e}"

        # 2. Permission check
        perm = self._check_tool(tc.name, tool, parsed)
        if asyncio.iscoroutine(perm):
            perm = await perm
        if hasattr(perm, 'allowed') and not perm.allowed:
            return f"Error: Permission denied: {perm.reason}"

        # 3. Execute
        session_key = getattr(msg, 'session_key', '')
        account = getattr(msg, 'sender_id', '')
        ctx = ToolExecutionContext(cwd=workspace, metadata={"session_key": session_key, "account": account})
        try:
            r = await tool.execute(parsed, ctx)
            return r.output
        except Exception as e:
            return f"Error executing '{tc.name}': {e}"
