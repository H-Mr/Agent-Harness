"""Session data class — pure structure, no IO."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Session:
    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0

    @property
    def channel(self) -> str | None:
        """First component of ``key`` when formatted as ``channel:chat_id``."""
        return self.key.split(":", 1)[0] if ":" in self.key else None

    @property
    def chat_id(self) -> str | None:
        """Second component of ``key`` when formatted as ``channel:chat_id``."""
        return self.key.split(":", 1)[1] if ":" in self.key else None

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        msg = {"role": role, "content": content, "timestamp": datetime.now(timezone.utc).isoformat(), **kwargs}
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc)

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        unconsolidated = self.messages[self.last_consolidated:]
        if max_messages <= 0:
            return []
        sliced = unconsolidated[-max_messages:]
        found = False
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                found = True
                break
        if not found:
            return []
        result = []
        for m in sliced:
            entry = {"role": m["role"], "content": m.get("content", "")}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            result.append(entry)
        return result

    def remove_before(self, idx: int) -> None:
        if idx <= 0:
            return
        self.messages = self.messages[idx:]
        self.last_consolidated = max(0, self.last_consolidated - idx)
        self.updated_at = datetime.now(timezone.utc)

    def to_state(self) -> dict[str, Any]:
        return {"messages": self.messages, "metadata": self.metadata,
                "last_consolidated": self.last_consolidated}
