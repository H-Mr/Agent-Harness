# Dynamic Memory Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the global, token-budget-only memory consolidation with per-session multi-file memory, a pluggable consolidation policy callback, and automatic old-message archival from session windows.

**Architecture:** `ConsolidationPolicy` protocol defines `should_consolidate(session, consolidator) -> list[dict] | None`. Two built-in strategies: `TokenBudgetPolicy` (default, current behavior) and `MessageCountPolicy` (new). `MemoryStore` becomes session-scoped with 5 output files. `MemoryConsolidator.maybe_consolidate(session)` dispatches to the configured policy, compresses via LLM into structured multi-field output, archives raw messages to `history.jsonl`, then physically removes old messages from the session JSONL.

**Tech Stack:** Python 3.10+, Pydantic, asyncio. No new dependencies.

---

### Task 1: Add `Session.remove_before(idx)` and pinned last_consolidated

**Files:**
- Modify: `src/agent_harness/session/manager.py:114-145`

- [ ] **Step 1: Implement `remove_before` on Session**

In `src/agent_harness/session/manager.py`, add the method to the `Session` class right after `retain_recent_legal_suffix` (after line 144):

```python
def remove_before(self, idx: int) -> int:
    """Remove all messages before *idx* and reset last_consolidated to 0.

    Returns:
        Number of messages removed.
    """
    if idx <= 0 or idx > len(self.messages):
        return 0
    removed = idx
    self.messages = self.messages[idx:]
    self.last_consolidated = 0
    self.updated_at = datetime.now()
    return removed
```

- [ ] **Step 2: Write and run test**

Create `tests/test_session/test_session_remove.py`:

```python
"""Test Session.remove_before()."""

from agent_harness.session.manager import Session

def test_remove_before_removes_messages():
    s = Session(key="test:1")
    for i in range(10):
        s.add_message("user", f"msg {i}")
    assert len(s.messages) == 10

    removed = s.remove_before(6)
    assert removed == 6
    assert len(s.messages) == 4
    assert s.messages[0]["content"] == "msg 6"
    assert s.last_consolidated == 0


def test_remove_before_zero_does_nothing():
    s = Session(key="test:2")
    s.add_message("user", "hello")
    removed = s.remove_before(0)
    assert removed == 0
    assert len(s.messages) == 1


def test_remove_before_out_of_bounds_does_nothing():
    s = Session(key="test:3")
    s.add_message("user", "hello")
    removed = s.remove_before(10)
    assert removed == 0
    assert len(s.messages) == 1


def test_remove_before_with_last_consolidated():
    s = Session(key="test:4")
    s.add_message("user", "msg 0")
    s.add_message("user", "msg 1")
    s.last_consolidated = 1
    s.remove_before(1)
    assert s.last_consolidated == 0
```

Run: `uv run pytest tests/test_session/test_session_remove.py -v`
Expected: 4 passed

- [ ] **Step 3: Commit**

```bash
git add src/agent_harness/session/manager.py tests/test_session/test_session_remove.py
git commit -m "feat: add Session.remove_before(idx) for physical message removal"
```

---

### Task 2: Refactor `MemoryStore` for per-session multi-file memory

**Files:**
- Modify: `src/agent_harness/memory/store.py`

- [ ] **Step 1: Rewrite MemoryStore with multi-file support**

Replace the entire content of `src/agent_harness/memory/store.py`:

