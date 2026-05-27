"""Memory system for persistent agent memory.

Ported from nanobot.agent.memory with interface adapted to agent-harness.
MemoryConsolidator uses pluggable policy dispatch and per-session MemoryStore.
"""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from collections.abc import Awaitable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from agent_harness.memory.store import MemoryStore
from agent_harness.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from agent_harness.providers.base import LLMProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token estimation helpers inlined from nanobot.utils.helpers
# ---------------------------------------------------------------------------


def estimate_message_tokens(message: dict) -> int:
    """Estimate token count of a message (rough estimate: 4 chars ~= 1 token)."""
    content = message.get("content", "")
    if isinstance(content, str):
        return len(content) // 4
    if isinstance(content, list):
        return sum(len(str(item)) // 4 for item in content)
    return 0


def estimate_prompt_tokens_chain(
    provider: Any,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
) -> tuple[int, str]:
    """Estimate total prompt tokens."""
    del provider, model
    msg_tokens = sum(estimate_message_tokens(m) for m in messages)
    tool_tokens = sum(len(str(t)) // 4 for t in (tools or []))
    return msg_tokens + tool_tokens, "estimate"


# ---------------------------------------------------------------------------
# save_memory tool definition (5-field)
# ---------------------------------------------------------------------------


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save structured memory consolidation across five output files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agents_update": {
                        "type": ["string", "null"],
                        "description": (
                            "Updated AGENTS.md content: project rules, conventions, "
                            "workflow preferences. Return null if nothing changed."
                        ),
                    },
                    "soul_update": {
                        "type": ["string", "null"],
                        "description": (
                            "Updated SOUL.md content: personality, tone, communication "
                            "style, behavioral patterns. Return null if nothing changed."
                        ),
                    },
                    "memory_update": {
                        "type": "string",
                        "description": (
                            "Updated MEMORY.md content: factual knowledge, decisions "
                            "made, key discoveries. MUST return the complete updated "
                            "version including all existing and new facts."
                        ),
                    },
                    "user_update": {
                        "type": ["string", "null"],
                        "description": (
                            "Updated USER.md content: user profile, preferences, goals. "
                            "Return null if nothing changed."
                        ),
                    },
                    "history_entry": {
                        "type": "string",
                        "description": (
                            "A grep-searchable summary line for history.jsonl. "
                            'Start with "[YYYY-MM-DD HH:MM] key events/decisions/topics".'
                        ),
                    },
                },
                "required": ["memory_update", "history_entry"],
            },
        },
    }
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _ensure_text(value: Any) -> str:
    """Normalize tool-call payload values to text for file storage."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _normalize_save_memory_args(args: Any) -> dict[str, Any] | None:
    """Normalize provider tool-call arguments to the expected dict shape."""
    if isinstance(args, str):
        args = json.loads(args)
    if isinstance(args, list):
        return args[0] if args and isinstance(args[0], dict) else None
    return args if isinstance(args, dict) else None


_TOOL_CHOICE_ERROR_MARKERS = (
    "tool_choice",
    "toolchoice",
    "does not support",
    'should be ["none", "auto"]',
)


def _is_tool_choice_unsupported(content: str | None) -> bool:
    """Detect provider errors caused by forced tool_choice being unsupported."""
    text = (content or "").lower()
    return any(m in text for m in _TOOL_CHOICE_ERROR_MARKERS)


def _format_messages(messages: list[dict]) -> str:
    """Format a list of messages into a human-readable string for LLM consolidation."""
    lines = []
    for message in messages:
        if not message.get("content"):
            continue
        tools = f" [tools: {', '.join(message['tools_used'])}]" if message.get("tools_used") else ""
        lines.append(
            f"[{message.get('timestamp', '?')[:16]}] {message['role'].upper()}{tools}: {message['content']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MemoryConsolidator
# ---------------------------------------------------------------------------


class MemoryConsolidator:
    """Owns consolidation policy, locking, and session offset updates."""

    _MAX_CONSOLIDATION_ROUNDS = 5
    _MAX_FAILURES_BEFORE_RAW_ARCHIVE = 3

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        sessions: SessionManager,
        context_window_tokens: int,
        build_messages: Callable[..., list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]],
        get_tool_definitions: Callable[[], list[dict[str, Any]]],
        max_completion_tokens: int = 4096,
        policy: object = None,
    ):
        from agent_harness.memory.policy import TokenBudgetPolicy as TBP

        self.provider = provider
        self.model = model
        self.sessions = sessions
        self.context_window_tokens = context_window_tokens
        self.max_completion_tokens = max_completion_tokens
        self._build_messages = build_messages
        self._get_tool_definitions = get_tool_definitions
        self._policy = policy or TBP(
            context_window_tokens=context_window_tokens,
            max_completion_tokens=max_completion_tokens,
        )
        self._workspace = workspace
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

        # Per-session store cache
        self._stores: dict[str, MemoryStore] = {}

        # Backward-compat: keep self.store for existing callers
        self.store = MemoryStore(workspace / "memory")

    def _get_store(self, session_key: str) -> MemoryStore:
        """Return or create the per-session MemoryStore."""
        if session_key not in self._stores:
            self._stores[session_key] = MemoryStore(
                self._workspace / "memory", session_key=session_key
            )
        return self._stores[session_key]

    def get_lock(self, session_key: str) -> asyncio.Lock:
        """Return the shared consolidation lock for one session."""
        return self._locks.setdefault(session_key, asyncio.Lock())

    def _build_consolidation_prompt(
        self,
        messages: list[dict],
        current_files: dict[str, str],
    ) -> str:
        """Build the structured consolidation prompt from current memory state."""
        formatted = _format_messages(messages)
        return f"""Process this conversation and call the save_memory tool with your consolidation.

