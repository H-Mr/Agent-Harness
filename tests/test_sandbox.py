"""Tests for SRTSandboxBackend: path enforcement, file operations, exec."""

import pytest
from llm_harness.adapters.sandbox.srt import SRTSandboxBackend


class TestPathEnforcement:
    """All file paths must stay within workspace root."""

    def test_read_within_workspace(self, tmp_path):
        (tmp_path / "f.txt").write_text("hello")
        sandbox = SRTSandboxBackend(tmp_path)

        async def run():
            result = await sandbox.read_file("s1", "f.txt")
            assert result == "hello"
        pytest.importorskip("pytest_asyncio", reason="needs pytest-asyncio")
        import asyncio
        asyncio.run(run())

    def test_traversal_blocked(self, tmp_path):
        sandbox = SRTSandboxBackend(tmp_path)

        async def run():
            with pytest.raises(PermissionError, match="traversal"):
                await sandbox.read_file("s1", "../etc/passwd")
        import asyncio
        asyncio.run(run())

    def test_glob_returns_relative_paths(self, tmp_path):
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        sandbox = SRTSandboxBackend(tmp_path)

        async def run():
            results = await sandbox.glob("s1", "*.py")
            assert sorted(results) == ["a.py", "b.py"]
        import asyncio
        asyncio.run(run())


class TestSessionStubs:
    """create_session / destroy_session are no-ops with valid return."""

    def test_create_session_returns_session(self, tmp_path):
        sandbox = SRTSandboxBackend(tmp_path)

        async def run():
            s = await sandbox.create_session("key")
            assert s.session_key == "key"
            assert s.sandbox_id == "srt"
        import asyncio
        asyncio.run(run())

    def test_destroy_session_is_noop(self, tmp_path):
        sandbox = SRTSandboxBackend(tmp_path)

        async def run():
            await sandbox.destroy_session("any")  # does not raise
        import asyncio
        asyncio.run(run())


class TestWriteAndRead:
    def test_write_creates_parent_dirs(self, tmp_path):
        sandbox = SRTSandboxBackend(tmp_path)

        async def run():
            await sandbox.write_file("s1", "sub/dir/f.txt", "content")
            assert (tmp_path / "sub" / "dir" / "f.txt").read_text() == "content"
        import asyncio
        asyncio.run(run())
