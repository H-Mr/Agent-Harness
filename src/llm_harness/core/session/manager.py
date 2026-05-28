"""SessionManager — wraps SessionBackend with in-memory caching."""

from __future__ import annotations

import logging

from llm_harness.adapters.session.backend import SessionBackend
from llm_harness.core.session.session import Session

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, backend: SessionBackend, *, cache_max_size: int = 1000):
        self.backend = backend
        self._cache: dict[str, Session] = {}
        self._cache_max_size = cache_max_size

    async def get_or_create(self, key: str) -> Session:
        if key in self._cache:
            return self._cache[key]
        state = await self.backend.load(key)
        if state:
            session = Session(
                key=key, messages=state.get("messages", []),
                metadata=state.get("metadata", {}),
                last_consolidated=state.get("last_consolidated", 0),
            )
        else:
            session = Session(key=key)

        if len(self._cache) >= self._cache_max_size:
            overflow = len(self._cache) - self._cache_max_size + 1
            for stale_key in list(self._cache)[:overflow]:
                if stale_key != key:
                    self._cache.pop(stale_key, None)

        self._cache[key] = session
        return session

    async def save(self, session: Session) -> None:
        await self.backend.save(session.key, session.to_state())

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

    async def list_keys(self) -> list[str]:
        return await self.backend.list_keys()
