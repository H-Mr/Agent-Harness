"""Tests for SessionManager: cache eviction and size limits."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from llm_harness.core.session.manager import SessionManager


class TestCacheEviction:
    """SessionManager must evict oldest cache entries when exceeding max_size."""

    @pytest.fixture
    def backend(self):
        """SessionBackend that returns None (new sessions) for all keys."""
        be = AsyncMock()
        be.load = AsyncMock(return_value=None)
        be.save = AsyncMock()
        return be

    @pytest.fixture
    def manager(self, backend):
        mgr = SessionManager(backend)
        mgr._cache_max_size = 3
        return mgr

    @pytest.mark.asyncio
    async def test_cache_max_size_default(self, backend):
        """Default max_size is set and reasonable."""
        mgr = SessionManager(backend)
        assert mgr._cache_max_size > 0
        assert mgr._cache_max_size <= 10_000

    @pytest.mark.asyncio
    async def test_evicts_oldest_on_overflow(self, manager):
        """Oldest cache entries are evicted when max_size exceeded."""
        for i in range(5):
            await manager.get_or_create(f"session:{i}")

        # Only 3 should remain (max_size=3), oldest 2 evicted
        assert len(manager._cache) == 3
        assert "session:0" not in manager._cache
        assert "session:1" not in manager._cache
        assert "session:2" in manager._cache
        assert "session:3" in manager._cache
        assert "session:4" in manager._cache

    @pytest.mark.asyncio
    async def test_oldest_evicted_by_insertion_order(self, manager):
        """Oldest sessions by insertion order are evicted first."""
        for i in range(3):
            await manager.get_or_create(f"session:{i}")

        # Add 2 more, triggering eviction
        await manager.get_or_create("session:3")
        await manager.get_or_create("session:4")

        # Oldest inserted (session:0, session:1) should be evicted
        assert "session:0" not in manager._cache
        assert "session:1" not in manager._cache
        # Most recently inserted survive
        assert "session:2" in manager._cache
        assert "session:3" in manager._cache
        assert "session:4" in manager._cache

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_reload(self, manager):
        """get_or_create returns cached session without calling backend.load again."""
        await manager.get_or_create("session:0")
        # Second call should return cached session, no second load
        await manager.get_or_create("session:0")

        # backend.load called only once (on first get_or_create)
        assert manager.backend.load.call_count == 1

    @pytest.mark.asyncio
    async def test_overflow_does_not_lose_all(self, manager):
        """When adding many sessions, the cache stays within max_size but is not empty."""
        for i in range(50):
            await manager.get_or_create(f"session:{i}")

        assert len(manager._cache) <= manager._cache_max_size
        assert len(manager._cache) > 0
