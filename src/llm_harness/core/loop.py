"""AgentLoop — pure ReAct skeleton. Behavior injected via callbacks."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llm_harness.adapters.providers.base import LLMProvider
from llm_harness.core.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    final_content: str | None = None
    tools_used: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)


class AgentLoop:
    TOOL_RESULT_MAX_CHARS = 16_000

    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        model: str,
        *,
        on_build_context: Any,
        on_tool_check: Any,
        on_error: Any,
        on_event: Any = None,
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

    async def run(self, msg: Any, history: list[dict[str, Any]]) -> TurnResult:
        result = TurnResult()
        messages = self._build_context(msg, history)
        if asyncio.iscoroutine(messages):
            messages = await messages

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

                tool = self.tools.get(tc.name)
                if tool is None:
                    tool_result = f"Error: unknown tool '{tc.name}'"
                else:
                    args = tc.arguments
                    if isinstance(args, str):
                        args = json.loads(args)
                    try:
                        parsed = tool.input_model(**args)
                    except Exception as e:
                        tool_result = f"Error: invalid args for '{tc.name}': {e}"
                    else:
                        try:
                            perm = await self._check_tool(tc.name, tool, parsed)
                            if hasattr(perm, 'allowed') and not perm.allowed:
                                tool_result = f"Error: Permission denied: {perm.reason}"
                            else:
                                from llm_harness.core.tools.base import ToolExecutionContext
                                ctx = ToolExecutionContext(cwd=Path("/workspace"), metadata={})
                                r = await tool.execute(parsed, ctx)
                                tool_result = r.output
                        except Exception as e:
                            tool_result = f"Error executing '{tc.name}': {e}"

                if len(tool_result) > self.TOOL_RESULT_MAX_CHARS:
                    tool_result = tool_result[:self.TOOL_RESULT_MAX_CHARS] + f"\n... truncated"

                messages.append({"role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": tool_result})
                result.tools_used.append(tc.name)

            if self._on_event:
                await self._on_event("loop:iteration", {"tools_used": result.tools_used})

        result.final_content = "Max iterations reached."
        result.messages = messages
        return result
