"""OpenSandbox adapter — container + volume isolation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from llm_harness.adapters.sandbox.backend import ExecResult, SandboxBackend, SandboxSession

logger = logging.getLogger(__name__)


class OpenSandboxBackend:
    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        self._sessions: dict[str, SandboxSession] = {}

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:
                return self._client
            self._client = httpx.AsyncClient(timeout=self._timeout)
            return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def create_session(self, session_key: str) -> SandboxSession:
        client = await self._ensure_client()
        resp = await client.post(f"{self.base_url}/sandboxes", json={"name": session_key.replace(":", "-")})
        resp.raise_for_status()
        data = resp.json()
        session = SandboxSession(
            session_key=session_key,
            volume_path=data.get("mount_path", "/workspace"),
            sandbox_id=data.get("sandbox_id", session_key),
        )
        self._sessions[session_key] = session
        return session

    async def destroy_session(self, session_key: str) -> None:
        session = self._sessions.pop(session_key, None)
        if session is None:
            return
        client = await self._ensure_client()
        try:
            await client.delete(f"{self.base_url}/sandboxes/{session.sandbox_id}")
        except Exception:
            logger.warning("Failed to destroy sandbox", exc_info=True)

    async def read_file(self, session_key: str, path: str) -> str:
        session = self._sessions.get(session_key)
        if not session:
            return f"Error: session {session_key} not found"
        client = await self._ensure_client()
        resp = await client.get(f"{self.base_url}/sandboxes/{session.sandbox_id}/files", params={"path": path})
        resp.raise_for_status()
        return resp.text

    async def write_file(self, session_key: str, path: str, content: str) -> None:
        session = self._sessions.get(session_key)
        if not session:
            return
        client = await self._ensure_client()
        await client.post(f"{self.base_url}/sandboxes/{session.sandbox_id}/files", json={"path": path, "content": content})

    async def list_dir(self, session_key: str, path: str) -> list[str]:
        session = self._sessions.get(session_key)
        if not session:
            return []
        client = await self._ensure_client()
        resp = await client.get(f"{self.base_url}/sandboxes/{session.sandbox_id}/files/list", params={"path": path})
        return resp.json() if resp.status_code == 200 else []

    async def glob(self, session_key: str, pattern: str) -> list[str]:
        session = self._sessions.get(session_key)
        if not session:
            return []
        client = await self._ensure_client()
        resp = await client.get(f"{self.base_url}/sandboxes/{session.sandbox_id}/files/glob", params={"pattern": pattern})
        return resp.json() if resp.status_code == 200 else []

    async def grep(self, session_key: str, pattern: str, path: str) -> list[str]:
        session = self._sessions.get(session_key)
        if not session:
            return []
        client = await self._ensure_client()
        resp = await client.get(f"{self.base_url}/sandboxes/{session.sandbox_id}/files/grep", params={"pattern": pattern, "path": path})
        return resp.json() if resp.status_code == 200 else []

    async def execute(self, session_key: str, command: str, *, cwd: str = "/workspace", env: dict[str, str] | None = None, timeout: int = 60) -> ExecResult:
        session = self._sessions.get(session_key)
        if not session:
            return ExecResult(output=f"Error: session {session_key} not found", exit_code=1, is_error=True)
        client = await self._ensure_client()
        try:
            resp = await client.post(
                f"{self.base_url}/sandboxes/{session.sandbox_id}/exec",
                json={"command": command, "cwd": cwd, "env": env or {}, "timeout": timeout},
            )
            resp.raise_for_status()
            data = resp.json()
            return ExecResult(output=data.get("output", ""), exit_code=data.get("exit_code", 0))
        except httpx.HTTPError as e:
            return ExecResult(output=f"Sandbox error: {e}", exit_code=1, is_error=True)
