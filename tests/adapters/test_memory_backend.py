"""Tests for FileMemoryBackend -- file-based memory persistence."""

import json
from pathlib import Path

import pytest

from llm_harness.adapters.memory.backend import (
    MEMORY_SECTION_MEMORY,
    MEMORY_SECTION_PERSONA,
    MEMORY_SECTION_RULES,
    MEMORY_SECTION_USER,
)
from llm_harness.adapters.memory.file import FileMemoryBackend


class TestFileMemoryBackend:
    """FileMemoryBackend: section CRUD, namespaces, history, consolidation."""

    # ------------------------------------------------------------------
    # Section operations
    # ------------------------------------------------------------------

    async def test_append_and_read_section_round_trip(
        self, tmp_workspace: Path,
    ) -> None:
        """Appending to a section and reading it back must return the content."""
        backend = FileMemoryBackend(tmp_workspace)
        await backend.append_section("ns1", MEMORY_SECTION_MEMORY, "entry one")
        await backend.append_section("ns1", MEMORY_SECTION_MEMORY, "entry two")
        content = await backend.read_section("ns1", MEMORY_SECTION_MEMORY)
        assert "entry one" in content
        assert "entry two" in content

    async def test_read_section_empty_when_not_exists(
        self, tmp_workspace: Path,
    ) -> None:
        """Reading a section that has never been written must return empty string."""
        backend = FileMemoryBackend(tmp_workspace)
        content = await backend.read_section("ns-fresh", MEMORY_SECTION_RULES)
        assert content == ""

    async def test_get_context_returns_all_sections(self, tmp_workspace: Path) -> None:
        """get_context must return a formatted string containing all sections."""
        backend = FileMemoryBackend(tmp_workspace)
        await backend.append_section("ns-ctx", MEMORY_SECTION_MEMORY, "some memory")
        await backend.append_section("ns-ctx", MEMORY_SECTION_USER, "user info")
        context = await backend.get_context("ns-ctx")
        assert "MEMORY.md" in context
        assert "some memory" in context
        assert "USER.md" in context
        assert "user info" in context
        # Sections without content should show (empty)
        assert "SOUL.md" in context
        assert "(empty)" in context

    # ------------------------------------------------------------------
    # Namespace isolation
    # ------------------------------------------------------------------

    async def test_namespace_isolation(self, tmp_workspace: Path) -> None:
        """Different namespaces must not share data."""
        backend = FileMemoryBackend(tmp_workspace)
        await backend.append_section("alice", MEMORY_SECTION_MEMORY, "alice data")
        await backend.append_section("bob", MEMORY_SECTION_MEMORY, "bob data")
        alice = await backend.read_section("alice", MEMORY_SECTION_MEMORY)
        bob = await backend.read_section("bob", MEMORY_SECTION_MEMORY)
        assert "alice data" in alice
        assert "bob data" in bob
        assert "alice data" not in bob
        assert "bob data" not in alice

    # ------------------------------------------------------------------
    # Namespace sanitisation
    # ------------------------------------------------------------------

    async def test_colon_in_namespace_replaced(self, tmp_workspace: Path) -> None:
        """Colons in namespace names must be replaced with underscores."""
        backend = FileMemoryBackend(tmp_workspace)
        ns = "user:session:abc"
        await backend.append_section(ns, MEMORY_SECTION_MEMORY, "data")
        # The directory should use underscores, not colons
        dir_name = backend._dir(ns).name
        assert ":" not in dir_name
        assert "_" in dir_name
        # Round-trip must still work
        content = await backend.read_section(ns, MEMORY_SECTION_MEMORY)
        assert content == "data\n\n"

    async def test_path_traversal_namespace_blocked(self, tmp_workspace: Path) -> None:
        """Namespace containing '..' is sanitized (replaced with '__') to prevent traversal."""
        backend = FileMemoryBackend(tmp_workspace)
        result_dir = backend._dir("../../etc")
        # The path should be under base_dir (no traversal)
        assert str(result_dir).startswith(str(tmp_workspace.resolve()))
        # The '..' should have been replaced with '__'
        assert ".." not in result_dir.name

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    async def test_add_history_persists_records(self, tmp_workspace: Path) -> None:
        """Entries written via add_history must appear in history.jsonl."""
        backend = FileMemoryBackend(tmp_workspace)
        await backend.add_history("hist-ns", "user said hello")
        hist_file = tmp_workspace / "hist-ns" / "history.jsonl"
        assert hist_file.exists()
        lines = hist_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["entry"] == "user said hello"
        assert "timestamp" in record

    # ------------------------------------------------------------------
    # Consolidation
    # ------------------------------------------------------------------

    async def test_consolidate_without_provider_does_raw_archive(
        self, tmp_workspace: Path,
    ) -> None:
        """consolidate(namespace, messages, provider=None) must call _raw_archive."""
        backend = FileMemoryBackend(tmp_workspace)
        messages = [{"role": "user", "content": "hello", "timestamp": "2025-01-01T00:00:00"}]
        result = await backend.consolidate("raw-ns", messages)
        assert result is True
        hist_file = tmp_workspace / "raw-ns" / "history.jsonl"
        assert hist_file.exists()
        content = hist_file.read_text(encoding="utf-8")
        assert "RAW" in content
        assert "hello" in content

    async def test_consolidate_with_empty_messages_returns_true(
        self, tmp_workspace: Path,
    ) -> None:
        """consolidate with an empty message list must return True immediately."""
        backend = FileMemoryBackend(tmp_workspace)
        result = await backend.consolidate("empty-ns", [], provider=None)
        assert result is True

    # ------------------------------------------------------------------
    # _write_section_content overwrites
    # ------------------------------------------------------------------

    async def test_write_section_content_overwrites(self, tmp_workspace: Path) -> None:
        """_write_section_content must replace the entire file content."""
        backend = FileMemoryBackend(tmp_workspace)
        await backend.append_section("overwrite", MEMORY_SECTION_RULES, "old content")
        await backend._write_section_content("overwrite", MEMORY_SECTION_RULES, "new content")
        content = await backend.read_section("overwrite", MEMORY_SECTION_RULES)
        assert content == "new content"
        assert "old content" not in content
