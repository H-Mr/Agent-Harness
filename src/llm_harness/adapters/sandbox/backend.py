"""SandboxBackend Protocol — file operations + exec, all via sandbox."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class SandboxSession:
    session_key: str
    volume_path: str     # Container mount path (what LLM sees)
    sandbox_id: str      # Backend-internal identifier


@dataclass
class ExecResult:
    output: str
    exit_code: int = 0
    is_error: bool = False


@runtime_checkable
class SandboxBackend(Protocol):
    async def create_session(self, session_key: str) -> SandboxSession: ...
    async def destroy_session(self, session_key: str) -> None: ...
    async def read_file(self, session_key: str, path: str) -> str: ...
    async def write_file(self, session_key: str, path: str, content: str) -> None: ...
    async def list_dir(self, session_key: str, path: str) -> list[str]: ...
    async def glob(self, session_key: str, pattern: str) -> list[str]: ...
    async def grep(self, session_key: str, pattern: str, path: str) -> list[str]: ...
    async def execute(self, session_key: str, command: str, *, cwd: str = "/workspace", env: dict | None = None, timeout: int = 60) -> ExecResult: ...