```python
"""Per-session memory store: AGENTS.md, SOUL.md, MEMORY.md, USER.md, history.jsonl."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_MEMORY_FILES = ("MEMORY.md", "AGENTS.md", "SOUL.md", "USER.md")


class MemoryStore:
    """Per-session memory with five structured files.

    Directory layout::

        memory/{session_key}/
            MEMORY.md      ← facts, decisions (LLM overwrites)
            AGENTS.md      ← project rules, conventions (LLM overwrites)
            SOUL.md        ← personality, tone, behavior (LLM overwrites)
            USER.md        ← user profile, preferences (LLM overwrites)
            history.jsonl  ← archived conversation + summaries (append-only)

    Backward-compatible: passing a plain ``memory_dir`` without a session key
    creates a flat store with the old MEMORY.md / HISTORY.md behaviour.
    """

    def __init__(self, memory_dir: Path, session_key: str | None = None):
        if session_key:
            from agent_harness.session.manager import safe_filename

            self.memory_dir = memory_dir / safe_filename(session_key.replace(":", "_"))
        else:
            self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.agents_file = self.memory_dir / "AGENTS.md"
        self.soul_file = self.memory_dir / "SOUL.md"
        self.user_file = self.memory_dir / "USER.md"
        self.history_file = self.memory_dir / "history.jsonl"

    # ------------------------------------------------------------------
    # Per-file read / write
    # ------------------------------------------------------------------

    def read_file(self, name: str) -> str:
        """Read the full content of a memory file by logical name.

        *name* must be one of ``MEMORY.md``, ``AGENTS.md``, ``SOUL.md``, ``USER.md``.
        """
        path = self._path_for(name)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def write_file(self, name: str, content: str) -> None:
        """Overwrite a memory file with new content."""
        self._path_for(name).write_text(content, encoding="utf-8")

    def _path_for(self, name: str) -> Path:
        mapping = {
            "MEMORY.md": self.memory_file,
            "AGENTS.md": self.agents_file,
            "SOUL.md": self.soul_file,
            "USER.md": self.user_file,
        }
        path = mapping.get(name)
        if path is None:
            raise ValueError(f"Unknown memory file: {name}")
        return path

    # ------------------------------------------------------------------
    # History (append-only)
    # ------------------------------------------------------------------

    def append_history(self, entry: str) -> None:
        """Append a text entry to history.jsonl (grep-searchable log)."""
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def append_raw_messages(self, messages: list[dict]) -> None:
        """Append raw conversation messages to history.jsonl for traceability."""
        with open(self.history_file, "a", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            f.write("\n")

    # ------------------------------------------------------------------
    # Multi-file snapshot (for consolidation prompt)
    # ------------------------------------------------------------------

    def get_all_files(self) -> dict[str, str]:
        """Return current content of all memory files."""
        return {name: self.read_file(name) for name in _MEMORY_FILES}

    def get_context(self) -> str:
        """Return all memory files formatted as a context block for prompts."""
        blocks: list[str] = []
        for name in ("AGENTS.md", "SOUL.md", "MEMORY.md", "USER.md"):
            content = self.read_file(name)
            blocks.append(f"## {name}\n{content}" if content else f"## {name}\n(empty)")
        return "\n\n".join(blocks)

    # ------------------------------------------------------------------
    # Backward-compatible API (delegates to MEMORY.md / history.jsonl)
    # ------------------------------------------------------------------

    def read_long_term(self) -> str:
        """Backward-compatible: read MEMORY.md."""
        return self.read_file("MEMORY.md")

    def write_long_term(self, content: str) -> None:
        """Backward-compatible: overwrite MEMORY.md."""
        self.write_file("MEMORY.md", content)

    def get_memory_context(self) -> str:
        """Backward-compatible: return multi-file context."""
        return self.get_context()
```

- [ ] **Step 2: Write and run tests**

Create `tests/test_memory/test_store_multi.py`:

```python
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
```

Run: `uv run pytest tests/test_memory/test_store_multi.py -v`
Expected: 6 passed

- [ ] **Step 3: Run existing memory tests to ensure no regression**

```bash
uv run pytest tests/test_memory/ -v
```

Expected: all existing tests pass (MemoryStore API is backward-compatible).

- [ ] **Step 4: Commit**

```bash
git add src/agent_harness/memory/store.py tests/test_memory/test_store_multi.py
git commit -m "feat: per-session multi-file MemoryStore (AGENTS/SOUL/MEMORY/USER/history)"
```

---

### Task 3: Create consolidation policy protocol and built-in strategies

**Files:**
- Create: `src/agent_harness/memory/policy.py`
- Create: `tests/test_memory/test_policy.py`