## File Responsibilities
- **agents_update** → AGENTS.md: project rules, workflow conventions, tech stack preferences
- **soul_update** → SOUL.md: communication style, tone, reply habits, behavioral patterns
- **memory_update** → MEMORY.md: factual knowledge, decisions, key discoveries (REQUIRED — return complete updated version)
- **user_update** → USER.md: user role, preferences, goals
- **history_entry** → history.jsonl: one grep-searchable summary line like "[YYYY-MM-DD HH:MM] key events"

For any file where nothing changed, return null (not empty string). For memory_update, always return the complete updated MEMORY.md content.

## Current Memory State
### AGENTS.md
{current_files.get('AGENTS.md') or '(empty)'}

### SOUL.md
{current_files.get('SOUL.md') or '(empty)'}

### MEMORY.md
{current_files.get('MEMORY.md') or '(empty)'}

### USER.md
{current_files.get('USER.md') or '(empty)'}

## Conversation to Process
{formatted}"""

    async def _consolidate_chunk(self, session_key: str, messages: list[dict]) -> bool:
        """Consolidate a message chunk via LLM into per-session memory files."""
        if not messages:
            return True

        store = self._get_store(session_key)
        current_files = store.get_all_files()
        prompt = self._build_consolidation_prompt(messages, current_files)

        chat_messages = [
            {
                "role": "system",
                "content": "You are a memory consolidation agent. Call the save_memory tool with your structured consolidation.",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            forced = {"type": "function", "function": {"name": "save_memory"}}
            response = await self.provider.chat_with_retry(
                messages=chat_messages,
                tools=_SAVE_MEMORY_TOOL,
                model=self.model,
                tool_choice=forced,
            )

            if response.finish_reason == "error" and _is_tool_choice_unsupported(response.content):
                logger.warning("Forced tool_choice unsupported, retrying with auto")
                response = await self.provider.chat_with_retry(
                    messages=chat_messages,
                    tools=_SAVE_MEMORY_TOOL,
                    model=self.model,
                    tool_choice="auto",
                )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory")
                return self._fallback_raw_archive(store, messages)

            args = _normalize_save_memory_args(response.tool_calls[0].arguments)
            if args is None:
                logger.warning("Memory consolidation: unexpected save_memory arguments")
                return self._fallback_raw_archive(store, messages)

            # Validate required fields: memory_update and history_entry
            memory_val = args.get("memory_update")
            if memory_val is None:
                logger.warning("Memory consolidation: missing required memory_update")
                return self._fallback_raw_archive(store, messages)

            memory_text = _ensure_text(memory_val).strip()
            if not memory_text:
                logger.warning("Memory consolidation: empty memory_update after normalization")
                return self._fallback_raw_archive(store, messages)

            history_val = args.get("history_entry")
            history_text = _ensure_text(history_val or "").strip()
            if not history_text:
                logger.warning("Memory consolidation: missing or empty history_entry")
                return self._fallback_raw_archive(store, messages)

            # Write each non-null field to its file (normalize values for LLM dicts)
            field_to_file = {
                "agents_update": "AGENTS.md",
                "soul_update": "SOUL.md",
                "memory_update": "MEMORY.md",
                "user_update": "USER.md",
            }

            for field, filename in field_to_file.items():
                value = args.get(field)
                if value is not None:
                    text_value = _ensure_text(value).strip()
                    if text_value:
                        current = current_files.get(filename, "")
                        if text_value != current:
                            store.write_file(filename, text_value)

            # Append history entry
            store.append_history(history_text)

            # Archive raw messages
            store.append_raw_messages(messages)

            self._consecutive_failures = 0
            logger.info("Memory consolidation done for %s messages", len(messages))
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return self._fallback_raw_archive(store, messages)

    def _fallback_raw_archive(self, store: MemoryStore, messages: list[dict]) -> bool:
        """Increment failure count; after threshold, raw-archive and return True."""
        if not hasattr(self, '_consecutive_failures'):
            self._consecutive_failures = 0
        self._consecutive_failures += 1
        if self._consecutive_failures < self._MAX_FAILURES_BEFORE_RAW_ARCHIVE:
            return False
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        store.append_history(f"[{ts}] [RAW] {len(messages)} messages")
        store.append_raw_messages(messages)
        logger.warning("Memory consolidation degraded: raw-archived %s messages", len(messages))
        self._consecutive_failures = 0
        return True

    async def maybe_consolidate(self, session: Session) -> None:
        """Run consolidation if the configured policy requests it."""
        if not session.messages:
            return

        lock = self.get_lock(session.key)
        async with lock:
            for _ in range(self._MAX_CONSOLIDATION_ROUNDS):
                chunk = await self._policy.should_consolidate(session, self)
                if chunk is None or not chunk:
                    return

                end_idx = session.last_consolidated + len(chunk)
                logger.info(
                    "Consolidation: archiving %s messages for %s",
                    len(chunk), session.key,
                )

                if not await self._consolidate_chunk(session.key, chunk):
                    return

                session.remove_before(end_idx)
                self.sessions.save(session)

    async def consolidate_messages(
        self, session_key: str, messages: list[dict[str, object]]
    ) -> bool:
        """Archive a selected message chunk into persistent memory."""
        return await self._consolidate_chunk(session_key, messages)

    def pick_consolidation_boundary(
        self,
        session: Session,
        tokens_to_remove: int,
    ) -> tuple[int, int] | None:
        """Pick a user-turn boundary that removes enough old prompt tokens."""
        start = session.last_consolidated
        if start >= len(session.messages) or tokens_to_remove <= 0:
            return None

        removed_tokens = 0
        last_boundary: tuple[int, int] | None = None
        for idx in range(start, len(session.messages)):
            message = session.messages[idx]
            if idx > start and message.get("role") == "user":
                last_boundary = (idx, removed_tokens)
                if removed_tokens >= tokens_to_remove:
                    return last_boundary
            removed_tokens += estimate_message_tokens(message)

        return last_boundary

    async def estimate_session_prompt_tokens(self, session: Session) -> tuple[int, str]:
        """Estimate current prompt size for the normal session history view."""
        history = session.get_history(max_messages=0)
        channel, chat_id = (session.key.split(":", 1) if ":" in session.key else (None, None))
        probe_messages = self._build_messages(
            history=history,
            current_message="[token-probe]",
            channel=channel,
            chat_id=chat_id,
        )
        if asyncio.iscoroutine(probe_messages):
            probe_messages = await probe_messages
        return estimate_prompt_tokens_chain(
            self.provider,
            self.model,
            probe_messages,
            self._get_tool_definitions(),
        )

    async def archive_messages(
        self, session_key: str, messages: list[dict[str, object]]
    ) -> bool:
        """Archive messages with guaranteed persistence (retries until raw-dump fallback)."""
        if not messages:
            return True
        for _ in range(self._MAX_FAILURES_BEFORE_RAW_ARCHIVE):
            if await self._consolidate_chunk(session_key, messages):
                return True
        # Final fallback: always raw-dump
        store = self._get_store(session_key)
        self._fallback_raw_archive(store, messages)
        return True
