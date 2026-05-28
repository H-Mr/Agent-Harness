"""TencentDB Agent Memory adapter — HTTP to localhost:8420."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from llm_harness.adapters.memory.backend import MemoryBackend

logger = logging.getLogger(__name__)


class TencentDBMemoryBackend:
    def __init__(self, base_url: str = "http://localhost:8420", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:
                return self._client
            self._client = httpx.AsyncClient(timeout=self._timeout)
            return self._client

    async def close(self) -> None:
        async with self._client_lock:
            if self._client:
                await self._client.aclose()
                self._client = None

    async def get_context(self, namespace: str) -> str:
        client = await self._ensure_client()
        try:
            resp = await client.get(f"{self.base_url}/memory/{namespace}/context")
            resp.raise_for_status()
            data = resp.json()
            return data.get("context", data.get("content", str(data)))
        except Exception:
            logger.debug("TencentDB get_context failed", exc_info=True)
            return ""

    async def read_section(self, namespace: str, section: str) -> str:
        client = await self._ensure_client()
        try:
            resp = await client.get(f"{self.base_url}/memory/{namespace}/{section}")
            resp.raise_for_status()
            return resp.json().get("content", "")
        except Exception:
            logger.debug("TencentDB read_section failed", exc_info=True)
            return ""

    async def append_section(self, namespace: str, section: str, entry: str) -> None:
        client = await self._ensure_client()
        try:
            await client.post(f"{self.base_url}/memory/{namespace}/{section}", json={"entry": entry})
        except Exception:
            logger.warning("TencentDB append_section failed", exc_info=True)

    async def add_history(self, namespace: str, entry: str) -> None:
        client = await self._ensure_client()
        try:
            await client.post(f"{self.base_url}/memory/{namespace}/history", json={"entry": entry})
        except Exception:
            logger.warning("TencentDB add_history failed", exc_info=True)

    async def consolidate(self, namespace: str, messages: list[dict[str, Any]], provider: Any = None, model: str = "") -> bool:
        client = await self._ensure_client()
        try:
            resp = await client.post(f"{self.base_url}/memory/{namespace}/ingest", json={"messages": messages})
            resp.raise_for_status()
            return True
        except Exception:
            logger.exception("TencentDB consolidation failed")
            return False