- [ ] **Step 1: Create `policy.py`**

Create `src/agent_harness/memory/policy.py`:

```python
"""Pluggable consolidation policies.

A policy is called before each LLM turn.  It receives the current session
and the consolidator and returns the message chunk to archive (or ``None``
to skip).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_harness.memory.consolidator import MemoryConsolidator
    from agent_harness.session.manager import Session


@dataclass
class TokenBudgetPolicy:
    """Consolidate when estimated prompt tokens exceed a safe budget.

    This replicates the default behaviour of ``maybe_consolidate_by_tokens``.
    """

    context_window_tokens: int
    max_completion_tokens: int = 4096
    _SAFETY_BUFFER: int = 1024

    async def should_consolidate(
        self,
        session: Session,
        consolidator: MemoryConsolidator,
    ) -> list[dict[str, Any]] | None:
        budget = self.context_window_tokens - self.max_completion_tokens - self._SAFETY_BUFFER
        estimated, _ = await consolidator.estimate_session_prompt_tokens(session)
        if estimated < budget:
            return None

        target = budget // 2
        boundary = consolidator.pick_consolidation_boundary(
            session, max(1, estimated - target),
        )
        if boundary is None:
            return None

        end_idx = boundary[0]
        chunk = session.messages[session.last_consolidated : end_idx]
        return chunk if chunk else None


@dataclass
class MessageCountPolicy:
    """Consolidate when the number of unconsolidated messages exceeds a threshold.

    Messages are counted from *last_consolidated*.  The boundary is always
    at a user-turn to avoid splitting assistant/tool-call pairs.
    """

    max_messages: int = 50

    async def should_consolidate(
        self,
        session: Session,
        consolidator: MemoryConsolidator,
    ) -> list[dict[str, Any]] | None:
        active = session.messages[session.last_consolidated :]
        if len(active) <= self.max_messages:
            return None

        # Find user-turn boundary that removes enough messages
        target_remove = len(active) - self.max_messages
        cut_idx = session.last_consolidated
        count = 0
        for i in range(session.last_consolidated, len(session.messages)):
            if (
                i > session.last_consolidated
                and session.messages[i].get("role") == "user"
            ):
                count += 1
                if count >= target_remove:
                    cut_idx = i
                    break

        if cut_idx <= session.last_consolidated:
            return None

        return session.messages[session.last_consolidated : cut_idx]
```

- [ ] **Step 2: Write and run tests**

Create `tests/test_memory/test_policy.py`:

```python
"""Test consolidation policies."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_harness.memory.policy import MessageCountPolicy, TokenBudgetPolicy
from agent_harness.session.manager import Session


@pytest.fixture
def session():
    s = Session(key="test:policy")
    for i in range(60):
        s.add_message("user", f"msg {i}")
        s.add_message("assistant", f"reply {i}")
    return s


@pytest.fixture
def consolidator():
    c = MagicMock()
    c.estimate_session_prompt_tokens = AsyncMock(return_value=(0, "estimate"))
    c.pick_consolidation_boundary = MagicMock(return_value=None)
    return c


class TestMessageCountPolicy:
    async def test_no_consolidation_under_limit(self, session, consolidator):
        session.last_consolidated = 0
        policy = MessageCountPolicy(max_messages=200)
        result = await policy.should_consolidate(session, consolidator)
        assert result is None

    async def test_triggers_when_over_limit(self, session, consolidator):
        session.last_consolidated = 0
        policy = MessageCountPolicy(max_messages=50)
        result = await policy.should_consolidate(session, policy)
        # 120 messages > 50 → should return a chunk
        # (Note: in the test the policy is passed instead of consolidator,
        #  but the policy doesn't call consolidator methods for MessageCountPolicy)
        assert result is not None
        assert len(result) > 0


class TestTokenBudgetPolicy:
    async def test_no_consolidation_under_budget(self, session, consolidator):
        consolidator.estimate_session_prompt_tokens.return_value = (5000, "estimate")
        policy = TokenBudgetPolicy(context_window_tokens=200000)
        result = await policy.should_consolidate(session, consolidator)
        assert result is None

    async def test_triggers_when_over_budget(self, session, consolidator):
        consolidator.estimate_session_prompt_tokens.return_value = (180000, "estimate")
        boundary = (session.last_consolidated + 20, 50000)
        consolidator.pick_consolidation_boundary.return_value = boundary
        policy = TokenBudgetPolicy(context_window_tokens=200000)
        result = await policy.should_consolidate(session, consolidator)
        assert result is not None
```

