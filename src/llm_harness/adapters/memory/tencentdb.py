"""TencentDB Agent Memory adapter — HTTP client for the TDAI Gateway.

Maps llm-harness MemoryBackend Protocol calls to the real TDAI Gateway API:

  get_context(ns)        → POST /recall        {query, session_key}
  read_section(ns, sec)  → POST /search/memories or POST /search/conversations
  append_section(ns,s,e) → POST /capture        {user_content, assistant_content, session_key}
  add_history(ns, entry) → POST /capture        (entry as user_content)
  consolidate(ns, msgs)  → POST /seed           {data: {sessions: [{session_key, rounds}]}}

Gateway: https://github.com/H-Mr/TencentDB-Agent-Memory
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from llm_harness.adapters.memory.backend import (
    MEMORY_SECTION_MEMORY,
    MEMORY_SECTION_PERSONA,
    MEMORY_SECTION_RULES,
    MEMORY_SECTION_USER,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:8420"
_SEED_TIMEOUT = 300  # seed can be slow with large datasets


class TencentDBMemoryBackend:
    """Memory backend backed by a TDAI Gateway sidecar.

    Parameters
    ----------
    base_url:
        Gateway base URL (default ``http://localhost:8420``).
    timeout:
        Default request timeout in seconds (default 30).
    api_key:
        Optional Bearer token. When set, every request attaches
        ``Authorization: Bearer <api_key>``.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 30.0,
        api_key: str | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._api_key = (api_key or "").strip() or None
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # client lifecycle
    # ------------------------------------------------------------------

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:
                return self._client
            headers: dict[str, str] = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers=headers,
            )
            return self._client

    async def close(self) -> None:
        async with self._client_lock:
            if self._client:
                await self._client.aclose()
                self._client = None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _post(self, path: str, body: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        client = await self._ensure_client()
        t = timeout or self._timeout
        resp = await client.post(f"{self._base_url}{path}", json=body, timeout=t)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # MemoryBackend Protocol
    # ------------------------------------------------------------------

    async def get_context(self, namespace: str) -> str:
        """Recall memories via POST /recall.

        Uses *namespace* as both session_key and query so the Gateway
        returns context relevant to the current session.
        """
        try:
            data = await self._post("/recall", {
                "query": namespace,
                "session_key": namespace,
            })
            return data.get("context", "")
        except Exception:
            logger.debug("TencentDB get_context failed", exc_info=True)
            return ""

    async def read_section(self, namespace: str, section: str) -> str:
        """Read a memory section by searching the Gateway index.

        ``section == "memory"`` searches L1 structured memories; other
        sections (rules, persona, user) search L0 raw conversations.
        """
        try:
            query = f"{section} {namespace}"
            if section == MEMORY_SECTION_MEMORY:
                data = await self._post("/search/memories", {
                    "query": query,
                    "limit": 10,
                })
            else:
                data = await self._post("/search/conversations", {
                    "query": query,
                    "limit": 10,
                    "session_key": namespace,
                })
            return self._format_search_results(data, section)
        except Exception:
            logger.debug("TencentDB read_section failed", exc_info=True)
            return ""

    async def append_section(self, namespace: str, section: str, entry: str) -> None:
        """Capture a memory write as a Gateway conversation turn.

        The Gateway pipeline will auto-extract structured memories from
        the captured content.
        """
        try:
            await self._post("/capture", {
                "user_content": f"[memory_write:{section}] {entry}",
                "assistant_content": "ok",
                "session_key": namespace,
            })
        except Exception:
            logger.warning("TencentDB append_section failed", exc_info=True)

    async def add_history(self, namespace: str, entry: str) -> None:
        """Capture a history entry as a Gateway conversation turn."""
        try:
            await self._post("/capture", {
                "user_content": entry,
                "assistant_content": "(system: history entry captured)",
                "session_key": namespace,
            })
        except Exception:
            logger.warning("TencentDB add_history failed", exc_info=True)

    async def consolidate(
        self,
        namespace: str,
        messages: list[dict[str, Any]],
        provider: Any = None,
        model: str = "",
    ) -> bool:
        """Consolidate messages into the Gateway via POST /seed.

        Messages are grouped into user-assistant round pairs and
        submitted as a session batch.
        """
        try:
            rounds = self._messages_to_rounds(messages)
            if not rounds:
                return True
            await self._post("/seed", {
                "data": {
                    "sessions": [{
                        "session_key": namespace,
                        "rounds": rounds,
                    }],
                },
            }, timeout=_SEED_TIMEOUT)
            return True
        except Exception:
            logger.exception("TencentDB consolidation failed")
            return False

    # ------------------------------------------------------------------
    # message conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _messages_to_rounds(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Convert a flat message list into user-assistant round pairs.

        Adjacent user→assistant messages become one round. Orphaned
        messages are paired with a placeholder.
        """
        rounds: list[dict[str, str]] = []
        pending_user: str | None = None

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    str(item.get("text", item)) if isinstance(item, dict) else str(item)
                    for item in content
                )
            content = str(content or "").strip()
            if not content:
                continue

            if role == "user":
                if pending_user is not None:
                    rounds.append({
                        "user_content": pending_user,
                        "assistant_content": "(no assistant response)",
                    })
                pending_user = content
            elif role in ("assistant", "tool"):
                if pending_user is not None:
                    rounds.append({
                        "user_content": pending_user,
                        "assistant_content": content,
                    })
                    pending_user = None
                else:
                    rounds.append({
                        "user_content": f"[{role}] {content}",
                        "assistant_content": "(system: captured)",
                    })

        # flush remaining
        if pending_user is not None:
            rounds.append({
                "user_content": pending_user,
                "assistant_content": "(no assistant response)",
            })

        return rounds

    @staticmethod
    def _format_search_results(data: dict[str, Any], section: str) -> str:
        """Format Gateway search results as readable text."""
        results = data.get("results") or data.get("memories") or []
        if not results:
            return ""

        lines = [f"## {section}"]
        for item in results[:10]:
            if isinstance(item, dict):
                title = item.get("title") or item.get("memory", "")[:80]
                content = item.get("content") or item.get("text") or ""
                score = item.get("score") or item.get("relevance")
                line = f"- **{title}**"
                if score is not None:
                    line += f" ({score})"
                if content:
                    line += f"\n  {content[:200]}"
                lines.append(line)
            else:
                lines.append(f"- {str(item)[:200]}")
        return "\n".join(lines)
