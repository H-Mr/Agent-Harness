# Memory & Sessions -- Persistent Agent State

## Overview

Memory and sessions form the two-tier persistence layer that lets an agent
maintain context across conversations and restarts. They work together but serve
different purposes:

- **Sessions** preserve the exact conversation history as JSONL files --
  everything the user and agent said, every tool call and result.
- **Memory** stores distilled knowledge -- long-term facts in MEMORY.md and a
  grep-searchable event log in HISTORY.md.

## Two-Tier Memory

### MEMORY.md (Long-Term Facts)

`MEMORY.md` is a single markdown file containing the agent's accumulated
knowledge about the user, the project, and the world. It is:

- **Read into the system prompt** on every turn, so the LLM always has context
- **Overwritten on each consolidation** -- the LLM rewrites the entire file
  with new facts added and old ones retained
- **Human-readable and editable** -- users can open MEMORY.md and add/remove
  facts directly

```markdown
## Long-term Memory
- User's name is Alice
- Working on project "Nova" -- a task management app
- Preferred coding style: Python with type hints
- Alice's timezone: US/Eastern
```

### HISTORY.md (Grep-Searchable Log)

`HISTORY.md` is an append-only file that records events, decisions, and
consolidation summaries. It is:

- **Append-only** -- entries are never modified after writing
- **Timestamped** -- each entry starts with `[YYYY-MM-DD HH:MM]`
- **Grep-searchable** -- users and agents can search HISTORY.md for past events
- **Written during consolidation** -- the LLM summarizes a batch of messages

```markdown
[2026-05-24 10:15] USER: Asked about project architecture. Discussed microservices vs monolith.
[2026-05-24 10:15] ASSISTANT: Recommended microservices for team of 5+.

[2026-05-24 11:30] [RAW] 12 messages
[2026-05-24 11:30] USER: What's the deployment strategy?
[2026-05-24 11:30] ASSISTANT: Recommended Kubernetes with Helm charts.
```

!!! tip "Raw-archive fallback"
    After 3 consecutive LLM consolidation failures, the system falls back to
    raw-archiving messages directly into HISTORY.md without LLM summarization.
    This ensures no data is lost even when the LLM is unavailable.

### MemoryStore API

```python
from pathlib import Path
from agent_harness.memory.store import MemoryStore

store = MemoryStore(Path("~/.my-agent/memory"))

# Long-term
long_term = store.read_long_term()       # Read MEMORY.md
store.write_long_term(new_content)       # Overwrite MEMORY.md

# History
store.append_history("[2026-05-24 12:00] ...")  # Append to HISTORY.md

# Context for system prompt
context_block = store.get_memory_context()
# Returns: "## Long-term Memory\n..." (empty string if no MEMORY.md)
```

## MemoryConsolidator

The `MemoryConsolidator` is the policy engine that decides when to archive
messages, selects which messages to archive, and drives the LLM-based
summarization.

```python
from agent_harness.memory.consolidator import MemoryConsolidator

consolidator = MemoryConsolidator(
    workspace=workspace_path,
    provider=llm_provider,
    model="claude-sonnet-4-20250514",
    sessions=session_manager,
    context_window_tokens=200_000,
    build_messages=my_build_fn,
    get_tool_definitions=my_get_tools_fn,
    max_completion_tokens=8192,
)
```

### Consolidation Policy

The consolidator is invoked by `Agent.process()` before the ReAct loop via
`maybe_consolidate_by_tokens()`. The algorithm is:

```
1. Calculate budget:
       budget = context_window_tokens - max_completion_tokens - SAFETY_BUFFER

2. Set target:
       target = budget // 2

3. If estimated prompt tokens < budget:
       → No consolidation needed, return

4. Loop (up to 5 rounds):
   a. Pick a user-turn boundary in the session that removes enough tokens
   b. Extract the message chunk [last_consolidated .. boundary]
   c. Call consolidate_messages(chunk) → LLM save_memory call
   d. Advance last_consolidated to boundary
   e. Re-estimate; loop if still over target
```

!!! warning "Budget calculation"
    `budget = context_window - max_completion - 1024` (safety buffer).
    The safety buffer compensates for tokenizer estimation drift.

### LLM-Based Summarization with save_memory Tool

Consolidation works by calling the LLM with a forced `save_memory` tool call:

```python
response = await provider.chat_with_retry(
    messages=[
        {"role": "system", "content": "You are a memory consolidation agent..."},
        {"role": "user", "content": prompt},
    ],
    tools=[SAVE_MEMORY_TOOL],
    tool_choice={"type": "function", "function": {"name": "save_memory"}},
)

# The LLM returns a save_memory call with:
#   history_entry: "[YYYY-MM-DD HH:MM] Summary for HISTORY.md"
#   memory_update: "Full markdown content for MEMORY.md"
```

The `save_memory` tool has two parameters:

| Field | Type | Description |
|-------|------|-------------|
| `history_entry` | `string` | A paragraph summarizing key events/decisions. Starts with `[YYYY-MM-DD HH:MM]`. Should include sufficient detail for grep search. |
| `memory_update` | `string` | Full updated long-term memory as markdown. Includes all existing facts plus new ones. Return unchanged if nothing new. |