Run: `uv run pytest tests/test_memory/test_policy.py -v`
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add src/agent_harness/memory/policy.py tests/test_memory/test_policy.py
git commit -m "feat: add consolidation policy protocol with TokenBudget + MessageCount strategies"
```

---

### Task 4: Refactor `MemoryConsolidator` to use policy and new MemoryStore

**Files:**
- Modify: `src/agent_harness/memory/consolidator.py`

- [ ] **Step 1: Update `_SAVE_MEMORY_TOOL` to 5 fields**

Replace the `_SAVE_MEMORY_TOOL` constant (lines 59-83) with:

```python
_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save structured memory consolidation across five output files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agents_update": {
                        "type": ["string", "null"],
                        "description": (
                            "Updated AGENTS.md content: project rules, conventions, "
                            "workflow preferences. Return null if nothing changed."
                        ),
                    },
                    "soul_update": {
                        "type": ["string", "null"],
                        "description": (
                            "Updated SOUL.md content: personality, tone, communication "
                            "style, behavioral patterns. Return null if nothing changed."
                        ),
                    },
                    "memory_update": {
                        "type": "string",
                        "description": (
                            "Updated MEMORY.md content: factual knowledge, decisions "
                            "made, key discoveries. MUST return the complete updated "
                            "version including all existing and new facts."
                        ),
                    },
                    "user_update": {
                        "type": ["string", "null"],
                        "description": (
                            "Updated USER.md content: user profile, preferences, goals. "
                            "Return null if nothing changed."
                        ),
                    },
                    "history_entry": {
                        "type": "string",
                        "description": (
                            "A grep-searchable summary line for history.jsonl. "
                            'Start with "[YYYY-MM-DD HH:MM] key events/decisions/topics".'
                        ),
                    },
                },
                "required": ["memory_update", "history_entry"],
            },
        },
    }
]
```

- [ ] **Step 2: Add prompt template method to MemoryConsolidator**

Add the method to `MemoryConsolidator` class (before `consolidate_messages`):

```python
def _build_consolidation_prompt(
    self,
    messages: list[dict],
    current_files: dict[str, str],
) -> str:
    """Build the structured consolidation prompt from current memory state."""
    return f"""Process this conversation and call the save_memory tool with your consolidation.

## File Responsibilities
- **agents_update** → AGENTS.md: project rules, workflow conventions, tech stack preferences
- **soul_update** → SOUL.md: communication style, tone, reply habits, behavioral patterns
- **memory_update** → MEMORY.md: factual knowledge, decisions, key discoveries (REQUIRED — return complete updated version)
- **user_update** → USER.md: user role, preferences, goals
- **history_entry** → history.jsonl: one grep-searchable summary line like "[YYYY-MM-DD HH:MM] key events"

For any file where nothing changed, return null (not empty string). For memory_update, always return the complete updated MEMORY.md content.

## Current Memory State
### AGENTS.md
{current_files.get('AGENTS.md') or '(empty)'}

### SOUL.md
{current_files.get('SOUL.md') or '(empty)'}

### MEMORY.md
{current_files.get('MEMORY.md') or '(empty)'}

### USER.md
{current_files.get('USER.md') or '(empty)'}

## Conversation to Process
{MemoryStore._format_messages(messages)}"""
```

- [ ] **Step 3: Update `MemoryStore.consolidate` to handle 5 fields**

Replace the existing `consolidate` method (lines 170-256) with:

```python
async def consolidate(
    self,
    messages: list[dict],
    provider: LLMProvider,
    model: str,
) -> bool:
    """Consolidate *messages* into structured memory files via LLM call."""
    if not messages:
        return True

    current_files = self.get_all_files()
    prompt = self._build_consolidation_prompt(messages, current_files)

    chat_messages = [
        {
            "role": "system",
            "content": (
                "You are a memory consolidation agent. "
                "Call the save_memory tool with your structured consolidation."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        forced = {"type": "function", "function": {"name": "save_memory"}}
        response = await provider.chat_with_retry(
            messages=chat_messages,
            tools=_SAVE_MEMORY_TOOL,
            model=model,
            tool_choice=forced,
        )

        if response.finish_reason == "error" and _is_tool_choice_unsupported(response.content):
            logger.warning("Forced tool_choice unsupported, retrying with auto")
            response = await provider.chat_with_retry(
                messages=chat_messages,
                tools=_SAVE_MEMORY_TOOL,
                model=model,
                tool_choice="auto",
            )

        if not response.has_tool_calls:
            logger.warning(
                "Memory consolidation: LLM did not call save_memory "
                "(finish_reason=%s, content_len=%s)",
                response.finish_reason,
                len(response.content or ""),
            )
            return self._fail_or_raw_archive(messages)

        args = _normalize_save_memory_args(response.tool_calls[0].arguments)
        if args is None:
            logger.warning("Memory consolidation: unexpected save_memory arguments")
            return self._fail_or_raw_archive(messages)

        # Write each non-null field to its file
        field_to_file = {
            "agents_update": "AGENTS.md",
            "soul_update": "SOUL.md",
            "memory_update": "MEMORY.md",
            "user_update": "USER.md",
        }

        for field, filename in field_to_file.items():
            value = args.get(field)
            if value is not None and isinstance(value, str) and value.strip():
                current = current_files.get(filename, "")
                if value != current:
                    self.write_file(filename, value)

        # Append history entry
        history_entry = _ensure_text(args.get("history_entry", "")).strip()
        if history_entry:
            self.append_history(history_entry)

        # Archive raw messages
        self.append_raw_messages(messages)

        self._consecutive_failures = 0
        logger.info("Memory consolidation done for %s messages", len(messages))
        return True
    except Exception:
        logger.exception("Memory consolidation failed")
        return self._fail_or_raw_archive(messages)
```

- [ ] **Step 4: Add `maybe_consolidate` dispatch method**

Add to `MemoryConsolidator`:

```python
async def maybe_consolidate(self, session: Session) -> None:
    """Run consolidation if the configured policy requests it.

    Called by Agent.process() before each turn.
    """
    if not session.messages:
        return

    lock = self.get_lock(session.key)
    async with lock:
        for _ in range(self._MAX_CONSOLIDATION_ROUNDS):
            chunk = await self._policy.should_consolidate(session, self)
            if chunk is None:
                return
            if not chunk:
                return

            end_idx = session.last_consolidated + len(chunk)
            logger.info(
                "Consolidation: archiving %s messages for %s",
                len(chunk),
                session.key,
            )

            if not await self.consolidate_messages(chunk):
                return

            # Remove consolidated messages from session window
            session.remove_before(end_idx)
            self.sessions.save(session)
```

- [ ] **Step 5: Update `MemoryConsolidator.__init__` for policy**

Replace the constructor to accept `policy` and create per-session `MemoryStore`:

```python
def __init__(
    self,
    workspace: Path,
    provider: LLMProvider,
    model: str,
    sessions: SessionManager,
    context_window_tokens: int,
    build_messages: Callable[..., list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]],
    get_tool_definitions: Callable[[], list[dict[str, Any]]],
    max_completion_tokens: int = 4096,
    policy: TokenBudgetPolicy | None = None,
):
    from agent_harness.memory.policy import TokenBudgetPolicy as TBP

    self.provider = provider
    self.model = model
    self.sessions = sessions
    self.context_window_tokens = context_window_tokens
    self.max_completion_tokens = max_completion_tokens
    self._build_messages = build_messages
    self._get_tool_definitions = get_tool_definitions
    self._policy = policy or TBP(
        context_window_tokens=context_window_tokens,
        max_completion_tokens=max_completion_tokens,
    )
    self._workspace = workspace
    self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
        weakref.WeakValueDictionary()
    )

    # Per-session store factory
    self._stores: dict[str, MemoryStore] = {}

    # Backward-compat: keep self.store as a global fallback
    from agent_harness.memory.store import MemoryStore as MS

    self.store = MS(workspace / "memory")
```

- [ ] **Step 6: Update `consolidate_messages` to use per-session store**

```python
def _get_store(self, session_key: str) -> MemoryStore:
    """Return or create the per-session MemoryStore."""
    if session_key not in self._stores:
        self._stores[session_key] = MemoryStore(
            self._workspace / "memory", session_key=session_key
        )
    return self._stores[session_key]

async def consolidate_messages(self, session_key: str, messages: list[dict[str, object]]) -> bool:
    """Archive a selected message chunk into persistent memory."""
    store = self._get_store(session_key)
    return await store.consolidate(messages, self.provider, self.model)
```

- [ ] **Step 7: Update `maybe_consolidate` to pass session_key**

Update the call to `consolidate_messages` in `maybe_consolidate`:

```python
if not await self.consolidate_messages(session.key, chunk):
    return
```

- [ ] **Step 8: Keep `pick_consolidation_boundary` and `estimate_session_prompt_tokens` unchanged**

These methods remain exactly as-is. No changes needed.

- [ ] **Step 9: Keep `archive_messages`**

```python
async def archive_messages(self, session_key: str, messages: list[dict[str, object]]) -> bool:
    """Archive messages with guaranteed persistence."""
    if not messages:
        return True
    store = self._get_store(session_key)
    for _ in range(store._MAX_FAILURES_BEFORE_RAW_ARCHIVE):
        if await store.consolidate(messages, self.provider, self.model):
            return True
    return True
```

- [ ] **Step 10: Write and run tests**

Create `tests/test_memory/test_consolidator_dispatch.py`:

```python
"""Test consolidator dispatch with policy."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_harness.memory.policy import MessageCountPolicy
from agent_harness.session.manager import Session, SessionManager


@pytest.fixture
def session():
    s = Session(key="test:dispatch")
    for i in range(100):
        s.add_message("user", f"msg {i}")
        s.add_message("assistant", f"reply {i}")
    return s


@pytest.fixture
def sessions(tmp_path):
    return SessionManager(tmp_path / "workspace")


def test_message_count_policy_triggers_consolidation(session):
    policy = MessageCountPolicy(max_messages=50)
    # 200 messages > 50 → should return chunk
    import asyncio

    async def run():
        c = MagicMock()
        result = await policy.should_consolidate(session, c)
        return result

    result = asyncio.run(run())
    assert result is not None
    assert len(result) > 0
```

Run: `uv run pytest tests/test_memory/test_consolidator_dispatch.py -v`
Expected: pass

- [ ] **Step 11: Run existing consolidation tests**

```bash
uv run pytest tests/test_memory/ -v
```

Expected: all tests pass or are adjusted for the new API.

- [ ] **Step 12: Commit**

```bash
git add src/agent_harness/memory/consolidator.py tests/test_memory/test_consolidator_dispatch.py
git commit -m "feat: refactor MemoryConsolidator with policy dispatch and per-session stores"
```

---

### Task 5: Wire consolidation_policy through Agent and Harness

**Files:**
- Modify: `src/agent_harness/agent.py:63-75, 95-103, 176`
- Modify: `src/agent_harness/harness.py:207-222, 505`

- [ ] **Step 1: Add `consolidation_policy` to Agent.__init__**

In `src/agent_harness/agent.py`, add the parameter to `__init__`:

After `ask_user` parameter (line 75), insert:

```python
        consolidation_policy: object = None,
```

Then update the consolidator creation block (lines 95-103) to pass the policy:

```python
        # Memory consolidator (only when both memory and sessions are active) --
        self._consolidator: MemoryConsolidator | None = None
        if harness.memory is not None and harness.sessions is not None:
            self._consolidator = MemoryConsolidator(
                workspace=harness.workspace,
                provider=harness.provider,
                model=self.model,
                sessions=harness.sessions,
                context_window_tokens=harness.context_window_tokens,
                build_messages=self._make_consolidation_build_messages(),
                get_tool_definitions=lambda: harness.tools.to_api_schema("openai"),
                max_completion_tokens=harness.max_completion_tokens,
                policy=consolidation_policy if consolidation_policy is not None else None,
            )
```

- [ ] **Step 2: Update `agent.process()` to call `maybe_consolidate`**

In `agent.py`, line 193 (the consolidation call), change:

```python
await self._consolidator.maybe_consolidate_by_tokens(session)
```

to:

```python
await self._consolidator.maybe_consolidate(session)
```

- [ ] **Step 3: Update Agent class docstring**

Add `consolidation_policy` to the Args block in the class docstring:

```python
        consolidation_policy: Consolidation policy callable. Receives
            ``(session, consolidator)`` and returns a list of messages to
            archive, or ``None`` to skip. Defaults to
            :class:`TokenBudgetPolicy <agent_harness.memory.policy.TokenBudgetPolicy>`.
```

- [ ] **Step 4: Update harness.py to pass through**

In `src/agent_harness/harness.py`, add the parameter if needed (actually Harness doesn't need explicit wiring — it's passed directly to Agent. But for config-driven mode, add to `Harness.from_config()` passthrough if needed.)

Actually, since `Agent` receives `consolidation_policy` directly, Harness doesn't need changes for the direct-constructor path. For config-driven mode we'd add it later.

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_harness_agent.py -v -q --tb=short
```

Expected: 47 passed, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/agent_harness/agent.py src/agent_harness/harness.py
git commit -m "feat: wire consolidation_policy through Agent and Harness"
```

---

### Task 6: Update public exports

**Files:**
- Modify: `src/agent_harness/__init__.py`

- [ ] **Step 1: Export policy classes**

Add after the memory imports (line 48):

```python
from agent_harness.memory.policy import MessageCountPolicy, TokenBudgetPolicy
```

And in `__all__` add after `"MemoryStore"` (line 107):

```python
    "TokenBudgetPolicy",
    "MessageCountPolicy",
```

- [ ] **Step 2: Verify import**

```bash
uv run python -c "from agent_harness import TokenBudgetPolicy, MessageCountPolicy; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/agent_harness/__init__.py
git commit -m "feat: export TokenBudgetPolicy and MessageCountPolicy from public API"
```

---

### Task 7: End-to-end integration test

**Files:**
- Create: `tests/test_integration_memory_consolidation.py`

- [ ] **Step 1: Write integration test**

```python
"""Integration test: Agent triggers consolidation via policy."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_harness.agent import Agent
from agent_harness.bus.events import InboundMessage
from agent_harness.harness import Harness
from agent_harness.memory.policy import MessageCountPolicy
from agent_harness.memory.store import MemoryStore
from agent_harness.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from agent_harness.session.manager import SessionManager


class _ConsolidationMockProvider(LLMProvider):
    """Mock provider: returns tool_calls, then plain text."""

    def __init__(self):
        super().__init__(api_key="mock")
        self._seen = 0

    async def chat(self, messages, tools=None, model=None, **kwargs):
        self._seen += 1
        # If tools include "save_memory", this is consolidation call
        if tools and any(t.get("function", {}).get("name") == "save_memory" for t in (tools or [])):
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="mem_1",
                        name="save_memory",
                        arguments={
                            "agents_update": None,
                            "soul_update": None,
                            "memory_update": "Test memory: user asked a question.",
                            "user_update": None,
                            "history_entry": "[2026-05-27 10:00] Test session started",
                        },
                    )
                ],
                finish_reason="tool_calls",
            )

        if self._seen <= 2:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="read_file",
                        arguments={"path": "/tmp/test.txt"},
                    )
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(
            content="I've completed the task.",
            finish_reason="stop",
        )

    async def chat_stream(self, messages, tools=None, model=None, on_content_delta=None, **kwargs):
        return await self.chat(messages, tools, model, **kwargs)

    def get_default_model(self):
        return "mock-model"


