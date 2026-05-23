"""Pluggable context building with section providers.

Each part of the system prompt is produced by an independent SectionProvider.
The ContextBuilder assembles them in priority order.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class SectionProvider(ABC):
    """Produces one section of the system prompt."""

    @property
    @abstractmethod
    def section_name(self) -> str:
        """Unique name for dedup and ordering."""
        ...

    @abstractmethod
    async def get_section(self) -> str:
        """Return the markdown section content."""
        ...

    @property
    def priority(self) -> int:
        """Lower = earlier in the prompt. Default 100."""
        return 100


class ContextBuilder:
    """Assembles system prompt from section providers and builds message lists."""

    def __init__(self):
        self._providers: dict[str, SectionProvider] = {}

    def add_provider(self, provider: SectionProvider) -> None:
        self._providers[provider.section_name] = provider

    def remove_provider(self, name: str) -> None:
        self._providers.pop(name, None)

    async def build_system_prompt(self) -> str:
        """Assemble all providers in priority order."""
        sorted_providers = sorted(
            self._providers.values(), key=lambda p: p.priority
        )
        parts: list[str] = []
        for provider in sorted_providers:
            section = await provider.get_section()
            if section.strip():
                parts.append(section)
        return "\n\n---\n\n".join(parts)

    def build_messages(
        self,
        system_prompt: str,
        history: list[dict[str, Any]],
        current_message: str,
        *,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build a complete message list for an LLM call."""
        runtime_ctx = self._build_runtime_context(channel, chat_id)
        merged = f"{runtime_ctx}\n\n{current_message}" if runtime_ctx else current_message
        return [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": merged},
        ]

    @staticmethod
    def _build_runtime_context(channel: str | None, chat_id: str | None) -> str:
        """Build a runtime context tag prepended to user messages."""
        parts: list[str] = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parts.append(f"Current time: {now}")
        if channel and chat_id:
            parts.append(f"Channel: {channel} | Chat ID: {chat_id}")
        return "\n".join(parts) if len(parts) > 1 else ""

    @staticmethod
    def add_tool_result(
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str,
    ) -> list[dict[str, Any]]:
        """Append a tool result to the message list."""
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result,
        })
        return messages

    @staticmethod
    def add_assistant_message(
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Append an assistant message to the message list."""
        msg: dict[str, Any] = {"role": "assistant"}
        if content:
            msg["content"] = content
        if tool_calls:
            msg["tool_calls"] = tool_calls
        messages.append(msg)
        return messages
