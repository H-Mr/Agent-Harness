"""MemoryBackend Protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

MEMORY_SECTION_MEMORY = "memory"
MEMORY_SECTION_RULES = "rules"
MEMORY_SECTION_PERSONA = "persona"
MEMORY_SECTION_USER = "user"


@runtime_checkable
class MemoryBackend(Protocol):
    async def get_context(self, namespace: str) -> str: ...
    async def read_section(self, namespace: str, section: str) -> str: ...
    async def append_section(self, namespace: str, section: str, entry: str) -> None: ...
    async def consolidate(self, namespace: str, messages: list[dict[str, Any]], provider: Any = None, model: str = "") -> bool: ...
