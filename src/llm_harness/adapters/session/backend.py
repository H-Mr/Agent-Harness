"""SessionBackend Protocol — harness owns Session model, backend owns persistence."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionBackend(Protocol):
    async def load(self, session_key: str) -> dict[str, Any] | None:
        """Load session state dict. Returns None if not found."""
        ...

    async def save(self, session_key: str, state: dict[str, Any]) -> None:
        """Persist session state."""
        ...

    async def list_keys(self) -> list[str]:
        """List all persisted session keys."""
        ...
