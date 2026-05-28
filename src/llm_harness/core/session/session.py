"""Session data class — pure structure, no IO."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Session:
    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        msg = {"role": role, "content": content, "timestamp": datetime.now().isoformat(), **kwargs}
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        unconsolidated = self.messages[self.last_consolidated:]
        sliced = unconsolidated[-max_messages:]
        found = False
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                found = True
                break
        if not found:
            return []
        return [{"role": m["role"], "content": m.get("content", "")} for m in sliced]

    def remove_before(self, idx: int) -> None:
        if idx <= 0:
            return
        self.messages = self.messages[idx:]
        self.last_consolidated = max(0, self.last_consolidated - idx)
        self.updated_at = datetime.now()

    def to_state(self) -> dict[str, Any]:
        return {"messages": self.messages, "metadata": self.metadata,
                "last_consolidated": self.last_consolidated}