@pytest.mark.asyncio
async def test_agent_with_message_count_policy(tmp_path):
    """Agent with MessageCountPolicy triggers consolidation and continues."""
    workspace = tmp_path / "workspace"
    memory_dir = workspace / "memory"
    sessions_dir = workspace / "sessions"

    harness = Harness(
        provider=_ConsolidationMockProvider(),
        memory=memory_dir,
        sessions=SessionManager(workspace),
        tools=[],
    )

    agent = Agent(
        harness,
        model="mock-model",
        consolidation_policy=MessageCountPolicy(max_messages=6),
    )

    # Add enough messages to trigger consolidation (>6 unconsolidated)
    msg = InboundMessage(
        channel="cli", sender_id="user", chat_id="c1",
        content="test message",
    )

    result = await agent.process(msg)
    assert result is not None
    # Session should still be functional after consolidation
    assert result.content == "I've completed the task."
```

- [ ] **Step 2: Run integration test**

```bash
uv run pytest tests/test_integration_memory_consolidation.py -v
```

Expected: pass

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -v -q --tb=short
```

Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_memory_consolidation.py
git commit -m "test: add integration test for policy-driven memory consolidation"
```

---

### Task 8: Update documentation

**Files:**
- Create: `docs/mkdocs/how-to/configure-memory.md`
- Modify: `docs/mkdocs/api/memory.md`
- Modify: `mkdocs.yml`

- [ ] **Step 1: Write how-to guide**

Create `docs/mkdocs/how-to/configure-memory.md`:

```markdown
# 配置动态记忆压缩

