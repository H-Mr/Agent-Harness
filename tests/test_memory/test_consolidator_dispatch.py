"""Test MemoryConsolidator policy dispatch, per-session stores, and 5-field consolidation."""

import asyncio
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from agent_harness.memory.consolidator import (
    MemoryConsolidator,
    _SAVE_MEMORY_TOOL,
    _ensure_text,
    _format_messages,
    _normalize_save_memory_args,
)
from agent_harness.memory.policy import MessageCountPolicy, TokenBudgetPolicy
from agent_harness.memory.store import MemoryStore
from agent_harness.providers.base import LLMResponse, ToolCallRequest
from agent_harness.session.manager import Session, SessionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SESSION_KEY = "test:dispatch"


def _make_consolidator(
    tmp_path: Path,
    provider=None,
    policy=None,
    model: str = "test-model",
    context_window_tokens: int = 200000,
):
    provider = provider or AsyncMock()
    return MemoryConsolidator(
        workspace=tmp_path,
        provider=provider,
        model=model,
        sessions=SessionManager(tmp_path),
        context_window_tokens=context_window_tokens,
        build_messages=lambda **kw: [],
        get_tool_definitions=lambda: [],
        policy=policy,
    )


def _ok_tool_response(history_entry: str = "[2026-05-27 10:00] Test.", memory_update: str = "# Test\nOK."):
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(
                id="call_1",
                name="save_memory",
                arguments={
                    "history_entry": history_entry,
                    "memory_update": memory_update,
                },
            )
        ],
    )


def _multi_field_response(
    history_entry: str = "[2026-05-27 10:00] Multi.",
    memory_update: str = "# Memory\nUpdated.",
    agents_update: str | None = None,
    soul_update: str | None = None,
    user_update: str | None = None,
):
    args = {
        "history_entry": history_entry,
        "memory_update": memory_update,
    }
    if agents_update is not None:
        args["agents_update"] = agents_update
    if soul_update is not None:
        args["soul_update"] = soul_update
    if user_update is not None:
        args["user_update"] = user_update
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(id="call_1", name="save_memory", arguments=args)
        ],
    )


# ---------------------------------------------------------------------------
# Tests: save_memory tool definition
# ---------------------------------------------------------------------------

class TestSaveMemoryTool:
    """The 5-field save_memory tool definition."""

    def test_memory_update_and_history_entry_are_required(self):
        tool = _SAVE_MEMORY_TOOL[0]["function"]
        required = tool["parameters"]["required"]
        assert "memory_update" in required
        assert "history_entry" in required
        assert "agents_update" not in required
        assert "soul_update" not in required
        assert "user_update" not in required

    def test_nullable_fields_accept_null_type(self):
        tool = _SAVE_MEMORY_TOOL[0]["function"]
        props = tool["parameters"]["properties"]
        assert props["agents_update"]["type"] == ["string", "null"]
        assert props["soul_update"]["type"] == ["string", "null"]
        assert props["user_update"]["type"] == ["string", "null"]
        # memory_update is required and not nullable
        assert props["memory_update"]["type"] == "string"


# ---------------------------------------------------------------------------
# Tests: per-session store cache
# ---------------------------------------------------------------------------

