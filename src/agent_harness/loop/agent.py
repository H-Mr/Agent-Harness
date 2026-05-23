"""Agent Loop -- pure ReAct skeleton.

All app-specific behavior is injected via LoopCallbacks.
The loop knows nothing about sessions, channels, slash commands, or persistence.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from agent_harness.bus.events import InboundMessage, OutboundMessage
from agent_harness.observability.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ErrorEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from agent_harness.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


# ============================================================================
# Callbacks -- the "what" that the loop does not own
# ============================================================================


@dataclass
class LoopCallbacks:
    """All app-level behavior injected into the AgentLoop.

    The loop doesn't care what tools exist, how messages are assembled,
    or what happens to the final response -- it just coordinates the cycle.
    """

    # Build the initial message list for an LLM call
    build_messages: Callable[..., list[dict[str, Any]]]

    # Execute a single tool by name + arguments dict -> returns result string
    execute_tool: Callable[[str, dict[str, Any]], Awaitable[str]]

    # Return the current tool definitions (OpenAI function schema format)
    get_tool_definitions: Callable[[], list[dict[str, Any]]]

    # Optional: called when tool execution starts, with human-readable hint
    on_progress: Callable[[str, bool], Awaitable[None]] | None = None

    # Optional: streaming text delta callback
    on_stream: Callable[[str], Awaitable[None]] | None = None

    # Optional: streaming segment ended (resuming=True means tool calls follow)
    on_stream_end: Callable[[bool], Awaitable[None]] | None = None

    # Optional: ask the user a question and await their response
    ask_user: Callable[[str], Awaitable[str]] | None = None

    # Optional: structured observability events (metrics, tracing, dashboards)
    on_event: Callable[[object], Awaitable[None]] | None = None


# ============================================================================
# Turn result
# ============================================================================


@dataclass
class TurnResult:
    """Result of one turn through the ReAct loop."""

    final_content: str | None = None
    tools_used: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


# ============================================================================
# AgentLoop -- pure ReAct skeleton with concurrency control
# ============================================================================


class AgentLoop:
    """Pure ReAct loop skeleton with concurrency control.

    Concurrency model (from nanobot):
      - per-session asyncio.Lock for serial processing within a session
      - global asyncio.Semaphore for max concurrent sessions
    """

    _TOOL_RESULT_MAX_CHARS = 16_000

    def __init__(
        self,
        provider: LLMProvider,
        callbacks: LoopCallbacks,
        *,
        model: str | None = None,
        max_iterations: int = 40,
        max_concurrent: int = 3,
    ):
        self.provider = provider
        self.callbacks = callbacks
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._concurrency_gate = (
            asyncio.Semaphore(max_concurrent) if max_concurrent > 0 else None
        )
        self._last_usage: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _emit(self, event) -> None:
        """Fire a structured observability event to callback and global bus."""
        if self.callbacks.on_event is not None:
            await self.callbacks.on_event(event)
        # Also push to global EventBus (no-op if no consumers attached)
        from agent_harness.observability.bus import get_event_bus
        try:
            await get_event_bus().emit(event)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Core ReAct Loop
    # ------------------------------------------------------------------

    async def run_react_loop(
        self,
        initial_messages: list[dict[str, Any]],
        *,
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> TurnResult:
        """Execute one full ReAct cycle.

        Loop: LLM call -> has tool_calls? -> execute tools concurrently -> repeat
        Until: LLM returns plain text or max_iterations reached.

        Returns TurnResult with final_content, tools_used, all messages, and token usage.
        """
        messages = list(initial_messages)
        iteration = 0
        final_content = None
        tools_used: list[str] = []

        on_stream = self.callbacks.on_stream
        on_stream_end = self.callbacks.on_stream_end
        on_progress = self.callbacks.on_progress

        while iteration < self.max_iterations:
            iteration += 1

            tool_defs = self.callbacks.get_tool_definitions()

            # Call LLM (streaming if callbacks provided, otherwise non-streaming)
            if on_stream:
                response = await self.provider.chat_stream_with_retry(
                    messages=messages,
                    tools=tool_defs,
                    model=self.model,
                    on_content_delta=on_stream,
                )
            else:
                response = await self.provider.chat_with_retry(
                    messages=messages,
                    tools=tool_defs,
                    model=self.model,
                )

            usage = response.usage or {}
            self._last_usage = {
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            }

            # Branch 1: LLM wants to call tools
            if response.has_tool_calls:
                if on_stream and on_stream_end:
                    await on_stream_end(resuming=True)

                if on_progress:
                    hint = self._tool_hint(response.tool_calls)
                    await on_progress(hint, True)

                # Append assistant message with tool_calls
                tool_call_dicts = [
                    tc.to_openai_tool_call() for tc in response.tool_calls
                ]
                messages.append(self._build_assistant_msg(response, tool_call_dicts))

                for tc in response.tool_calls:
                    tools_used.append(tc.name)
                    args_str = json.dumps(tc.arguments, ensure_ascii=False)
                    logger.info("Tool call: %s(%s)", tc.name, args_str[:200])

                # Execute tools concurrently
                # return_exceptions ensures one failure doesn't block others
                import time as _time
                _started: dict[str, float] = {}
                for tc in response.tool_calls:
                    _started[tc.id] = _time.monotonic()
                    await self._emit(ToolExecutionStarted(tc.name, tc.arguments))

                results = await asyncio.gather(
                    *(
                        self.callbacks.execute_tool(tc.name, tc.arguments)
                        for tc in response.tool_calls
                    ),
                    return_exceptions=True,
                )

                # Append tool results
                for tc, result in zip(response.tool_calls, results):
                    is_err = isinstance(result, BaseException)
                    if is_err:
                        result = f"Error: {type(result).__name__}: {result}"
                    duration = (_time.monotonic() - _started[tc.id]) * 1000
                    await self._emit(ToolExecutionCompleted(
                        tc.name, str(result)[:self._TOOL_RESULT_MAX_CHARS],
                        is_error=is_err,
                        duration_ms=duration,
                    ))
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tc.name,
                            "content": str(result)[: self._TOOL_RESULT_MAX_CHARS],
                        }
                    )

            # Branch 2: LLM gave final text response
            else:
                if on_stream and on_stream_end:
                    await on_stream_end(resuming=False)

                if response.finish_reason == "error":
                    logger.error(
                        "LLM returned error: %s", (response.content or "")[:200]
                    )
                    final_content = (
                        response.content or "Sorry, I encountered an error."
                    )
                    await self._emit(ErrorEvent(final_content, recoverable=True))
                    break

                messages.append(self._build_assistant_msg(response))
                final_content = response.content
                await self._emit(AssistantTurnComplete(final_content, self._last_usage))
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations (%s) reached", self.max_iterations)
            final_content = (
                f"Reached maximum iterations ({self.max_iterations}) without completion. "
                "Try breaking the task into smaller steps."
            )

        return TurnResult(
            final_content=final_content,
            tools_used=tools_used,
            messages=messages,
            usage=self._last_usage,
        )

    # ------------------------------------------------------------------
    # Message Processing (with concurrency)
    # ------------------------------------------------------------------

    @staticmethod
    async def _maybe_await(fn, *args, **kwargs):
        """Call fn and await it if it returns an awaitable."""
        result = fn(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def process_message(
        self, msg: InboundMessage
    ) -> OutboundMessage | None:
        """Process one inbound message through the ReAct loop.

        Concurrency: per-session Lock (serial within session) + global Semaphore (max concurrent).
        """
        lock = self._session_locks.setdefault(msg.session_key, asyncio.Lock())
        gate = self._concurrency_gate or nullcontext()
        async with lock, gate:
            try:
                # Build messages using the injected callback
                initial_messages = await self._maybe_await(
                    self.callbacks.build_messages, msg
                )

                result = await self.run_react_loop(
                    initial_messages,
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                )

                if result.final_content is None:
                    return None

                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=result.final_content,
                )
            except asyncio.CancelledError:
                logger.info(
                    "Task cancelled for session %s", msg.session_key
                )
                raise
            except Exception:
                logger.exception(
                    "Error processing message for session %s", msg.session_key
                )
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Sorry, I encountered an error.",
                )

    async def process_direct(
        self,
        content: str,
        *,
        channel: str = "cli",
        chat_id: str = "direct",
        sender_id: str = "user",
    ) -> TurnResult:
        """One-shot processing without a bus.

        Build a synthetic InboundMessage and run the loop directly.
        """
        msg = InboundMessage(
            channel=channel,
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
        )
        initial_messages = await self._maybe_await(
            self.callbacks.build_messages, msg
        )
        return await self.run_react_loop(
            initial_messages, channel=channel, chat_id=chat_id
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as human-readable string: tool_name("arg")."""
        def _fmt(tc):
            args = tc.arguments
            if isinstance(args, list):
                args = args[0] if args else {}
            val = (
                next(iter(args.values()), None)
                if isinstance(args, dict)
                else None
            )
            if not isinstance(val, str):
                return tc.name
            return (
                f'{tc.name}("{val[:40]}...")'
                if len(val) > 40
                else f'{tc.name}("{val}")'
            )

        return ", ".join(_fmt(tc) for tc in tool_calls)

    @staticmethod
    def _build_assistant_msg(
        response: LLMResponse,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build an assistant message dict from LLMResponse."""
        msg: dict[str, Any] = {"role": "assistant"}
        if response.content:
            msg["content"] = response.content
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return msg