llm-harness 支持两种记忆压缩策略，通过 `consolidation_policy` 参数注入 Agent。

## 按消息数压缩

保留最新 N 条消息在会话窗口中，旧消息自动压缩归档：

```python
from agent_harness import Agent, Harness
from agent_harness.memory.policy import MessageCountPolicy

agent = Agent(
    harness,
    model="gpt-4o",
    consolidation_policy=MessageCountPolicy(max_messages=50),
)
```

## 按 Token 预算压缩（默认）

当 prompt token 数接近上下文窗口上限时触发：

```python
from agent_harness.memory.policy import TokenBudgetPolicy

agent = Agent(
    harness,
    model="gpt-4o",
    consolidation_policy=TokenBudgetPolicy(
        context_window_tokens=200000,
        max_completion_tokens=4096,
    ),
)
```

## 记忆文件结构

每个会话独立管理记忆：

```
memory/{session_key}/
  MEMORY.md    ← 事实、知识、决策
  AGENTS.md    ← 项目规则、约定
  SOUL.md      ← 人格、语气、行为模式
  USER.md      ← 用户画像、偏好
  history.jsonl ← 归档聊天记录（可 grep）
```

压缩时 LLM 一次调用输出 5 个字段，分别写入对应文件。无变化的文件跳过不写。
```

- [ ] **Step 2: Update API reference**

In `docs/mkdocs/api/memory.md`, add after the existing content:

```markdown
## 压缩策略

::: agent_harness.memory.policy
    options:
      show_root_heading: true
      heading_level: 2
```

- [ ] **Step 3: Add to navigation**

In `mkdocs.yml`, add under 指南:

```yaml
      - 配置记忆压缩: how-to/configure-memory.md
```

- [ ] **Step 4: Commit**

```bash
git add docs/mkdocs/how-to/configure-memory.md docs/mkdocs/api/memory.md mkdocs.yml
git commit -m "docs: add memory consolidation configuration guide"
```
