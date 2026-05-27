"""Agent class -- runnable agent that combines Harness + model name.

The Agent wraps a :class:`Harness <agent_harness.harness.Harness>` and a model
name into a single ``process(msg)`` entry point that handles session bookkeeping,
memory consolidation, message building, and the ReAct loop.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Awaitable, Callable

from agent_harness.bus.events import InboundMessage, OutboundMessage
from agent_harness.harness import Harness
from agent_harness.loop.agent import AgentLoop, LoopCallbacks, TurnResult
from agent_harness.memory.consolidator import MemoryConsolidator
from agent_harness.session.manager import Session
from agent_harness.tools.base import ToolExecutionContext

log = logging.getLogger(__name__)

_TOOL_RESULT_MAX_CHARS = 16_000


class Agent:
    """Harness + model = a runnable agent.

    Combines a fully configured :class:`Harness` with a model name and provides
    a single ``process(msg)`` entry point that drives the full pipeline:

    1. Concurrency control (per-session lock + global semaphore)
    2. Session get-or-create (only when sessions are configured)
    3. User message persistence (only when sessions are configured)
    4. Memory consolidation (only when both memory and sessions are configured)
    5. Context/message building via ``harness.on_build_context``
    6. ReAct loop via :class:`AgentLoop <agent_harness.loop.agent.AgentLoop>`
    7. Turn persistence (only when sessions are configured)
    8. Return :class:`OutboundMessage <agent_harness.bus.events.OutboundMessage>`

    When sessions are **not** configured the Agent operates in stateless mode:
    session bookkeeping and memory consolidation are skipped entirely.

    Args:
        harness: Fully configured :class:`Harness` instance.
        model: Model name override (defaults to provider default).
        max_iterations: Maximum ReAct loop iterations before forced stop.
        max_concurrent: Maximum concurrent sessions (semaphore gate).
        on_stream: Called with each text delta during LLM streaming output.
            Leave ``None`` to use non-streaming mode.
        on_progress: Called with ``(hint: str, is_tool_start: bool)`` when a
            tool call begins, giving a human-readable hint like ``read_file("config.py")``.
        on_stream_end: Called with ``resuming: bool`` when a streaming segment
            ends; ``resuming=True`` means tool calls follow.
        on_event: Called with structured observability events
            (:class:`ToolExecutionStarted <agent_harness.observability.events.ToolExecutionStarted>`,
            :class:`AssistantTurnComplete <agent_harness.observability.events.AssistantTurnComplete>`, etc.).
        ask_user: Called when the loop needs user input (blocks until returned).
    """

    def __init__(
        self,
        harness: Harness,
        *,
        model: str | None = None,
        max_iterations: int = 40,
        max_concurrent: int = 3,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_progress: Callable[[str, bool], Awaitable[None]] | None = None,
        on_stream_end: Callable[[bool], Awaitable[None]] | None = None,
        on_event: Callable[[object], Awaitable[None]] | None = None,
        ask_user: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        self.harness = harness
        self.model = model or harness.provider.get_default_model()
        self.max_iterations = max_iterations

        # Concurrency control --------------------------------------------------
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._concurrency_gate = (
            asyncio.Semaphore(max_concurrent) if max_concurrent > 0 else None
        )

        # Build the AgentLoop with wired callbacks ----------------------------
        self._loop = self._build_loop(
            on_stream=on_stream,
            on_progress=on_progress,
            on_stream_end=on_stream_end,
            on_event=on_event,
            ask_user=ask_user,
        )

        # Memory consolidator (only when both memory and sessions are active) --
        self._consolidator: MemoryConsolidator | None = None
        if harness.memory is not None and harness.sessions is not None:
            self._consolidator = MemoryConsolidator(
                workspace=harness.workspace,
                provider=harness.provider,
                model=self.model,
                sessions=harness.sessions,
                context_window_tokens=harness.context_window_tokens,
                build_messages=self._make_consolidation_build_messages(),
                get_tool_definitions=lambda: harness.tools.to_api_schema("openai"),
                max_completion_tokens=harness.max_completion_tokens,
            )

    # ------------------------------------------------------------------
    # AgentLoop construction
    # ------------------------------------------------------------------

    def _build_loop(
        self,
        *,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_progress: Callable[[str, bool], Awaitable[None]] | None = None,
        on_stream_end: Callable[[bool], Awaitable[None]] | None = None,
        on_event: Callable[[object], Awaitable[None]] | None = None,
        ask_user: Callable[[str], Awaitable[str]] | None = None,
    ) -> AgentLoop:
        """Create the :class:`AgentLoop` with all callbacks wired to *harness*."""
        harness = self.harness

        async def execute_tool(tool_name: str, args_dict: dict[str, Any]) -> str:
            tool = harness.tools.get(tool_name)
            if tool is None:
                return f"Error: Unknown tool '{tool_name}'"

            try:
                parsed = tool.input_model.model_validate(args_dict)
            except Exception as exc:
                return f"Error: Invalid arguments for '{tool_name}': {exc}"

            permission = await harness.on_tool_check(tool_name, tool, parsed)
            if not permission.allowed:
                return f"Error: Permission denied: {permission.reason}"

            context = ToolExecutionContext(cwd=harness.workspace)
            try:
                result = await tool.execute(parsed, context)
                return result.output
            except Exception as exc:
                log.exception("Tool %s failed", tool_name)
                return f"Error: {type(exc).__name__}: {exc}"

        def get_tool_definitions() -> list[dict[str, Any]]:
            return harness.tools.to_api_schema("openai")

        callbacks = LoopCallbacks(
            build_messages=lambda *args, **kwargs: [],
            execute_tool=execute_tool,
            get_tool_definitions=get_tool_definitions,
            on_stream=on_stream,
            on_progress=on_progress,
            on_stream_end=on_stream_end,
            on_event=on_event,
            ask_user=ask_user,
        )

        return AgentLoop(
            provider=harness.provider,
            callbacks=callbacks,
            model=self.model,
            max_iterations=self.max_iterations,
            max_concurrent=0,  # Agent handles concurrency at its own level
        )

    # ------------------------------------------------------------------
    # MemoryConsolidator helper
    # ------------------------------------------------------------------

    def _make_consolidation_build_messages(self):
        """Build a ``build_messages`` callable matching MemoryConsolidator's expected signature.

        The consolidator calls::

            build_messages(history=..., current_message=..., channel=..., chat_id=...)
        """
        harness = self.harness

        async def _build(
            *,
            history: list[dict[str, Any]],
            current_message: str,
            channel: str | None = None,
            chat_id: str | None = None,
        ) -> list[dict[str, Any]]:
            system = await harness.context.build_system_prompt()
            return harness.context.build_messages(
                system,
                history,
                current_message,
                channel=channel,
                chat_id=chat_id,
            )

        return _build

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def process(self, msg: InboundMessage) -> OutboundMessage | None:
        """Process an inbound message through the full Agent pipeline.

        Args:
            msg: The inbound message to process.

        Returns:
            An outbound message with the agent's response, or ``None`` if no
            response could be produced.
        """
        lock = self._session_locks.setdefault(msg.session_key, asyncio.Lock())
        gate = self._concurrency_gate or nullcontext()

        async with lock, gate:
            try:
                # Step 2-3: Session bookkeeping (only if sessions configured)
                session = None
                history: list[dict[str, Any]] = []

                if self.harness.sessions is not None:
                    session = self.harness.sessions.get_or_create(msg.session_key)
                    # Capture history BEFORE adding the current message so that
                    # on_build_context does not duplicate it.
                    history = session.get_history()
                    session.add_message("user", msg.content)
                    self.harness.sessions.save(session)

                # Step 4: Memory consolidation (only if both memory & sessions)
                if self._consolidator is not None and session is not None:
                    await self._consolidator.maybe_consolidate(session)

                # Step 5: Build messages via pipeline callback
                initial_messages = await self.harness.on_build_context(msg, history)

                # Step 6: Run the ReAct loop
                result = await self._loop.run_react_loop(
                    initial_messages,
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                )

                # Step 7: Persist new messages (only if sessions)
                if session is not None:
                    self._save_turn(session, result, len(initial_messages))

                # Step 8: Return result
                if result.final_content is None:
                    return None

                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=result.final_content,
                )

            except asyncio.CancelledError:
                log.info("Task cancelled for session %s", msg.session_key)
                raise
            except Exception as exc:
                log.exception(
                    "Error processing message for session %s", msg.session_key
                )
                user_msg = await self.harness.on_error(exc, "agent.process")
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=user_msg or "Sorry, I encountered an error.",
                )

    # ------------------------------------------------------------------
    # Persistence helper
    # ------------------------------------------------------------------

    def _save_turn(self, session: Session, result: TurnResult, initial_count: int) -> None:
        """Persist new messages from *result* to *session*.

        Args:
            session: The session to persist to.
            result: The turn result from the ReAct loop.
            initial_count: The number of messages in ``initial_messages`` so
                that ``result.messages[initial_count:]`` yields only the new
                assistant and tool messages produced during this turn.
        """
        new_messages = result.messages[initial_count:]

        for msg in new_messages:
            role = msg.get("role")
            content = msg.get("content", "")

            # Skip truly empty assistant messages (no content and no tool_calls)
            if role == "assistant" and not content and not msg.get("tool_calls"):
                continue

            # Truncate long tool results to avoid bloating session storage
            if role == "tool" and isinstance(content, str) and len(content) > _TOOL_RESULT_MAX_CHARS:
                content = content[:_TOOL_RESULT_MAX_CHARS]

            # Collect extra message fields the session should preserve
            extra: dict[str, Any] = {}
            for key in ("tool_calls", "tool_call_id", "name"):
                if key in msg:
                    extra[key] = msg[key]

            session.add_message(role, content, **extra)

        self.harness.sessions.save(session)