### Tool Choice Fallback

Some providers don't support forced `tool_choice`. The consolidator detects this
and retries with `tool_choice="auto"`:

```python
if response.finish_reason == "error" and "tool_choice" in (response.content or "").lower():
    response = await provider.chat_with_retry(..., tool_choice="auto")
```

### Raw-Archive Fallback

After `_MAX_FAILURES_BEFORE_RAW_ARCHIVE = 3` consecutive failures, the
consolidator writes messages directly to HISTORY.md without LLM processing:

```python
def _raw_archive(self, messages):
    self.append_history(
        f"[{ts}] [RAW] {len(messages)} messages\n{self._format_messages(messages)}"
    )
```

This guarantees that even if the LLM is broken or unavailable, conversation
history is never lost.

### Consolidation Locking

Each session has its own `asyncio.Lock` for consolidation (stored in a
`WeakValueDictionary`). This prevents two concurrent consolidations for the
same session from interleaving:

```python
async with self.get_lock(session.key):
    # Consolidation logic
```

## Sessions

### JSONL Persistence

Sessions are stored as JSONL (JSON Lines) files in `{workspace}/sessions/`.
Each line is either a metadata header or a message.

```jsonl
{"_type": "metadata", "key": "cli:direct", "created_at": "...", "last_consolidated": 42}
{"role": "user", "content": "Hello!", "timestamp": "2026-05-24T10:00:00"}
{"role": "assistant", "content": "Hi!", "tool_calls": [], "timestamp": "2026-05-24T10:00:01"}
{"role": "tool", "tool_call_id": "call_123", "name": "web_search", "content": "results...", "timestamp": "2026-05-24T10:00:02"}
```

The file name is derived from the session key (channel:chat_id) with
unsafe characters replaced by underscores:

```python
safe_key = safe_filename("cli:direct")      # "cli_direct"
safe_key = safe_filename("discord:12345")   # "discord_12345"
```

### Legal Boundary Alignment

When slicing session history for the LLM context window, `Session.get_history()`
must ensure all tool results have matching assistant tool_call messages.
Otherwise, the LLM API complains about orphaned tool results.

```python
@staticmethod
def _find_legal_start(messages):
    """Find first index where every tool result has a matching assistant tool_call."""
    declared = set()
    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant":
            for tc in msg.get("tool_calls") or []:
                if tc.get("id"):
                    declared.add(str(tc["id"]))
        elif msg.get("role") == "tool":
            tid = msg.get("tool_call_id")
            if tid and str(tid) not in declared:
                # Orphan tool result found -- advance start past it
                start = i + 1
                # Rebuild declared set from new window
    return start
```

### Session.get_history()

```python
def get_history(self, max_messages: int = 500) -> list[dict]:
```

Returns unconsolidated messages (`messages[last_consolidated:]`) for LLM input:

1. Slice to the most recent `max_messages` unconsolidated messages
2. Drop leading non-user messages (to avoid starting mid-turn)
3. Align to a legal tool-call boundary (via `_find_legal_start`)
4. Return only the fields the LLM needs: `role`, `content`, `tool_calls`,
   `tool_call_id`, `name`

### SessionManager API

```python
from pathlib import Path
from agent_harness.session.manager import SessionManager

manager = SessionManager(Path("~/.my-agent"))

# Get or create a session
session = manager.get_or_create("cli:direct")

# Add messages
session.add_message("user", "What's my name?")
session.add_message("assistant", "Your name is Alice.")

# Save to disk
manager.save(session)

# Load back
session = manager.get_or_create("cli:direct")
print(session.messages)  # Restored from JSONL

# List all sessions
for info in manager.list_sessions():
    print(info["key"], info["updated_at"])

# Invalid cache
manager.invalidate("cli:direct")
```

## How Memory and Session Work Together in Agent.process()

The `Agent.process()` method orchestrates both systems:

```python
async def process(self, msg):
    # Session bookkeeping
    session = self.harness.sessions.get_or_create(msg.session_key)
    history = session.get_history()
    session.add_message("user", msg.content)
    self.harness.sessions.save(session)

    # Memory consolidation (pre-turn)
    if self._consolidator is not None:
        await self._consolidator.maybe_consolidate_by_tokens(session)

    # Build context with history (excluding current user message)
    initial_messages = await self.harness.on_build_context(msg, history)

    # Run ReAct loop
    result = await self._loop.run_react_loop(initial_messages)

    # Persist turn
    self._save_turn(session, result, len(initial_messages))
```

The flow ensures:

1. **History is captured before appending** -- `on_build_context` sees the
   session as it was before the current message, preventing duplication
2. **Consolidation happens before the ReAct loop** -- freeing context window
   space before the LLM call
3. **Messages are persisted before the LLM call** -- if the ReAct loop crashes,
   the user message is already saved
4. **Tool results are truncated at 16,000 characters** in session storage
   (configurable via `_TOOL_RESULT_MAX_CHARS`)

---

**Prev:** [Providers](providers.md) | **Next:** [Permissions](permissions.md)
