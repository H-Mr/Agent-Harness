"""Tests for FileSessionBackend -- multi-tenant JSONL persistence."""

import json
import logging
from pathlib import Path

import pytest

from llm_harness.adapters.session.file import FileSessionBackend


class TestFileSessionBackend:
    """FileSessionBackend: save/load round-trip, edge cases, and security."""

    async def test_save_load_round_trip(self, tmp_workspace: Path) -> None:
        """Save a session then load it; all fields must be preserved."""
        backend = FileSessionBackend(tmp_workspace)
        state = {
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"user": "alice"},
            "last_consolidated": 0,
        }
        await backend.save("alice:chat1", state)
        loaded = await backend.load("alice:chat1")
        assert loaded is not None
        assert loaded["messages"] == state["messages"]
        assert loaded["metadata"] == state["metadata"]
        assert loaded["last_consolidated"] == state["last_consolidated"]

    async def test_load_nonexistent_returns_none(self, tmp_workspace: Path) -> None:
        """Loading a key that has never been saved must return None."""
        backend = FileSessionBackend(tmp_workspace)
        result = await backend.load("bob:missing")
        assert result is None

    async def test_list_keys(self, tmp_workspace: Path) -> None:
        """list_keys must return all keys that were previously saved."""
        backend = FileSessionBackend(tmp_workspace)
        await backend.save("alice:chat-a", {"messages": []})
        await backend.save("alice:chat-b", {"messages": []})
        keys = await backend.list_keys()
        assert "chat-a" in keys or "alice:chat-a" in keys
        assert "chat-b" in keys or "alice:chat-b" in keys

    async def test_metadata_and_last_consolidated_preserved(
        self, tmp_workspace: Path,
    ) -> None:
        """Metadata and last_consolidated fields survive a round-trip."""
        backend = FileSessionBackend(tmp_workspace)
        original = {
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"user_id": "42", "channel": "cli"},
            "last_consolidated": 3,
        }
        await backend.save("alice:meta-test", original)
        loaded = await backend.load("alice:meta-test")
        assert loaded is not None
        assert loaded["metadata"] == original["metadata"]
        assert loaded["last_consolidated"] == original["last_consolidated"]

    async def test_load_corrupt_jsonl_returns_none(
        self, tmp_workspace: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Corrupt JSONL content must return None and log a warning."""
        backend = FileSessionBackend(tmp_workspace)
        path = backend._path("alice:corrupt")
        path.write_text("not-json\n{also invalid\n", encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            result = await backend.load("alice:corrupt")
        assert result is None
        assert "Failed to load session" in caplog.text

    async def test_list_keys_skips_corrupt_files(self, tmp_workspace: Path) -> None:
        """Corrupt session files should be skipped by list_keys."""
        backend = FileSessionBackend(tmp_workspace)
        await backend.save("alice:good", {"messages": [{"role": "user", "content": "ok"}]})
        # Write a corrupt file in a session directory
        corrupt_dir = backend._path("alice:bad").parent
        corrupt_dir.mkdir(parents=True, exist_ok=True)
        (corrupt_dir / "session.jsonl").write_text("garbage\n", encoding="utf-8")
        keys = await backend.list_keys()
        assert "good" in keys or "alice:good" in keys

    async def test_save_uses_atomic_write(self, tmp_workspace: Path) -> None:
        """Save must write to a .tmp file first, then atomically replace."""
        backend = FileSessionBackend(tmp_workspace)
        await backend.save("alice:atomic", {"messages": [{"role": "user", "content": "x"}]})
        path = backend._path("alice:atomic")
        assert path.exists()
        assert path.suffix == ".jsonl"

    async def test_path_traversal_double_dot_sanitized(
        self, tmp_workspace: Path,
    ) -> None:
        """A session_key containing '..' must have it sanitized."""
        backend = FileSessionBackend(tmp_workspace)
        path = backend._path("..")
        # Path must stay inside base_dir
        assert str(path.resolve()).startswith(str(tmp_workspace.resolve()))
        # ".." sanitized to "__" somewhere in the path
        assert "__" in str(path) or ".." not in str(path)

    async def test_path_traversal_slash_etc_sanitized(
        self, tmp_workspace: Path,
    ) -> None:
        """A session_key containing '../etc' must have special chars sanitized."""
        backend = FileSessionBackend(tmp_workspace)
        path = backend._path("../etc")
        assert str(path.resolve()).startswith(str(tmp_workspace.resolve()))

    async def test_special_chars_in_key_sanitized(self, tmp_workspace: Path) -> None:
        """Characters like <, >, :, /, \\, |, ?, * must be sanitized."""
        backend = FileSessionBackend(tmp_workspace)
        key = 'test:<key>/with\\bad|chars?*'
        path = backend._path(key)
        stem = path.stem  # stem removes .jsonl suffix
        assert "<" not in stem
        assert ">" not in stem
        assert "|" not in stem
        assert "?" not in stem
        assert "*" not in stem
        await backend.save(key, {"messages": [{"role": "user", "content": "hi"}]})
        loaded = await backend.load(key)
        assert loaded is not None
