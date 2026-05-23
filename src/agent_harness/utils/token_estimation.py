"""Character-based token estimation."""

from __future__ import annotations

from typing import Any


def estimate_tokens(text: str) -> int:
    """Estimate token count from character count (rough: 4 chars ~= 1 token)."""
    return max(1, (len(text) + 3) // 4)


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate tokens in a chat message.

    Handles both plain-text ``content`` fields and structured lists
    (e.g. tool results with embedded images).
    """
    content = message.get("content", "")
    if isinstance(content, str):
        return estimate_tokens(content)
    if isinstance(content, list):
        return sum(estimate_tokens(str(item)) for item in content)
    return 0
