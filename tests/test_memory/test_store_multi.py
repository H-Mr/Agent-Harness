"""Test per-session multi-file MemoryStore."""

import tempfile
from pathlib import Path

from agent_harness.memory.store import MemoryStore


def test_write_and_read_files():
    d = Path(tempfile.mkdtemp())
    store = MemoryStore(d, session_key="test:abc")

    store.write_file("MEMORY.md", "User prefers Python")
    store.write_file("AGENTS.md", "Use ruff for linting")
    store.write_file("SOUL.md", "Be concise")
    store.write_file("USER.md", "Senior engineer")

    assert store.read_file("MEMORY.md") == "User prefers Python"
    assert store.read_file("AGENTS.md") == "Use ruff for linting"
    assert store.read_file("SOUL.md") == "Be concise"
    assert store.read_file("USER.md") == "Senior engineer"


def test_read_nonexistent_file_returns_empty():
    d = Path(tempfile.mkdtemp())
    store = MemoryStore(d, session_key="test:xyz")
    assert store.read_file("MEMORY.md") == ""


def test_get_all_files():
    d = Path(tempfile.mkdtemp())
    store = MemoryStore(d, session_key="test:def")
    store.write_file("MEMORY.md", "memory")
    store.write_file("AGENTS.md", "agents")

    all_files = store.get_all_files()
    assert all_files["MEMORY.md"] == "memory"
    assert all_files["AGENTS.md"] == "agents"
    assert all_files["SOUL.md"] == ""
    assert all_files["USER.md"] == ""


def test_append_history_and_raw_messages():
    d = Path(tempfile.mkdtemp())
    store = MemoryStore(d, session_key="test:hist")

    store.append_history("[2026-05-27 10:00] User asked about Python")
    store.append_raw_messages([
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ])

    content = store.history_file.read_text()
    assert "[2026-05-27 10:00]" in content
    assert '"role": "user"' in content
    assert '"role": "assistant"' in content


def test_get_context():
    d = Path(tempfile.mkdtemp())
    store = MemoryStore(d, session_key="test:ctx")
    store.write_file("MEMORY.md", "fact")

    ctx = store.get_context()
    assert "## AGENTS.md" in ctx
    assert "## SOUL.md" in ctx
    assert "## MEMORY.md" in ctx
    assert "fact" in ctx
    assert "## USER.md" in ctx


def test_backward_compat_api():
    d = Path(tempfile.mkdtemp())
    store = MemoryStore(d, session_key="test:bw")

    store.write_long_term("legacy memory")
    assert store.read_long_term() == "legacy memory"

    ctx = store.get_memory_context()
    assert "legacy memory" in ctx
