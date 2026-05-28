"""AgentBackend Protocol for sub-agent execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class SpawnConfig:
    agent_name: str
    prompt: str
    tool_names: list[str]
    model: str = ""


@dataclass
class SpawnResult:
    agent_id: str
    success: bool = True
    error: str | None = None


@runtime_checkable
class AgentBackend(Protocol):
    async def spawn(self, config: SpawnConfig) -> SpawnResult: ...
    async def send_message(self, agent_id: str, message: str) -> bool: ...
    async def stop(self, agent_id: str) -> bool: ...