class TestPerSessionStores:
    """MemoryConsolidator._get_store returns isolated per-session MemoryStores."""

    def test_get_store_creates_new_store(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        store = c._get_store("a:b")
        assert isinstance(store, MemoryStore)
        assert store.memory_dir == tmp_path / "memory" / "a_b"

    def test_same_key_returns_same_store(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        s1 = c._get_store("a:b")
        s2 = c._get_store("a:b")
        assert s1 is s2

    def test_different_keys_return_different_stores(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        s1 = c._get_store("a:1")
        s2 = c._get_store("a:2")
        assert s1 is not s2
        assert s1.memory_dir == tmp_path / "memory" / "a_1"
        assert s2.memory_dir == tmp_path / "memory" / "a_2"

    def test_stores_are_isolated(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        s1 = c._get_store("a:1")
        s2 = c._get_store("a:2")

        s1.write_file("MEMORY.md", "memory for 1")
        s2.write_file("MEMORY.md", "memory for 2")

        assert s1.read_file("MEMORY.md") == "memory for 1"
        assert s2.read_file("MEMORY.md") == "memory for 2"


# ---------------------------------------------------------------------------
# Tests: _build_consolidation_prompt
# ---------------------------------------------------------------------------

class TestBuildConsolidationPrompt:
    """The prompt includes current memory state and conversation to process."""

    def test_includes_all_memory_files(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        prompt = c._build_consolidation_prompt(
            messages=[{"role": "user", "content": "hello", "timestamp": "2026-05-27 10:00"}],
            current_files={
                "AGENTS.md": "Use ruff",
                "SOUL.md": "Be concise",
                "MEMORY.md": "User likes Python",
                "USER.md": "Senior engineer",
            },
        )
        assert "AGENTS.md" in prompt
        assert "SOUL.md" in prompt
        assert "MEMORY.md" in prompt
        assert "USER.md" in prompt
        assert "Use ruff" in prompt
        assert "Be concise" in prompt
        assert "User likes Python" in prompt
        assert "Senior engineer" in prompt

    def test_empty_files_show_empty(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        prompt = c._build_consolidation_prompt(
            messages=[],
            current_files={},
        )
        assert "(empty)" in prompt

    def test_includes_conversation_messages(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        prompt = c._build_consolidation_prompt(
            messages=[
                {"role": "user", "content": "hi", "timestamp": "2026-05-27 10:00"},
                {"role": "assistant", "content": "hello", "timestamp": "2026-05-27 10:01"},
            ],
            current_files={},
        )
        assert "USER: hi" in prompt
        assert "ASSISTANT: hello" in prompt

    def test_includes_file_responsibilities(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        prompt = c._build_consolidation_prompt([], {})
        assert "agents_update" in prompt
        assert "soul_update" in prompt
        assert "memory_update" in prompt
        assert "user_update" in prompt
        assert "history_entry" in prompt


# ---------------------------------------------------------------------------
# Tests: 5-field consolidation output
# ---------------------------------------------------------------------------

class TestConsolidateChunk5Field:
    """_consolidate_chunk writes all 5 non-null fields to correct files."""

    @pytest.mark.asyncio
    async def test_writes_memory_and_history(self, tmp_path: Path):
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(
            return_value=_ok_tool_response(
                history_entry="[2026-05-27 10:00] User chatted.",
                memory_update="# Memory\nUser likes Python.",
            )
        )
        c = _make_consolidator(tmp_path, provider)

        result = await c._consolidate_chunk(SESSION_KEY, [{"role": "user", "content": "hi", "timestamp": "2026-05-27 10:00"}])

        assert result is True
        store = c._get_store(SESSION_KEY)
        assert "User likes Python" in store.read_file("MEMORY.md")
        history = store.history_file.read_text()
        assert "[2026-05-27 10:00] User chatted." in history

    @pytest.mark.asyncio
    async def test_writes_agents_soul_user_when_provided(self, tmp_path: Path):
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(
            return_value=_multi_field_response(
                history_entry="[2026-05-27 10:00] Multi-field.",
                memory_update="# Memory\nUpdated.",
                agents_update="Use pip",
                soul_update="Be friendly",
                user_update="Junior dev",
            )
        )
        c = _make_consolidator(tmp_path, provider)

        result = await c._consolidate_chunk(SESSION_KEY, [{"role": "user", "content": "hi"}])

        assert result is True
        store = c._get_store(SESSION_KEY)
        assert store.read_file("AGENTS.md") == "Use pip"
        assert store.read_file("SOUL.md") == "Be friendly"
        assert store.read_file("MEMORY.md") == "# Memory\nUpdated."
        assert store.read_file("USER.md") == "Junior dev"

    @pytest.mark.asyncio
    async def test_noop_when_value_unchanged(self, tmp_path: Path):
        """If the LLM returns the same value that's already on disk, don't overwrite."""
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(
            return_value=_multi_field_response(
                history_entry="[2026-05-27 10:00] No change.",
                memory_update="# Memory\nSame content.",
            )
        )
        c = _make_consolidator(tmp_path, provider=provider)
        store = c._get_store(SESSION_KEY)
        store.write_file("MEMORY.md", "# Memory\nSame content.")

        result = await c._consolidate_chunk(SESSION_KEY, [{"role": "user", "content": "hi"}])

        assert result is True
        # Content should be unchanged on disk
        assert store.read_file("MEMORY.md") == "# Memory\nSame content."

    @pytest.mark.asyncio
    async def test_appends_raw_messages(self, tmp_path: Path):
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(return_value=_ok_tool_response())
        c = _make_consolidator(tmp_path, provider)
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

        await c._consolidate_chunk(SESSION_KEY, messages)

        store = c._get_store(SESSION_KEY)
        content = store.history_file.read_text()
        assert '"role": "user"' in content
        assert '"role": "assistant"' in content


# ---------------------------------------------------------------------------
# Tests: _fallback_raw_archive
# ---------------------------------------------------------------------------

class TestFallbackRawArchive:
    """_fallback_raw_archive increments failure count and raw-archives after threshold."""

    def test_returns_false_under_threshold(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        store = c._get_store(SESSION_KEY)
        assert c._fallback_raw_archive(store, [{"role": "user", "content": "x"}]) is False
        assert c._consecutive_failures == 1

    def test_raw_archives_after_threshold(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        store = c._get_store(SESSION_KEY)
        msg = [{"role": "user", "content": "msg"}]
        assert c._fallback_raw_archive(store, msg) is False
        assert c._fallback_raw_archive(store, msg) is False
        assert c._fallback_raw_archive(store, msg) is True
        assert c._consecutive_failures == 0

        content = store.history_file.read_text()
        assert "[RAW]" in content
        assert "1 messages" in content

    def test_counter_resets_after_raw_archive(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        store = c._get_store(SESSION_KEY)
        for _ in range(3):
            c._fallback_raw_archive(store, [{"role": "user", "content": "x"}])
        assert c._consecutive_failures == 0


# ---------------------------------------------------------------------------
# Tests: archive_messages (guaranteed persistence)
# ---------------------------------------------------------------------------

class TestArchiveMessages:
    """archive_messages guarantees persistence via raw-dump fallback."""

    @pytest.mark.asyncio
    async def test_returns_true_for_empty_messages(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        result = await c.archive_messages(SESSION_KEY, [])
        assert result is True

    @pytest.mark.asyncio
    async def test_guarantees_persistence_after_failures(self, tmp_path: Path):
        """After all retries fail, raw-dump fallback is used."""
        no_tool = LLMResponse(content="No.", finish_reason="stop", tool_calls=[])
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(return_value=no_tool)
        c = _make_consolidator(tmp_path, provider)

        result = await c.archive_messages(SESSION_KEY, [{"role": "user", "content": "hi"}])

        assert result is True
        store = c._get_store(SESSION_KEY)
        assert store.history_file.exists()
        assert "[RAW]" in store.history_file.read_text()

    @pytest.mark.asyncio
    async def test_succeeds_on_first_retry(self, tmp_path: Path):
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(
            return_value=_ok_tool_response(
                history_entry="[2026-05-27 10:00] OK.",
                memory_update="# Memory\nOK.",
            )
        )
        c = _make_consolidator(tmp_path, provider=provider)

        result = await c.archive_messages(SESSION_KEY, [{"role": "user", "content": "hi"}])

        assert result is True
        store = c._get_store(SESSION_KEY)
        assert "OK." in store.read_file("MEMORY.md")


# ---------------------------------------------------------------------------
# Tests: maybe_consolidate (policy dispatch)
# ---------------------------------------------------------------------------

class TestMaybeConsolidate:
    """maybe_consolidate dispatches to the configured policy and removes messages."""

    @pytest.mark.asyncio
    async def test_noop_when_policy_returns_none(self, tmp_path: Path):
        policy = MagicMock()
        policy.should_consolidate = AsyncMock(return_value=None)
        c = _make_consolidator(tmp_path, policy=policy)
        session = Session(key=SESSION_KEY)
        session.add_message("user", "hello")
        session.add_message("assistant", "hi")

        await c.maybe_consolidate(session)

        policy.should_consolidate.assert_awaited_once()
        assert len(session.messages) == 2  # unchanged

    @pytest.mark.asyncio
    async def test_noop_when_policy_returns_empty_list(self, tmp_path: Path):
        policy = MagicMock()
        policy.should_consolidate = AsyncMock(return_value=[])
        c = _make_consolidator(tmp_path, policy=policy)
        session = Session(key=SESSION_KEY)
        session.add_message("user", "hello")

        await c.maybe_consolidate(session)

        assert len(session.messages) == 1  # unchanged

    @pytest.mark.asyncio
    async def test_noop_when_session_has_no_messages(self, tmp_path: Path):
        policy = MagicMock()
        c = _make_consolidator(tmp_path, policy=policy)
        session = Session(key=SESSION_KEY)

        await c.maybe_consolidate(session)

        policy.should_consolidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_consolidates_and_removes_messages(self, tmp_path: Path):
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(
            return_value=_ok_tool_response(
                history_entry="[2026-05-27 10:00] Consolidated.",
                memory_update="# Memory\nConsolidated OK.",
            )
        )
        policy = MagicMock()
        session = Session(key=SESSION_KEY)
        for i in range(10):
            session.add_message("user", f"msg {i}")
            session.add_message("assistant", f"reply {i}")

        chunk = session.messages[:10]
        policy.should_consolidate = AsyncMock(side_effect=[chunk, None])
        c = _make_consolidator(tmp_path, provider, policy=policy)

        await c.maybe_consolidate(session)

        # Messages before end_idx should be removed
        assert len(session.messages) == 10  # 20 - 10 removed
        store = c._get_store(SESSION_KEY)
        assert "Consolidated OK." in store.read_file("MEMORY.md")

    @pytest.mark.asyncio
    async def test_stops_when_consolidation_fails(self, tmp_path: Path):
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="no tool", finish_reason="stop", tool_calls=[])
        )
        policy = MagicMock()
        session = Session(key=SESSION_KEY)
        for i in range(10):
            session.add_message("user", f"msg {i}")

        chunk = session.messages[:5]
        policy.should_consolidate = AsyncMock(return_value=chunk)
        c = _make_consolidator(tmp_path, provider, policy=policy)

        await c.maybe_consolidate(session)

        # Should NOT remove messages since consolidation failed (under threshold)
        assert len(session.messages) == 10

    @pytest.mark.asyncio
    async def test_multiple_rounds_until_policy_returns_none(self, tmp_path: Path):
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(return_value=_ok_tool_response())
        session = Session(key=SESSION_KEY)
        for i in range(20):
            session.add_message("user", f"msg {i}")
            session.add_message("assistant", f"reply {i}")

        chunk1 = session.messages[:10]
        chunk2 = session.messages[10:20]
        responses = [chunk1, chunk2, None]
        policy = MagicMock()
        policy.should_consolidate = AsyncMock(side_effect=responses)
        c = _make_consolidator(tmp_path, provider, policy=policy)

        await c.maybe_consolidate(session)

        assert policy.should_consolidate.await_count == 3
        assert len(session.messages) == 20  # 40 - 20 removed


# ---------------------------------------------------------------------------
# Tests: consolidate_messages (with retries)
# ---------------------------------------------------------------------------

class TestConsolidateMessages:
    """consolidate_messages retries on transient failures."""

    @pytest.mark.asyncio
    async def test_retries_and_eventually_succeeds(self, tmp_path: Path):
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(return_value=_ok_tool_response())
        c = _make_consolidator(tmp_path, provider)

        result = await c.consolidate_messages(SESSION_KEY, [{"role": "user", "content": "hi"}])

        assert result is True


# ---------------------------------------------------------------------------
# Tests: lock isolation
# ---------------------------------------------------------------------------

class TestLockIsolation:
    """Consolidation locks are per-session."""

    def test_different_sessions_get_different_locks(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        lock1 = c.get_lock("a:1")
        lock2 = c.get_lock("a:2")
        assert lock1 is not lock2

    def test_same_session_gets_same_lock(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        lock1 = c.get_lock("a:1")
        lock2 = c.get_lock("a:1")
        assert lock1 is lock2


# ---------------------------------------------------------------------------
# Tests: helper functions
# ---------------------------------------------------------------------------

class TestHelperFunctions:
    def test_ensure_text_string(self):
        assert _ensure_text("hello") == "hello"

    def test_ensure_text_dict(self):
        assert _ensure_text({"a": 1}) == '{"a": 1}'

    def test_normalize_save_memory_args_string(self):
        result = _normalize_save_memory_args('{"key": "value"}')
        assert result == {"key": "value"}

    def test_normalize_save_memory_args_list(self):
        result = _normalize_save_memory_args([{"key": "value"}])
        assert result == {"key": "value"}

    def test_normalize_save_memory_args_list_non_dict(self):
        result = _normalize_save_memory_args(["string"])
        assert result is None

    def test_normalize_save_memory_args_empty_list(self):
        result = _normalize_save_memory_args([])
        assert result is None

    def test_normalize_save_memory_args_dict(self):
        result = _normalize_save_memory_args({"key": "value"})
        assert result == {"key": "value"}

    def test_format_messages(self):
        messages = [
            {"role": "user", "content": "hello", "timestamp": "2026-05-27 10:00:00"},
            {"role": "assistant", "content": "hi", "timestamp": "2026-05-27 10:01:00"},
        ]
        result = _format_messages(messages)
        assert "USER: hello" in result
        assert "ASSISTANT: hi" in result

    def test_format_messages_with_tools(self):
        messages = [
            {"role": "assistant", "content": "result", "tools_used": ["search"], "timestamp": "2026-05-27 10:00:00"},
        ]
        result = _format_messages(messages)
        assert "[tools: search]" in result

    def test_format_messages_skips_empty_content(self):
        messages = [
            {"role": "tool", "content": "", "timestamp": "2026-05-27 10:00:00"},
        ]
        result = _format_messages(messages)
        assert result == ""


# ---------------------------------------------------------------------------
# Tests: backward-compat self.store
# ---------------------------------------------------------------------------

class TestBackwardCompatStore:
    """self.store is maintained for existing callers."""

    def test_store_is_memory_store(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        assert isinstance(c.store, MemoryStore)

    def test_store_uses_legacy_directory(self, tmp_path: Path):
        c = _make_consolidator(tmp_path)
        assert c.store.memory_dir == tmp_path / "memory"
